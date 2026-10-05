"""Vanished-file submission — the skills send ``strict: false`` and surface skips.

A file manifest is a snapshot and a live site is not. Resubmitting a
hours-old selection used to die as an opaque 404; Extractor now accepts
``strict: false``, skips vanished files, and names every missing table and
every missing file on a remaining 404. This suite binds the caller: the
role whose steps actually POST, both SKILLs, and the spec all send the member,
surface ``skipped_files``, and unseal against the remaining file list.

``strict: false`` has two halves, and this suite pins both. The **create-time**
half is the one above: a file that vanished between the ``GET /files`` walk and
the ``POST`` is named on the ``201``. The **packaging-time** half (issue #78,
Extractor ADR-0026) is a file that vanishes hours later, while the job is being
packaged; it is named only on a poll, so the ``201``'s list is a lower bound and
the terminal poll's list is the whole of it. The poll helper folds what it
observed into the job record, and the tests below hold it to that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import poll_extraction as pe
import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

EXTRACT_SUBMIT: Path = REPO_ROOT / "skills" / "clone" / "roles" / "extract-submit.md"
EXTRACT_TRANSFER: Path = REPO_ROOT / "skills" / "clone" / "roles" / "extract-transfer.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"
CLONE: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"

SURFACES: tuple[Path, ...] = (
    EXTRACT_SUBMIT,
    SPEC,
    IMPLEMENTATION_NOTES,
    CLONE,
    PULL,
)


@pytest.mark.parametrize("path", SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_submit_surface_sends_strict_false(path: Path) -> None:
    """The main extraction is submitted with strict: false, so a vanished
    file is a reported skip rather than a fatal 404."""

    text = path.read_text(encoding="utf-8")
    assert "`strict: false`" in text or '"strict": false' in text, (
        f"{path.relative_to(REPO_ROOT)} never tells the caller to submit "
        "with strict: false"
    )


def test_extract_submit_posts_the_member_on_the_wire() -> None:
    """The role whose steps actually POST carries the JSON member, not just prose."""

    text = EXTRACT_SUBMIT.read_text(encoding="utf-8")
    assert '"strict": false' in text, (
        "the extract-submit role must put \"strict\": false on the POST body — "
        "a SKILL that only mentions the mode in prose will not change the wire"
    )


def test_extract_submit_surfaces_skipped_files() -> None:
    """Skipped names are operator-visible and recorded in the evidence block."""

    text = EXTRACT_SUBMIT.read_text(encoding="utf-8")
    assert "skipped_files" in text
    assert "`skipped_files`" in text or "skipped_files —" in text


def test_extract_transfer_unseals_the_remaining_file_list() -> None:
    """The container holds what the plugin packaged, so unseal must drop skips.

    The two halves of the phase are separated by the orchestrator's own poll
    (issue #58), so the list the unseal reconciles against no longer sits in the
    unsealing role's own memory: `extract-submit` records the selection as
    submitted, and `extract-transfer` reads it back from that record."""

    text = EXTRACT_TRANSFER.read_text(encoding="utf-8")
    assert "minus" in text and "skipped_files" in text, (
        "extract-transfer.md must unseal against the submitted files minus "
        "skipped_files — passing the original selection fails the container check"
    )
    assert "extract-job.json" in text, (
        "extract-transfer.md must read the submitted selection back from the job "
        "record extract-submit wrote, since it no longer submits the job itself"
    )


@pytest.mark.parametrize("path", (CLONE, PULL), ids=("clone", "pull"))
def test_skills_surface_skipped_files(path: Path) -> None:
    """Both SKILLs tell the operator that skipped_files are gone, not an error."""

    text = path.read_text(encoding="utf-8")
    assert "skipped_files" in text
    assert "vanished" in text.lower() or "gone from production" in text


# --- The packaging-time half: the poll folds its skips into the job record ----

ENDPOINT = "https://example.com/wp-json/kntnt-extractor/v1"
JOB_ID = "job-78"
PASSWORD = "super-secret-app-password-never-print-me"


class _StubClock:
    """A clock that advances only when the loop sleeps."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _write_record(tmp_path: Path, **overrides: Any) -> Path:
    """A job record shaped as ``extract-submit`` writes it, before any poll."""

    record: dict[str, Any] = {
        "job_id": JOB_ID,
        "submitted": {
            "tables": ["wp_posts"],
            "tables_structure_only": [],
            "files": ["wp-content/uploads/a.jpg", "wp-content/uploads/b.jpg"],
        },
        "skipped_files": [],
        "restricted_paths": [],
    }
    record.update(overrides)
    path = tmp_path / "extract-job.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _ready_response(skipped: list[str] | None) -> pe.HttpResponse:
    payload: dict[str, Any] = {
        "id": JOB_ID,
        "state": "ready",
        "download_url": "https://example.com/one-time",
    }
    if skipped is not None:
        payload["skipped_files"] = skipped
    return pe.HttpResponse(status=200, headers={}, body=json.dumps(payload).encode())


def _run_main(argv: list[str], *, response: pe.HttpResponse | BaseException) -> int:
    """Drive the CLI once against a single scripted response."""

    def fetch(url: str, *, timeout: float) -> pe.HttpResponse:
        if isinstance(response, BaseException):
            raise response
        return response

    return pe.main(
        argv,
        environ={pe.PASSWORD_ENV: PASSWORD},
        fetch=fetch,
        clock=_StubClock(),
        cache_buster=lambda: "cb1",
    )


def _poll_argv(record: Path | None = None) -> list[str]:
    argv = [ENDPOINT, JOB_ID, "--user", "operator"]
    if record is not None:
        argv += ["--job-record", str(record)]
    return argv


def _read(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_a_terminal_ready_leaves_the_record_holding_the_union(tmp_path: Path) -> None:
    """AC: a record whose skip list is a subset of the poll's ends up holding the
    union, with the create-time and packaging-time sets separately recoverable."""

    # Arrange: the 201 named one file; the job then lost a second while packaging.
    record = _write_record(tmp_path, skipped_files=["wp-content/uploads/a.jpg"])

    # Act.
    exit_code = _run_main(
        _poll_argv(record),
        response=_ready_response(
            ["wp-content/uploads/a.jpg", "wp-content/uploads/b.jpg"]
        ),
    )

    # Assert: both sets are on the record, and neither has absorbed the other.
    assert exit_code == pe.EXIT_READY
    merged = _read(record)
    assert merged["skipped_files"] == ["wp-content/uploads/a.jpg"]
    assert merged["packaging_skipped_files"] == ["wp-content/uploads/b.jpg"]


def test_a_poll_with_no_skips_leaves_the_record_semantically_unchanged(
    tmp_path: Path,
) -> None:
    """AC: no ``skipped_files`` on the payload means an empty packaging-time set
    — which is what makes the merge a no-op against an older Extractor."""

    record = _write_record(tmp_path, skipped_files=["wp-content/uploads/a.jpg"])

    assert _run_main(_poll_argv(record), response=_ready_response(None)) == pe.EXIT_READY

    merged = _read(record)
    assert merged["skipped_files"] == ["wp-content/uploads/a.jpg"]
    assert merged["packaging_skipped_files"] == []
    assert merged["submitted"]["files"] == [
        "wp-content/uploads/a.jpg",
        "wp-content/uploads/b.jpg",
    ]
    assert merged["restricted_paths"] == []


def test_a_recorded_path_absent_from_the_polls_list_survives(tmp_path: Path) -> None:
    """AC: the merge is a union that never shrinks. The plugin appends rather
    than rewrites, but the client must not depend on that."""

    record = _write_record(tmp_path, skipped_files=["wp-content/uploads/a.jpg"])

    assert (
        _run_main(
            _poll_argv(record),
            response=_ready_response(["wp-content/uploads/b.jpg"]),
        )
        == pe.EXIT_READY
    )

    merged = _read(record)
    assert merged["skipped_files"] == ["wp-content/uploads/a.jpg"]
    assert merged["packaging_skipped_files"] == ["wp-content/uploads/b.jpg"]


def test_merging_twice_produces_what_merging_once_produced(tmp_path: Path) -> None:
    """AC: a lost poller is a re-poll against the same job, so the merge has to
    be idempotent — no duplicated entries on the second pass."""

    record = _write_record(tmp_path, skipped_files=["wp-content/uploads/a.jpg"])
    observed = ["wp-content/uploads/a.jpg", "wp-content/uploads/b.jpg"]

    _run_main(_poll_argv(record), response=_ready_response(observed))
    once = _read(record)
    _run_main(_poll_argv(record), response=_ready_response(observed))
    twice = _read(record)

    assert twice == once


def test_a_terminal_failed_records_the_skips_too(tmp_path: Path) -> None:
    """A ``failed`` job is terminal and its skip list is real, so recording it
    makes the operator's report honest about what production dropped."""

    record = _write_record(tmp_path)
    payload = {
        "id": JOB_ID,
        "state": "failed",
        "download_url": None,
        "error": {"code": "boom"},
        "skipped_files": ["wp-content/uploads/b.jpg"],
    }
    response = pe.HttpResponse(status=200, headers={}, body=json.dumps(payload).encode())

    assert _run_main(_poll_argv(record), response=response) == pe.EXIT_FAILED
    assert _read(record)["packaging_skipped_files"] == ["wp-content/uploads/b.jpg"]


def test_a_non_terminal_exit_writes_nothing_to_the_record(tmp_path: Path) -> None:
    """AC: a transport failure or an exhausted budget never touches the record —
    only a terminal verdict has observed anything worth recording."""

    record = _write_record(tmp_path, skipped_files=["wp-content/uploads/a.jpg"])
    before = record.read_text(encoding="utf-8")

    exit_code = _run_main(
        [ENDPOINT, JOB_ID, "60", "--user", "operator", "--job-record", str(record)],
        response=ConnectionError("production is unreachable"),
    )

    assert exit_code == pe.EXIT_BUDGET
    assert record.read_text(encoding="utf-8") == before


def test_no_job_record_argument_leaves_the_helper_unchanged(tmp_path: Path) -> None:
    """AC: the preflight runs the same helper against a throwaway job with no
    record at all, so the argument stays optional and absent-by-default."""

    stray = tmp_path / "extract-job.json"

    assert (
        _run_main(_poll_argv(), response=_ready_response(["wp-content/uploads/b.jpg"]))
        == pe.EXIT_READY
    )
    assert not stray.exists()


def test_the_merge_keeps_a_packaging_path_out_of_the_create_time_set() -> None:
    """The two sets mean different things — a file deleted while the client was
    looking at it, and production mutating hours into the extraction — so a path
    the ``201`` never named never lands in the create-time list."""

    merged = pe.merge_skipped_files(
        {"skipped_files": ["a"], "packaging_skipped_files": ["b"]}, ["a", "b", "c"]
    )

    assert merged["skipped_files"] == ["a"]
    assert merged["packaging_skipped_files"] == ["b", "c"]


def test_the_merge_ignores_a_malformed_observed_list() -> None:
    """The observed list comes off the wire, so a non-string member is dropped
    rather than written into a record the unseal reconciles against."""

    merged = pe.merge_skipped_files({"skipped_files": []}, ["a", 7, None, "a"])

    assert merged["packaging_skipped_files"] == ["a"]


# --- The surfaces that carry the packaging-time half -------------------------


def test_extract_transfer_subtracts_both_skip_lists() -> None:
    """The container holds the submitted selection minus every skip, whenever it
    was decided; subtracting only the create-time list is the #78 abort."""

    text = EXTRACT_TRANSFER.read_text(encoding="utf-8")
    assert "packaging_skipped_files" in text, (
        "extract-transfer.md must name the packaging-time skip list — the "
        "unseal aborts after the whole download when it subtracts only the "
        "create-time one"
    )


@pytest.mark.parametrize("path", (CLONE, PULL), ids=("clone", "pull"))
def test_the_poll_command_hands_the_helper_the_job_record(path: Path) -> None:
    """The merge is the helper's, so the orchestrator's poll command has to give
    it the record. A command without the argument leaves the record frozen."""

    text = path.read_text(encoding="utf-8")
    assert "--job-record" in text, (
        f"{path.name}'s poll command never passes --job-record, so the poll's "
        "skip list never reaches the record the unseal reconciles against"
    )


@pytest.mark.parametrize("path", (CLONE, PULL), ids=("clone", "pull"))
def test_the_run_report_names_both_skip_sets_separately(path: Path) -> None:
    """AC: the report names the two sets separately, and the create-time
    parenthetical no longer claims to describe every absent file."""

    text = path.read_text(encoding="utf-8")
    report = text[text.index("## 11. Cleanup and report") :]
    assert "packaging_skipped_files" in report, (
        f"{path.name}'s run report never names the packaging-time skips, so a "
        "file production dropped mid-run is absent from the copy and from the "
        "report alike"
    )


@pytest.mark.parametrize("path", (CLONE, PULL), ids=("clone", "pull"))
def test_the_report_gains_the_packaging_skips_degraded_bullet(path: Path) -> None:
    """AC: a host whose ``honours`` list does not name ``packaging_skips``
    cannot produce a mid-run skip, and the merge is a no-op there — stated in
    the same place the other degraded behaviours are stated."""

    text = path.read_text(encoding="utf-8")
    bullet = next(
        (
            line
            for line in text.splitlines()
            if line.startswith("- **`honours`") and "packaging_skips" in line
        ),
        None,
    )
    assert bullet is not None, (
        f"{path.name}'s degraded-behaviours list has no bullet firing on "
        "honours not naming packaging_skips"
    )


def test_the_implementation_notes_unseal_contract_names_both_lists() -> None:
    """The notes already promised the unseal is given "the submitted selection
    minus any ``skipped_files`` the ``201`` or a later poll reported". That was
    aspirational; it has to name the member that makes it true."""

    text = IMPLEMENTATION_NOTES.read_text(encoding="utf-8")
    assert "packaging_skipped_files" in text


def test_the_glossary_defines_both_skip_terms() -> None:
    """Both terms enter the project glossary, since the rest of the code and
    docs are then written in them."""

    text = (REPO_ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
    assert "**Create-time skip**" in text
    assert "**Packaging-time skip**" in text
