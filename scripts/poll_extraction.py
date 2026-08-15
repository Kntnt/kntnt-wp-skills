# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Poll a Kntnt Extractor job to a terminal verdict.

This helper is the deterministic seam of the poll discipline (ADR-0018): one
blocking invocation waits on ``GET /extractions/{id}`` and exits exactly once
with a verdict plus the telemetry an evidence block needs. Agents invoke it;
they do not write the loop. The seven numeric literals live here so they
cannot be re-derived differently each run. The main extraction has no
overall wall-clock budget — omit the argv — and the stall window is the stop.

The Application Password is read from ``KNTNT_EXTRACTOR_APP_PASSWORD`` in this
process's environment. It is never accepted on argv, never printed, and never
logged. Invoke the process with the variable in that one environment — prefix
form, not ``export`` — so the secret exists only inside the call that uses it.

Stdout is one JSON object with ``verdict``, ``observed``, and ``inferred``
separated. Stderr is the progress log, including ``gave up after N minutes``
when a stall window or a bounded loop's budget expires. Do not pipe stdout
through ``tee`` without ``set -o pipefail``: the pipeline's exit code must
be this helper's, not tee's.

Exit codes: 0 ready, 1 usage / missing secret, 2 failed state, 3
confirmed-vanished, 4 stall, 5 budget, 6 cache-hit.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, TextIO

# The seven pinned poll-discipline literals (ADR-0018). Move them; do not
# invent new ones. Preflight and bootstrap pass their budget as argv; the
# main extraction omits it.
POLL_CADENCE_SECONDS = 15
PER_REQUEST_TIMEOUT_SECONDS = 120
BACKOFF_FIRST_SECONDS = 30
BACKOFF_SECOND_SECONDS = 60
STALL_WINDOW_SECONDS = 600
PREFLIGHT_BUDGET_SECONDS = 600
BOOTSTRAP_BUDGET_SECONDS = 900

# Existing credential convention (issue #44) — not a new discipline literal.
PASSWORD_ENV = "KNTNT_EXTRACTOR_APP_PASSWORD"

# Existing cache-buster query name — not a new discipline literal.
CACHE_BUSTER_PARAM = "_cb"

# Cache-hit headers an authenticated Extractor call must never accept.
_CACHE_HIT_HEADERS: tuple[tuple[str, str], ...] = (
    ("x-litespeed-cache", "hit"),
    ("cf-cache-status", "hit"),
    ("x-cache", "hit"),
    ("x-proxy-cache", "hit"),
)

EXIT_READY = 0
EXIT_USAGE = 1
EXIT_FAILED = 2
EXIT_CONFIRMED_VANISHED = 3
EXIT_STALL = 4
EXIT_BUDGET = 5
EXIT_CACHE_HIT = 6

_EXIT_BY_VERDICT: dict[str, int] = {
    "ready": EXIT_READY,
    "failed": EXIT_FAILED,
    "confirmed-vanished": EXIT_CONFIRMED_VANISHED,
    "stall": EXIT_STALL,
    "budget": EXIT_BUDGET,
    "cache-hit": EXIT_CACHE_HIT,
}


class Clock(Protocol):
    """Wall time and sleep, injectable so the loop can be tested without waiting."""

    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class HttpResponse:
    """One observed HTTP response. Headers are stored lower-cased."""

    status: int
    headers: dict[str, str]
    body: bytes

    def _replace(self, **changes: Any) -> HttpResponse:
        return replace(self, **changes)


@dataclass(frozen=True)
class PollResult:
    """A terminal verdict plus the observed/inferred split the evidence block wants."""

    verdict: str
    observed: dict[str, Any]
    inferred: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "observed": self.observed,
            "inferred": self.inferred,
        }


@dataclass
class _RealClock:
    """The process wall clock."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass
class _Advance:
    """The last observed progress signature the stall clock compares against."""

    state: str | None = None
    chunks_done: int | None = None
    coarse: int | None = None
    at: float | None = None
    saw_progress: bool = False
    chunks_done_absent: bool = False
    progress: dict[str, Any] | None = None


@dataclass
class _LoopState:
    """Mutable loop counters that are inferred, never observed on the wire."""

    transport_failures: int = 0
    consecutive_failures: int = 0
    previous_was_404: bool = False
    advance: _Advance = field(default_factory=_Advance)


def _log(stream: TextIO, message: str) -> None:
    """Write a progress line to stderr. Never used for secrets."""

    print(message, file=stream, flush=True)


def _cache_hit_header(headers: Mapping[str, str]) -> str | None:
    """Return the cache-hit header name if this authenticated response is cached."""

    lowered = {key.lower(): value for key, value in headers.items()}
    for name, token in _CACHE_HIT_HEADERS:
        if lowered.get(name, "").lower() == token:
            return name
    age = lowered.get("age")
    if age is not None:
        try:
            if int(age) > 0:
                return "age"
        except ValueError:
            pass
    return None


def _append_cache_buster(url: str, value: str) -> str:
    """Attach a unique ``_cb`` so a page cache cannot replay a stored body."""

    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(key, val) for key, val in query if key != CACHE_BUSTER_PARAM]
    query.append((CACHE_BUSTER_PARAM, value))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )


def _job_url(endpoint: str, job_id: str) -> str:
    return f"{endpoint.rstrip('/')}/extractions/{urllib.parse.quote(job_id, safe='')}"


def _list_url(endpoint: str) -> str:
    return f"{endpoint.rstrip('/')}/extractions"


def _parse_body(body: bytes) -> dict[str, Any] | None:
    """Parse a JSON object body, or ``None`` when the bytes are not one."""

    try:
        payload = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _progress_signature(payload: dict[str, Any]) -> tuple[str | None, int | None, int | None, bool]:
    """Return ``(state, chunks_done, coarse_sum, saw_progress)`` from a poll body."""

    state = payload.get("state")
    state_s = state if isinstance(state, str) else None
    progress = payload.get("progress")
    if not isinstance(progress, dict):
        return state_s, None, None, False

    chunks: int | None
    raw_chunks = progress.get("chunks_done")
    chunks = raw_chunks if isinstance(raw_chunks, int) else None

    tables = progress.get("tables_done")
    files = progress.get("files_done")
    coarse = None
    if isinstance(tables, int) or isinstance(files, int):
        coarse = (tables if isinstance(tables, int) else 0) + (
            files if isinstance(files, int) else 0
        )
    return state_s, chunks, coarse, True


def _has_advanced(previous: _Advance, state: str | None, chunks: int | None, coarse: int | None) -> bool:
    """True when state, chunks_done, or the coarse sum moved since last success."""

    if previous.at is None:
        return True
    if state != previous.state:
        return True
    if chunks is not None and previous.chunks_done is not None and chunks > previous.chunks_done:
        return True
    return (
        coarse is not None
        and previous.coarse is not None
        and coarse > previous.coarse
    )


def _listing_ids(payload: dict[str, Any]) -> set[str]:
    """Collect job ids from a ``GET /extractions`` ``{ jobs: [...] }`` body."""

    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return set()
    ids: set[str] = set()
    for job in jobs:
        if isinstance(job, dict) and isinstance(job.get("id"), str):
            ids.add(job["id"])
    return ids


def _result(
    verdict: str,
    *,
    observed: dict[str, Any],
    wall: float,
    transport_failures: int,
    chunks_done_absent: bool,
    gave_up_after_minutes: int | None = None,
) -> PollResult:
    return PollResult(
        verdict=verdict,
        observed=observed,
        inferred={
            "poll_wall_seconds": wall,
            "poll_transport_failures": transport_failures,
            "chunks_done_absent": chunks_done_absent,
            "gave_up_after_minutes": gave_up_after_minutes,
        },
    )


def _backoff_seconds(consecutive_failures: int) -> int:
    """30 s on the first consecutive fault, 60 s from the second onward."""

    if consecutive_failures <= 1:
        return BACKOFF_FIRST_SECONDS
    return BACKOFF_SECOND_SECONDS


def poll(
    *,
    endpoint: str,
    job_id: str,
    budget_seconds: int | None,
    fetch: Callable[..., HttpResponse],
    clock: Clock,
    cache_buster: Callable[[], str],
    log: TextIO | None = None,
) -> PollResult:
    """Block until a terminal verdict. ``fetch`` performs one authenticated GET.

    Args:
        endpoint: Extractor REST base URL, no trailing slash required.
        job_id: The job the caller already submitted.
        budget_seconds: Overall wall-clock budget for the preflight or
            bootstrap, or ``None`` for the main extraction (no overall budget;
            the stall window is the stop).
        fetch: ``fetch(url, timeout=...) -> HttpResponse``. Transport failures
            are signalled by raising; HTTP statuses ride on the response.
        clock: Injectable time source.
        cache_buster: Produces a unique ``_cb`` value per request.
        log: Progress stream, default stderr.

    Returns:
        A ``PollResult`` whose ``verdict`` is ``ready``, ``failed``,
        ``confirmed-vanished``, ``stall``, ``budget``, or ``cache-hit``.
    """

    stream = log if log is not None else sys.stderr
    started = clock.now()
    loop = _LoopState()

    def wall() -> float:
        return clock.now() - started

    def remaining() -> float:
        if budget_seconds is None:
            return float("inf")
        return budget_seconds - wall()

    def give_up(verdict: str, minutes: int, observed: dict[str, Any]) -> PollResult:
        _log(stream, f"gave up after {minutes} minutes")
        return _result(
            verdict,
            observed=observed,
            wall=wall(),
            transport_failures=loop.transport_failures,
            chunks_done_absent=loop.advance.chunks_done_absent,
            gave_up_after_minutes=minutes,
        )

    while True:

        # Stop when a bounded loop's overall budget is already spent.
        if budget_seconds is not None and remaining() <= 0:
            return give_up(
                "budget",
                budget_seconds // 60,
                {
                    "job_id": job_id,
                    "job_state": loop.advance.state,
                    "progress": loop.advance.progress,
                },
            )

        # Stop when nothing has advanced inside the stall window.
        last_at = loop.advance.at if loop.advance.at is not None else started
        if clock.now() - last_at >= STALL_WINDOW_SECONDS:
            return give_up(
                "stall",
                STALL_WINDOW_SECONDS // 60,
                {
                    "job_id": job_id,
                    "job_state": loop.advance.state,
                    "progress": loop.advance.progress,
                },
            )

        # Fetch the job. A cache hit is terminal; transport faults retry.
        job_url = _append_cache_buster(_job_url(endpoint, job_id), cache_buster())
        try:
            response = fetch(job_url, timeout=PER_REQUEST_TIMEOUT_SECONDS)
        except (TimeoutError, ConnectionError, OSError, urllib.error.URLError) as error:
            loop.transport_failures += 1
            loop.consecutive_failures += 1
            loop.previous_was_404 = False
            _log(stream, f"transport fault: {error!s}; retrying")
            clock.sleep(min(_backoff_seconds(loop.consecutive_failures), max(remaining(), 0)))
            continue

        hit = _cache_hit_header(response.headers)
        if hit is not None:
            return _result(
                "cache-hit",
                observed={
                    "job_id": job_id,
                    "http_status": response.status,
                    "cache_header": hit,
                },
                wall=wall(),
                transport_failures=loop.transport_failures,
                chunks_done_absent=loop.advance.chunks_done_absent,
            )

        if response.status == 404:
            loop.transport_failures += 1
            loop.consecutive_failures += 1
            _log(stream, "404 on job poll; treating as transport-class")

            # Confirm vanished only on a re-poll 404 plus an empty listing.
            if loop.previous_was_404:
                listing_url = _append_cache_buster(_list_url(endpoint), cache_buster())
                try:
                    listing = fetch(listing_url, timeout=PER_REQUEST_TIMEOUT_SECONDS)
                except (TimeoutError, ConnectionError, OSError, urllib.error.URLError):
                    listing = None
                else:
                    listing_hit = _cache_hit_header(listing.headers)
                    if listing_hit is not None:
                        return _result(
                            "cache-hit",
                            observed={
                                "job_id": job_id,
                                "http_status": listing.status,
                                "cache_header": listing_hit,
                            },
                            wall=wall(),
                            transport_failures=loop.transport_failures,
                            chunks_done_absent=loop.advance.chunks_done_absent,
                        )
                    payload = _parse_body(listing.body) if listing.status == 200 else None
                    if payload is not None and job_id not in _listing_ids(payload):
                        return _result(
                            "confirmed-vanished",
                            observed={
                                "job_id": job_id,
                                "http_status": 404,
                                "job_state": None,
                            },
                            wall=wall(),
                            transport_failures=loop.transport_failures,
                            chunks_done_absent=loop.advance.chunks_done_absent,
                        )

            loop.previous_was_404 = True
            clock.sleep(min(_backoff_seconds(loop.consecutive_failures), max(remaining(), 0)))
            continue

        if response.status >= 500 or response.status < 200:
            loop.transport_failures += 1
            loop.consecutive_failures += 1
            loop.previous_was_404 = False
            _log(stream, f"HTTP {response.status}; retrying")
            clock.sleep(min(_backoff_seconds(loop.consecutive_failures), max(remaining(), 0)))
            continue

        payload = _parse_body(response.body)
        if payload is None:
            loop.transport_failures += 1
            loop.consecutive_failures += 1
            loop.previous_was_404 = False
            _log(stream, "unparseable poll body; retrying")
            clock.sleep(min(_backoff_seconds(loop.consecutive_failures), max(remaining(), 0)))
            continue

        # A successful poll resets backoff and the 404 confirmation window.
        loop.consecutive_failures = 0
        loop.previous_was_404 = False

        state, chunks, coarse, saw_progress = _progress_signature(payload)
        if saw_progress and chunks is None:
            if not loop.advance.chunks_done_absent:
                _log(
                    stream,
                    "chunks_done absent; stall detection falls back to coarse counters",
                )
            loop.advance.chunks_done_absent = True

        last_progress = payload["progress"] if saw_progress else loop.advance.progress
        if _has_advanced(loop.advance, state, chunks, coarse):
            loop.advance = _Advance(
                state=state,
                chunks_done=chunks,
                coarse=coarse,
                at=clock.now(),
                saw_progress=saw_progress,
                chunks_done_absent=loop.advance.chunks_done_absent,
                progress=last_progress,
            )
        elif saw_progress:
            loop.advance.progress = payload["progress"]

        if saw_progress:
            tables = payload["progress"].get("tables_done", "?")
            tables_total = payload["progress"].get("tables_total", "?")
            files = payload["progress"].get("files_done", "?")
            files_total = payload["progress"].get("files_total", "?")
            _log(stream, f"tables {tables}/{tables_total}, files {files}/{files_total}")

        observed = {
            "job_id": payload.get("id", job_id),
            "job_state": state,
            "download_url": payload.get("download_url"),
            "progress": payload.get("progress"),
            "skipped_files": payload.get("skipped_files", []),
            "http_status": response.status,
            "error": payload.get("error"),
        }

        if state == "failed":
            return _result(
                "failed",
                observed=observed,
                wall=wall(),
                transport_failures=loop.transport_failures,
                chunks_done_absent=loop.advance.chunks_done_absent,
            )

        if state == "ready" and payload.get("download_url"):
            return _result(
                "ready",
                observed=observed,
                wall=wall(),
                transport_failures=loop.transport_failures,
                chunks_done_absent=loop.advance.chunks_done_absent,
            )

        clock.sleep(min(POLL_CADENCE_SECONDS, max(remaining(), 0)))


def _basic_auth_header(user: str, password: str) -> str:
    """Build an Authorization header. The return value is never logged."""

    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _real_fetch(user: str, password: str) -> Callable[..., HttpResponse]:
    """Authenticated GET that never puts the secret in the URL."""

    authorization = _basic_auth_header(user, password)

    def fetch(url: str, *, timeout: float) -> HttpResponse:
        request = urllib.request.Request(url, method="GET")
        request.add_header("Authorization", authorization)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                headers = {key.lower(): value for key, value in response.headers.items()}
                return HttpResponse(status=response.status, headers=headers, body=response.read())
        except urllib.error.HTTPError as error:
            headers = {key.lower(): value for key, value in error.headers.items()}
            return HttpResponse(status=error.code, headers=headers, body=error.read())

    return fetch


def _new_cache_buster() -> str:
    return secrets.token_hex(8)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll a Kntnt Extractor job to a terminal verdict."
    )
    parser.add_argument("endpoint", help="Extractor REST base URL")
    parser.add_argument("job_id", help="Extraction job id")
    parser.add_argument(
        "budget",
        nargs="?",
        type=int,
        default=None,
        help="Overall wall-clock budget in seconds; omit for the main extraction",
    )
    parser.add_argument("--user", required=True, help="WordPress user_login for HTTP basic auth")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    fetch: Callable[..., HttpResponse] | None = None,
    clock: Clock | None = None,
    cache_buster: Callable[[], str] | None = None,
) -> int:
    """CLI entry: parse argv, read the secret from the environment, poll, emit JSON."""

    env = os.environ if environ is None else environ
    parser = _build_parser()
    args = parser.parse_args(argv)

    password = env.get(PASSWORD_ENV, "")
    if not password:
        print(
            f"poll_extraction.py: missing {PASSWORD_ENV} in the process environment",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.budget is not None and args.budget <= 0:
        print("poll_extraction.py: budget must be a positive number of seconds", file=sys.stderr)
        return EXIT_USAGE

    do_fetch = fetch if fetch is not None else _real_fetch(args.user, password)
    result = poll(
        endpoint=args.endpoint,
        job_id=args.job_id,
        budget_seconds=args.budget,
        fetch=do_fetch,
        clock=clock if clock is not None else _RealClock(),
        cache_buster=cache_buster if cache_buster is not None else _new_cache_buster,
    )
    print(json.dumps(result.to_json(), separators=(",", ":")))
    return _EXIT_BY_VERDICT[result.verdict]


if __name__ == "__main__":
    raise SystemExit(main())
