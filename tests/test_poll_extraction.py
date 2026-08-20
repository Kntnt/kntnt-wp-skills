"""Behavioural tests for the extraction-poll helper.

The helper is the deterministic seam that waits on a Kntnt Extractor job
(ADR-0018): one blocking invocation, one terminal verdict, the seven
discipline literals living in the script so an agent cannot re-derive the
loop. Tests drive ``poll()`` through an injected fetcher and clock — never a
live site — and drive ``main()`` for the CLI and credential contract.
"""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import poll_extraction as pe
import pytest

ENDPOINT = "https://example.com/wp-json/kntnt-extractor/v1"
JOB_ID = "job-abc"
PASSWORD = "super-secret-app-password-never-print-me"


class FakeClock:
    """A clock that advances only when the loop sleeps."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class ScriptedFetcher:
    """Returns queued responses per URL path, recording every request."""

    def __init__(self, script: dict[str, list[Any]]) -> None:
        self.script = {path: list(queue) for path, queue in script.items()}
        self.urls: list[str] = []
        self.timeouts: list[float] = []

    def __call__(self, url: str, *, timeout: float) -> pe.HttpResponse:
        self.urls.append(url)
        self.timeouts.append(timeout)
        path = urlparse(url).path
        queue = self.script.get(path)
        if not queue:
            raise AssertionError(f"unexpected fetch of {url}")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _json_response(
    payload: dict[str, Any],
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> pe.HttpResponse:
    return pe.HttpResponse(
        status=status,
        headers=headers or {},
        body=json.dumps(payload).encode(),
    )


def _job(
    state: str,
    *,
    download_url: str | None = None,
    progress: dict[str, int] | None = None,
    error: dict[str, str] | None = None,
    skipped_files: list[str] | None = None,
) -> pe.HttpResponse:
    payload: dict[str, Any] = {"id": JOB_ID, "state": state, "download_url": download_url}
    if progress is not None:
        payload["progress"] = progress
    if error is not None:
        payload["error"] = error
    if skipped_files is not None:
        payload["skipped_files"] = skipped_files
    return _json_response(payload)


def _listing(*ids: str) -> pe.HttpResponse:
    return _json_response({"jobs": [{"id": job_id, "state": "running"} for job_id in ids]})


def _poll(
    script: dict[str, list[Any]],
    *,
    budget: int | None = None,
    clock: FakeClock | None = None,
) -> pe.PollResult:
    clock = clock or FakeClock()
    return pe.poll(
        endpoint=ENDPOINT,
        job_id=JOB_ID,
        budget_seconds=budget,
        fetch=ScriptedFetcher(script),
        clock=clock,
        cache_buster=lambda: "cb1",
    )


def _job_path() -> str:
    return f"/wp-json/kntnt-extractor/v1/extractions/{JOB_ID}"


def _list_path() -> str:
    return "/wp-json/kntnt-extractor/v1/extractions"


def test_ready_on_first_poll_does_not_sleep() -> None:
    """A job that is already ready returns at once with the observed URL."""

    clock = FakeClock()
    result = _poll(
        {
            _job_path(): [
                _job(
                    "ready",
                    download_url="https://example.com/dl",
                    progress={"tables_done": 2, "tables_total": 2, "files_done": 0, "files_total": 0, "chunks_done": 2},
                )
            ]
        },
        clock=clock,
    )

    assert result.verdict == "ready"
    assert result.observed["job_state"] == "ready"
    assert result.observed["download_url"] == "https://example.com/dl"
    assert result.inferred["poll_transport_failures"] == 0
    assert clock.sleeps == []


def test_failed_state_is_terminal() -> None:
    """``state == failed`` is a terminal verdict carrying the plugin error."""

    result = _poll(
        {_job_path(): [_job("failed", error={"message": "disk full"})]}
    )

    assert result.verdict == "failed"
    assert result.observed["job_state"] == "failed"
    assert result.observed["error"] == {"message": "disk full"}


def test_transport_timeout_retries_with_first_backoff_then_succeeds() -> None:
    """A single timeout is never failure; the next success resets the cadence."""

    clock = FakeClock()
    fetcher = ScriptedFetcher(
        {
            _job_path(): [
                TimeoutError("timed out"),
                _job("ready", download_url="https://example.com/dl"),
            ]
        }
    )

    result = pe.poll(
        endpoint=ENDPOINT,
        job_id=JOB_ID,
        budget_seconds=None,
        fetch=fetcher,
        clock=clock,
        cache_buster=lambda: "cb1",
    )

    assert result.verdict == "ready"
    assert result.inferred["poll_transport_failures"] == 1
    assert clock.sleeps == [pe.BACKOFF_FIRST_SECONDS]


def test_second_consecutive_transport_failure_uses_second_backoff() -> None:
    """The second consecutive transport fault waits 60 s, not 30 s."""

    clock = FakeClock()
    pe.poll(
        endpoint=ENDPOINT,
        job_id=JOB_ID,
        budget_seconds=None,
        fetch=ScriptedFetcher(
            {
                _job_path(): [
                    TimeoutError("t1"),
                    ConnectionError("t2"),
                    _job("ready", download_url="https://example.com/dl"),
                ]
            }
        ),
        clock=clock,
        cache_buster=lambda: "cb1",
    )

    assert clock.sleeps == [pe.BACKOFF_FIRST_SECONDS, pe.BACKOFF_SECOND_SECONDS]


def test_single_404_is_not_terminal() -> None:
    """A lone 404 is a transport-class fault; the next ready poll wins."""

    result = _poll(
        {
            _job_path(): [
                pe.HttpResponse(status=404, headers={}, body=b'{"code":"kntnt_extractor_no_such_job"}'),
                _job("ready", download_url="https://example.com/dl"),
            ]
        }
    )

    assert result.verdict == "ready"


def test_confirmed_vanished_requires_second_404_and_absent_listing() -> None:
    """Two 404s plus an empty listing is confirmed-vanished, not a lone 404."""

    result = _poll(
        {
            _job_path(): [
                pe.HttpResponse(status=404, headers={}, body=b""),
                pe.HttpResponse(status=404, headers={}, body=b""),
            ],
            _list_path(): [_listing()],
        }
    )

    assert result.verdict == "confirmed-vanished"
    assert result.observed["http_status"] == 404


def test_second_404_with_job_still_listed_continues() -> None:
    """A rewrite-race 404 pair is not vanished when the listing still has the id."""

    result = _poll(
        {
            _job_path(): [
                pe.HttpResponse(status=404, headers={}, body=b""),
                pe.HttpResponse(status=404, headers={}, body=b""),
                _job("ready", download_url="https://example.com/dl"),
            ],
            _list_path(): [_listing(JOB_ID)],
        }
    )

    assert result.verdict == "ready"


def test_never_2xx_without_budget_stalls_from_loop_start() -> None:
    """Transport-only faults and no budget still give up after the stall window.

    ``advance.at`` is written only after a successful poll. If the stall clock
    required that stamp, a main-extraction loop that never sees a 2xx would
    skip both budget and stall and hang. The clock must run from loop start.
    """

    clock = FakeClock()
    faults_needed = (pe.STALL_WINDOW_SECONDS // pe.BACKOFF_FIRST_SECONDS) + 2
    result = pe.poll(
        endpoint=ENDPOINT,
        job_id=JOB_ID,
        budget_seconds=None,
        fetch=ScriptedFetcher({_job_path(): [TimeoutError("down")] * faults_needed}),
        clock=clock,
        cache_buster=lambda: "cb1",
    )

    assert result.verdict == "stall"
    assert result.inferred["gave_up_after_minutes"] == pe.STALL_WINDOW_SECONDS // 60
    assert result.observed["progress"] is None
    assert clock.t >= pe.STALL_WINDOW_SECONDS
    assert result.inferred["poll_transport_failures"] > 0


def test_stall_without_advance_is_terminal() -> None:
    """Unchanging coarse progress for the stall window is a stall verdict."""

    clock = FakeClock()
    stuck = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0, "chunks_done": 3},
    )
    polls_needed = (pe.STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) + 2
    result = _poll(
        {_job_path(): [stuck] * polls_needed},
        clock=clock,
    )

    assert result.verdict == "stall"
    assert result.inferred["gave_up_after_minutes"] == pe.STALL_WINDOW_SECONDS // 60
    assert result.observed["progress"] == {
        "tables_done": 3,
        "tables_total": 186,
        "files_done": 0,
        "files_total": 0,
        "chunks_done": 3,
    }
    assert any(s == pe.POLL_CADENCE_SECONDS for s in clock.sleeps)


def test_stall_after_advance_keeps_last_progress() -> None:
    """A job that moves, then sits still, give-up JSON still carries last counters."""

    clock = FakeClock()
    first = {
        "tables_done": 3,
        "tables_total": 186,
        "files_done": 0,
        "files_total": 0,
        "chunks_done": 3,
    }
    later = {
        "tables_done": 3,
        "tables_total": 186,
        "files_done": 0,
        "files_total": 0,
        "chunks_done": 4,
    }
    polls_after_advance = (pe.STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) + 2
    result = _poll(
        {_job_path(): [_job("running", progress=first), *[_job("running", progress=later)] * polls_after_advance]},
        clock=clock,
    )

    assert result.verdict == "stall"
    assert result.observed["job_state"] == "running"
    assert result.observed["progress"] == later
    assert result.observed["progress"] is not None


def test_chunks_done_increase_is_an_advance() -> None:
    """A rising ``chunks_done`` resets the stall clock even if tables stay put."""

    clock = FakeClock()
    first = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0, "chunks_done": 3},
    )
    later = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0, "chunks_done": 4},
    )
    ready = _job("ready", download_url="https://example.com/dl", progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0, "chunks_done": 4})
    almost_stall = (pe.STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) - 1

    # Hold tables_done still for just under the stall window, then bump only
    # chunks_done — without that bump the next tick would be a stall.
    running = [first] * almost_stall + [later, ready]
    result = _poll({_job_path(): running}, clock=clock)

    assert result.verdict == "ready"


def test_stall_window_unwidened_when_chunks_done_present() -> None:
    """``chunks_done`` present keeps the 10-minute window even after this change."""

    clock = FakeClock()
    stuck = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0, "chunks_done": 3},
    )
    polls_needed = (pe.STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) + 2
    result = _poll({_job_path(): [stuck] * polls_needed}, clock=clock)

    assert result.verdict == "stall"
    assert result.inferred["gave_up_after_minutes"] == pe.STALL_WINDOW_SECONDS // 60
    assert result.inferred["chunks_done_absent"] is False


def test_stall_window_widens_when_chunks_done_absent() -> None:
    """No ``chunks_done``: 700 s of unchanging coarse counters is not read as a stall.

    This is the regression this plan exists to prevent — under the old,
    unconditional 600 s window this job would have aborted here.
    """

    clock = FakeClock()
    stuck = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0},
    )
    ready = _job("ready", download_url="https://example.com/dl")
    # 47 polls of 15 s cadence carry the clock past 700 s while still stuck;
    # the next poll then resolves, proving the loop was still polling.
    polls_past_700s = (700 // pe.POLL_CADENCE_SECONDS) + 1
    result = _poll({_job_path(): [stuck] * polls_past_700s + [ready]}, clock=clock)

    assert result.verdict == "ready"
    assert clock.t > 700


def test_widened_stall_still_fires_and_reports_forty_minutes() -> None:
    """No ``chunks_done``: unchanging coarse counters past 2400 s is still a stall,
    and the reported give-up minutes come from the widened window, not the
    unconditional 10-minute one."""

    clock = FakeClock()
    stuck = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0},
    )
    polls_needed = (pe.COARSE_STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) + 2
    result = _poll({_job_path(): [stuck] * polls_needed}, clock=clock)

    assert result.verdict == "stall"
    assert result.inferred["gave_up_after_minutes"] == 40
    assert clock.t >= pe.COARSE_STALL_WINDOW_SECONDS


def test_chunks_done_absent_flag_matches_which_window_fired() -> None:
    """The evidence block lets a reader tell which window was in force: ``True``
    when the widened window fired, ``False`` when the narrow one did."""

    narrow_clock = FakeClock()
    narrow_stuck = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0, "chunks_done": 3},
    )
    narrow_polls = (pe.STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) + 2
    narrow_result = _poll({_job_path(): [narrow_stuck] * narrow_polls}, clock=narrow_clock)

    wide_clock = FakeClock()
    wide_stuck = _job(
        "running",
        progress={"tables_done": 3, "tables_total": 186, "files_done": 0, "files_total": 0},
    )
    wide_polls = (pe.COARSE_STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) + 2
    wide_result = _poll({_job_path(): [wide_stuck] * wide_polls}, clock=wide_clock)

    assert narrow_result.inferred["chunks_done_absent"] is False
    assert wide_result.inferred["chunks_done_absent"] is True


def test_unbounded_advancing_job_is_not_budget_killed() -> None:
    """Main extraction has no overall budget: a slow-but-advancing job reaches ready."""

    clock = FakeClock()
    polls_past_old_hour = 250
    advancing = [
        _job(
            "running",
            progress={
                "tables_done": 0,
                "tables_total": 1,
                "files_done": i,
                "files_total": polls_past_old_hour,
                "chunks_done": i,
            },
        )
        for i in range(1, polls_past_old_hour)
    ]
    ready = _job(
        "ready",
        download_url="https://example.com/dl",
        progress={
            "tables_done": 0,
            "tables_total": 1,
            "files_done": polls_past_old_hour,
            "files_total": polls_past_old_hour,
            "chunks_done": polls_past_old_hour,
        },
    )
    result = pe.poll(
        endpoint=ENDPOINT,
        job_id=JOB_ID,
        budget_seconds=None,
        fetch=ScriptedFetcher({_job_path(): [*advancing, ready]}),
        clock=clock,
        cache_buster=lambda: "cb1",
    )

    assert result.verdict == "ready"
    assert clock.t > 3600

def test_budget_exhaustion_prints_give_up_line() -> None:
    """A preflight/bootstrap job that keeps advancing still dies when its budget expires."""

    clock = FakeClock()
    stderr = io.StringIO()
    advancing = [
        _job(
            "running",
            progress={
                "tables_done": i,
                "tables_total": 1000,
                "files_done": 0,
                "files_total": 0,
                "chunks_done": i,
            },
        )
        for i in range(1, 80)
    ]
    result = pe.poll(
        endpoint=ENDPOINT,
        job_id=JOB_ID,
        budget_seconds=pe.PREFLIGHT_BUDGET_SECONDS,
        fetch=ScriptedFetcher({_job_path(): advancing}),
        clock=clock,
        cache_buster=lambda: "cb1",
        log=stderr,
    )

    assert result.verdict == "budget"
    assert result.inferred["gave_up_after_minutes"] == pe.PREFLIGHT_BUDGET_SECONDS // 60
    assert result.observed["progress"] is not None
    assert result.observed["progress"]["tables_done"] == 40
    assert result.observed["progress"]["chunks_done"] == 40
    assert "gave up after 10 minutes" in stderr.getvalue()


def test_give_up_without_counters_leaves_progress_null() -> None:
    """Queued the whole time: give-up JSON has progress null, not invented counters."""

    clock = FakeClock()
    polls_needed = (pe.STALL_WINDOW_SECONDS // pe.POLL_CADENCE_SECONDS) + 2
    result = _poll(
        {_job_path(): [_job("queued")] * polls_needed},
        clock=clock,
    )

    assert result.verdict == "stall"
    assert result.observed["job_state"] == "queued"
    assert result.observed["progress"] is None


def test_cache_hit_is_terminal_not_retried() -> None:
    """A LiteSpeed cache-hit header is a hard stop, never a transport retry."""

    result = _poll(
        {
            _job_path(): [
                _job(
                    "running",
                    progress={"tables_done": 1, "tables_total": 2, "files_done": 0, "files_total": 0, "chunks_done": 1},
                    # headers ride on the HttpResponse, not the job body
                )._replace(headers={"x-litespeed-cache": "hit"})
            ]
        }
    )

    assert result.verdict == "cache-hit"
    assert "x-litespeed-cache" in result.observed["cache_header"]


def test_every_request_carries_a_unique_cache_buster() -> None:
    """Each Extractor URL gets a fresh ``_cb`` so a page cache cannot replay."""

    busts = iter(["one", "two"])
    fetcher = ScriptedFetcher(
        {
            _job_path(): [
                _job("running", progress={"tables_done": 0, "tables_total": 1, "files_done": 0, "files_total": 0, "chunks_done": 0}),
                _job("ready", download_url="https://example.com/dl"),
            ]
        }
    )
    pe.poll(
        endpoint=ENDPOINT,
        job_id=JOB_ID,
        budget_seconds=None,
        fetch=fetcher,
        clock=FakeClock(),
        cache_buster=lambda: next(busts),
    )

    cbs = [parse_qs(urlparse(url).query)["_cb"][0] for url in fetcher.urls]
    assert cbs == ["one", "two"]
    assert all(t == pe.PER_REQUEST_TIMEOUT_SECONDS for t in fetcher.timeouts)


def test_main_reads_password_from_env_never_argv(capsys: pytest.CaptureFixture[str]) -> None:
    """The secret lives in ``KNTNT_EXTRACTOR_APP_PASSWORD``, never in argv."""

    code = pe.main(
        [ENDPOINT, JOB_ID, "--user", "thomas"],
        environ={},
    )
    captured = capsys.readouterr()

    assert code == 1
    assert PASSWORD not in captured.out
    assert PASSWORD not in captured.err
    assert pe.PASSWORD_ENV in captured.err


def test_main_never_echoes_the_password(capsys: pytest.CaptureFixture[str]) -> None:
    """A ready run's stdout/stderr must not contain the Application Password."""

    fetcher = ScriptedFetcher(
        {_job_path(): [_job("ready", download_url="https://example.com/dl")]}
    )
    code = pe.main(
        [ENDPOINT, JOB_ID, "--user", "thomas"],
        environ={pe.PASSWORD_ENV: PASSWORD},
        fetch=fetcher,
        clock=FakeClock(),
        cache_buster=lambda: "cb1",
    )
    captured = capsys.readouterr()

    assert code == 0
    assert PASSWORD not in captured.out
    assert PASSWORD not in captured.err
    payload = json.loads(captured.out)
    assert payload["verdict"] == "ready"
    assert "observed" in payload and "inferred" in payload


def test_main_rejects_password_flag() -> None:
    """There is no ``--password`` flag — that would put the secret in argv."""

    with pytest.raises(SystemExit):
        pe.main(
            [ENDPOINT, JOB_ID, "--user", "thomas", "--password", PASSWORD],
            environ={pe.PASSWORD_ENV: PASSWORD},
        )


def test_literals_are_the_eight_pinned_values() -> None:
    """The script owns the seven discipline literals — move them, do not invent."""

    assert pe.POLL_CADENCE_SECONDS == 15
    assert pe.PER_REQUEST_TIMEOUT_SECONDS == 120
    assert pe.BACKOFF_FIRST_SECONDS == 30
    assert pe.BACKOFF_SECOND_SECONDS == 60
    assert pe.STALL_WINDOW_SECONDS == 600
    assert pe.PREFLIGHT_BUDGET_SECONDS == 600
    assert pe.BOOTSTRAP_BUDGET_SECONDS == 900
    assert not hasattr(pe, "MAIN_BUDGET_SECONDS")


def test_main_diverts_the_progress_log_to_a_file(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #52: ``--log`` sends the per-poll progress lines to a file, so an
    agent running the poll inline gets the verdict on stdout and nothing else.
    A multi-hour extraction prints one progress line per fifteen seconds; those
    belong in the run's scratchpad, not in an orchestrator's context."""

    log_path = tmp_path / "logs" / "poll.log"
    fetcher = ScriptedFetcher(
        {
            _job_path(): [
                _job("running", progress={"tables_done": 1, "tables_total": 2}),
                _job("ready", download_url="https://example.com/dl"),
            ]
        }
    )

    code = pe.main(
        [ENDPOINT, JOB_ID, "--user", "thomas", "--log", str(log_path)],
        environ={pe.PASSWORD_ENV: PASSWORD},
        fetch=fetcher,
        clock=FakeClock(),
        cache_buster=lambda: "cb1",
    )
    captured = capsys.readouterr()

    assert code == 0
    assert json.loads(captured.out)["verdict"] == "ready"
    assert captured.err == ""
    assert "tables 1/2" in log_path.read_text(encoding="utf-8")
    assert PASSWORD not in log_path.read_text(encoding="utf-8")
