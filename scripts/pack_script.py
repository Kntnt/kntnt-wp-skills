# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Generate the production-side pack script from resolved inputs.

Deterministic helper on the transfer engine's single automated seam: resolved
inputs (table classification, exclusion paths, archive/transfer set, working and
download dirs) go in as JSON, the ``pack.sh`` the background job runs comes out.
The model never assembles this shell by hand — it is generated here and unit
tested, then executed in a sandbox with stub binaries to prove its runtime
contract.

Every literal the generated script carries is settled in ``docs/spec.md`` (Pack
on production) and ``docs/implementation-notes.md`` (Pack): the anchored exclude
file with wildcards disabled, the two-pass live-safe dump with a MyISAM
fallback, encryption to ``.enc`` names from creation, checksums over the final
names, strict error handling with a FAILED marker plus log tail, the DONE
marker, and the armed self-destruct. The database password never enters this
script — it lives only in the ``.my.cnf`` the orchestration writes server-side —
and the passphrase is passed to OpenSSL by file reference, never on a command
line.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["PackInputs", "generate_pack_script", "main"]

# OpenSSL invocation shared by both artifacts: AES-256-CBC with PBKDF2 and a
# salt, the passphrase supplied by file reference so it never hits a command
# line, writing straight to the final .enc name.
_OPENSSL_ENC = 'openssl enc -aes-256-cbc -pbkdf2 -salt -pass file:"$PASS_FILE"'

# Live-site-safe dump flags. --single-transaction is dropped in the MyISAM
# fallback; the other two stay because they never lock a live site.
_INNODB_FLAGS = "--single-transaction --quick --skip-lock-tables"
_MYISAM_FLAGS = "--quick --skip-lock-tables"

# Default values for the optional resolved inputs. The self-destruct delay and
# log-tail length are free choices per the implementation notes.
_DEFAULT_SELF_DESTRUCT_DELAY = 3600
_DEFAULT_LOG_TAIL_LINES = 40

_REQUIRED_KEYS = ("workingDir", "downloadDir", "database", "sourceRoot")


@dataclass(frozen=True)
class PackInputs:
    """The resolved inputs a pack script is generated from.

    All paths are absolute. ``archive_paths`` and ``exclude_paths`` are relative
    to ``source_root`` (so ``exclude_paths`` are the anchored member names tar
    matches). ``content_tables`` are dumped with data, ``empty_tables`` schema
    only; the classifier guarantees the two are disjoint and cover every table.
    """

    working_dir: str
    download_dir: str
    database: str
    source_root: str
    archive_paths: tuple[str, ...]
    exclude_paths: tuple[str, ...]
    content_tables: tuple[str, ...]
    empty_tables: tuple[str, ...]
    consistent_snapshot: bool
    self_destruct_delay_seconds: int
    log_tail_lines: int

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> PackInputs:
        """Build inputs from a resolved-inputs mapping, applying defaults for the
        optional keys and rejecting a mapping missing a required one."""

        # Fail loudly on a missing required key rather than generating a
        # silently broken script.
        missing = [key for key in _REQUIRED_KEYS if key not in config]
        if missing:
            raise ValueError(
                f"pack inputs missing required key(s): {', '.join(missing)}"
            )

        return cls(
            working_dir=str(config["workingDir"]),
            download_dir=str(config["downloadDir"]),
            database=str(config["database"]),
            source_root=str(config["sourceRoot"]),
            archive_paths=_as_str_tuple(config.get("archivePaths", ())),
            exclude_paths=_as_str_tuple(config.get("excludePaths", ())),
            content_tables=_as_str_tuple(config.get("contentTables", ())),
            empty_tables=_as_str_tuple(config.get("emptyTables", ())),
            consistent_snapshot=bool(config.get("consistentSnapshot", True)),
            self_destruct_delay_seconds=int(
                config.get("selfDestructDelaySeconds", _DEFAULT_SELF_DESTRUCT_DELAY)
            ),
            log_tail_lines=int(config.get("logTailLines", _DEFAULT_LOG_TAIL_LINES)),
        )


def _as_str_tuple(values: Any) -> tuple[str, ...]:
    """Coerce a JSON array into a tuple of strings, preserving order."""

    return tuple(str(value) for value in values)


def _join_operands(items: Sequence[str]) -> str:
    """Shell-quote each item and join with spaces for use as command operands."""

    return " ".join(shlex.quote(item) for item in items)


def _dump_block(inputs: PackInputs) -> str:
    """Render the two-pass dump: full data for the content tables, schema only
    for the empty-classified ones, streamed through gzip and encryption to
    db.enc with no plaintext dump ever touching disk."""

    # Pick the consistency flags; a non-InnoDB content table drops
    # --single-transaction and logs a caveat instead of tearing the dump.
    caveat = ""
    flags = _INNODB_FLAGS
    if not inputs.consistent_snapshot:
        flags = _MYISAM_FLAGS
        caveat = (
            'echo "WARNING: a content table is not InnoDB; dumping without a '
            'consistent-snapshot transaction (consistency caveat)."\n'
        )

    # Build one mysqldump pass per non-empty table list; the classifier keeps
    # the lists disjoint, so concatenating the passes yields every table once.
    passes = []
    if inputs.content_tables:
        passes.append(
            f'    mysqldump --defaults-extra-file="$MYCNF" {flags} '
            f'"$DB" {_join_operands(inputs.content_tables)}'
        )
    if inputs.empty_tables:
        passes.append(
            f'    mysqldump --defaults-extra-file="$MYCNF" {flags} --no-data '
            f'"$DB" {_join_operands(inputs.empty_tables)}'
        )
    body = "\n".join(passes)

    return (
        "# Dump the database in two consistent passes — full data for the\n"
        "# content tables, schema only for the empty-classified ones — then\n"
        "# compress and encrypt straight to db.enc; no plaintext dump on disk.\n"
        f"{caveat}"
        "{\n"
        f"{body}\n"
        f'}} | gzip | {_OPENSSL_ENC} -out "$WORKDIR/db.enc"'
    )


def _archive_block(inputs: PackInputs) -> str:
    """Render the file archive: an anchored exclude file with wildcards disabled
    when an exclusion list applies, streamed straight through encryption to
    files.enc. An explicit include list (the pull delta path) already carries no
    exclusion list — it was scope-filtered locally against the exclude paths
    before the archive set was even built — so there is nothing left to exclude
    and the tar invocation drops the exclude-file flags entirely."""

    # An empty transfer set still yields a valid (empty) archive rather than a
    # tar invocation with no operands.
    operands = _join_operands(inputs.archive_paths) or "--files-from=/dev/null"
    exclude_flags = (
        '--exclude-from="$EXCLUDE_FILE" --anchored --no-wildcards '
        if inputs.exclude_paths
        else ""
    )

    return (
        "# Archive the in-scope tree with an anchored exclude file (wildcards\n"
        "# disabled) and stream it straight through encryption to files.enc.\n"
        f"tar {exclude_flags}"
        '--warning=no-file-changed -C "$SOURCE_ROOT" -czf - '
        f"{operands} \\\n"
        f'    | {_OPENSSL_ENC} -out "$WORKDIR/files.enc"'
    )


def generate_pack_script(config: Mapping[str, Any]) -> str:
    """Render the pack script text from a resolved-inputs mapping.

    The output is deterministic: identical inputs yield a byte-identical script,
    with no timestamps or randomness of its own (the random working and download
    dir names arrive as inputs).
    """

    inputs = PackInputs.from_mapping(config)

    # Bake the resolved locations and tunables as shell variables; every
    # interpolated value is shell-quoted so odd characters cannot break out.
    # EXCLUDE_FILE is only declared when an exclusion list applies — an explicit
    # include list has nothing for it to name.
    exclude_file_var = 'EXCLUDE_FILE="$WORKDIR/exclude.txt"\n' if inputs.exclude_paths else ""
    header = (
        "#!/usr/bin/env bash\n"
        "#\n"
        "# Generated by kntnt-wp-skills (pack_script.py) — do not edit by hand.\n"
        "# Production-side pack: dump, archive, encrypt, publish, self-destruct.\n"
        "# All packing happens in the outside-docroot working dir; only the\n"
        "# three encrypted artifacts are published into the docroot download dir.\n"
        "set -euo pipefail\n"
        "\n"
        "# Resolved locations and tunables, baked at generation time.\n"
        f"WORKDIR={shlex.quote(inputs.working_dir)}\n"
        f"DLDIR={shlex.quote(inputs.download_dir)}\n"
        f"SOURCE_ROOT={shlex.quote(inputs.source_root)}\n"
        f"DB={shlex.quote(inputs.database)}\n"
        'PASS_FILE="$WORKDIR/pass.key"\n'
        'MYCNF="$WORKDIR/.my.cnf"\n'
        'LOG="$WORKDIR/pack.log"\n'
        f"{exclude_file_var}"
        f"TAIL_LINES={inputs.log_tail_lines}\n"
        f"SELF_DESTRUCT_DELAY={inputs.self_destruct_delay_seconds}\n"
    )

    # On any error, publish a FAILED marker with the log tail into the download
    # dir — the only channel the client has to learn why a pack died.
    trap = (
        "# Publish a FAILED marker with the log tail into the download dir, then\n"
        "# abort — the only channel the client has to learn why a pack died.\n"
        "fail() {\n"
        "    trap - ERR\n"
        '    mkdir -p "$DLDIR"\n'
        '    { echo "FAILED"; tail -n "$TAIL_LINES" "$LOG" 2>/dev/null || true; } '
        '> "$DLDIR/FAILED"\n'
        "    exit 1\n"
        "}\n"
        "trap fail ERR\n"
    )

    # Create the download dir before any heavy work so an early failure can
    # report, then arm the self-destruct before touching the database.
    setup = (
        "# Ensure the download dir exists so even an early failure can report.\n"
        'mkdir -p "$DLDIR"\n'
        "\n"
        "# Arm the self-destruct: both dirs — passphrase, credentials, and\n"
        "# artifacts — vanish after the delay even if the client never returns.\n"
        '( sleep "$SELF_DESTRUCT_DELAY"; rm -rf "$WORKDIR" "$DLDIR" ) &\n'
    )

    # The exclusion list is a heredoc of full anchored relative paths; the quoted
    # delimiter keeps the shell from expanding anything inside. An explicit
    # include list (the pull delta path) arrives already scope-filtered against
    # the exclude paths, so there is nothing left to exclude — the heredoc is
    # skipped entirely rather than writing and matching against an empty file.
    exclude = ""
    if inputs.exclude_paths:
        exclude_body = "\n".join(inputs.exclude_paths)
        exclude = (
            "# Write the archive exclusion list: full anchored relative paths.\n"
            "cat > \"$EXCLUDE_FILE\" <<'KNTNT_EXCLUDE_EOF'\n"
            f"{exclude_body}\n"
            "KNTNT_EXCLUDE_EOF\n"
        )

    # Checksum the final names in the working dir, then publish all three
    # artifacts world-readable and signal a clean finish.
    publish = (
        "# Checksum the final artifact names, then publish all three\n"
        "# world-readable into the download dir.\n"
        'cd "$WORKDIR"\n'
        "sha256sum db.enc files.enc > SHA256\n"
        "chmod 0644 db.enc files.enc SHA256\n"
        'mv db.enc files.enc SHA256 "$DLDIR/"\n'
        "\n"
        "# Signal a clean finish.\n"
        'touch "$DLDIR/DONE"\n'
    )

    # Drop the exclude section outright when empty rather than joining in a
    # blank placeholder — the explicit-include path leaves no trace of it.
    sections = [
        header,
        trap,
        setup,
        *([exclude] if exclude else []),
        _dump_block(inputs) + "\n",
        _archive_block(inputs) + "\n",
        publish,
    ]
    return "\n".join(sections)


def main() -> None:
    """CLI entry point: read a resolved-inputs JSON object from stdin, write the
    generated pack script to stdout."""

    config = json.load(sys.stdin)
    sys.stdout.write(generate_pack_script(config))


if __name__ == "__main__":
    main()
