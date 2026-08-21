# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the exclusion-set assembler CLI.

The assembler (``scripts/build_exclusions.py``) is the deterministic seam issue
#35 introduces: the one place the resolved exclusion set is built, so the
extraction selection (clone §5) and the baseline manifest (clone §9.12, pull's
diff) can never assemble it even slightly differently and poison the deletion
diff. It reads the classifications (``classify.py``'s ``thumbnails.exclude``,
``blobs.flagged``, and ``uploads_prefix``) and the resolved plan
(``resolve_plan.py``'s decisions) as one JSON object on stdin, and writes the
complete, anchored, deduped exclusion prefix list on stdout as
``{"exclusions": [...]}`` — exactly the shape ``filter_manifest.py`` consumes.

The canonical always-excluded set lives once, as the module constant
:data:`build_exclusions.ALWAYS_EXCLUDED`; these tests pin its contents so no
prose reference can drift from it, and pin the assembler's output for a
representative classification-plus-plan input so the two consumers provably
agree.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import build_exclusions
import filter_manifest

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "clone" / "scripts" / "build_exclusions.py"


def run_build(payload: Any) -> subprocess.CompletedProcess[bytes]:
    """Run the assembler with ``payload`` as JSON on stdin and capture its result."""

    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )


def build(payload: Any) -> list[str]:
    """Run the assembler and return the parsed exclusion list, asserting success."""

    result = run_build(payload)
    assert result.returncode == 0, result.stderr.decode()
    document: dict[str, Any] = json.loads(result.stdout)
    return document["exclusions"]


def make_payload(
    *,
    thumbnails: list[str] | None = None,
    flagged: list[dict[str, Any]] | None = None,
    uploads_prefix: str = "wp-content/uploads",
    decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble a representative ``{classifications, plan}`` envelope, defaulting
    every decision to its recommended value (thumbnails and blobs excluded, media
    included) so a test only states the knob it varies."""

    resolved = {
        "generated_thumbnails": "exclude",
        "heavy_blobs": "exclude",
        "media_originals": "include",
        **(decisions or {}),
    }
    return {
        "classifications": {
            "thumbnails": {
                "exclude": thumbnails
                if thumbnails is not None
                else ["wp-content/uploads/2024/05/banner-300x200.jpg"]
            },
            "blobs": {
                "flagged": flagged
                if flagged is not None
                else [{"path": "wp-content/uploads/galleries", "size_bytes": 1}]
            },
            "uploads_prefix": uploads_prefix,
        },
        "plan": {
            "decisions": [
                {"id": key, "value": value} for key, value in resolved.items()
            ]
        },
    }


# --- The canonical constant ----------------------------------------------------


def test_always_excluded_covers_the_documented_categories() -> None:
    # Arrange / Act — the single source of truth for the always-excluded paths.
    always = set(build_exclusions.ALWAYS_EXCLUDED)

    # Assert — the configuration file, the drop-ins under wp-content/, the debug
    # log, the cache dir, and the upgrade dirs the §5 prose enumerates, each
    # anchored at the WordPress root.
    assert "**/wp-config.php" in always
    assert "wp-content/object-cache.php" in always
    assert "wp-content/advanced-cache.php" in always
    assert "wp-content/db.php" in always
    assert "wp-content/maintenance.php" in always
    assert "wp-content/debug.log" in always
    assert "wp-content/cache" in always
    assert "wp-content/litespeed" in always
    assert "wp-content/et-cache" in always
    assert "wp-content/w3tc-*" in always
    assert "wp-content/uploads/backwpup*" in always
    assert "wp-content/uploads/kntnt-extractor" in always
    assert "wp-content/uploads/kntnt-extractor-audit" in always
    assert "wp-content/uploads/kntnt-extractor-downloads" in always
    assert "wp-content/upgrade" in always
    assert "wp-content/upgrade-temp-backup" in always

    # Assert — the credential-bearing pattern family issue #36 adds: the
    # wp-config backup/swap/variant globs, .env anywhere in the tree, root-level
    # SQL dumps, and root-level key material. The unambiguous configuration-file
    # shapes carry the "**/" marker (issue #75) — a basename that can only ever
    # name a config copy is one at any depth — while the broad variant-catcher
    # stays root-anchored, since its basename can belong to something else.
    assert "**/wp-config.php.*" in always
    assert "**/wp-config.php~" in always
    assert "**/.wp-config.php" in always
    assert "**/.wp-config.php.*" in always
    assert "wp-config-*.php" in always
    assert "**/.env" in always
    assert "**/.env.*" in always
    assert "*.sql" in always
    assert "*.sql.gz" in always
    assert "*.sql.zip" in always
    assert "*.pem" in always
    assert "*.key" in always
    assert "id_rsa*" in always

    # Assert — the shapes issue #55 adds to the same family: the editor droppings
    # beside wp-config.php that are not vim's, the backup names that put the
    # marker ahead of the extension, and the rest of OpenSSH's default basenames.
    assert "**/#wp-config.php#" in always
    assert "**/.#wp-config.php" in always
    assert "**/wp-config.old" in always
    assert "**/wp-config.old.php" in always
    assert "id_ed25519*" in always

    # Assert — the WordPress core tree issue #37 adds: the admin and includes
    # directories, and the root-level core PHP files.
    assert "wp-admin" in always
    assert "wp-includes" in always
    assert "index.php" in always
    assert "wp-login.php" in always
    assert "wp-settings.php" in always
    assert "xmlrpc.php" in always
    assert "wp-config-sample.php" not in always


def test_always_excluded_pins_its_exact_contents() -> None:
    # Assert — the exact always-excluded set, so a stray, typo'd, or dropped entry
    # reddens here rather than silently changing what every run excludes.
    assert set(build_exclusions.ALWAYS_EXCLUDED) == {
        "**/wp-config.php",
        "**/wp-config.php.*",
        "**/wp-config.php~",
        "**/.wp-config.php",
        "**/.wp-config.php.*",
        "**/#wp-config.php#",
        "**/.#wp-config.php",
        "**/wp-config.bak",
        "**/wp-config.bak.php",
        "**/wp-config.old",
        "**/wp-config.old.php",
        "**/wp-config.orig",
        "**/wp-config.orig.php",
        "**/wp-config.save",
        "**/wp-config.save.php",
        "wp-config-*.php",
        "**/.env",
        "**/.env.*",
        "*.sql",
        "*.sql.gz",
        "*.sql.zip",
        "*.pem",
        "*.key",
        "id_rsa*",
        "id_dsa*",
        "id_ecdsa*",
        "id_ed25519*",
        "wp-content/advanced-cache.php",
        "wp-content/object-cache.php",
        "wp-content/db.php",
        "wp-content/db-error.php",
        "wp-content/install.php",
        "wp-content/maintenance.php",
        "wp-content/php-error.php",
        "wp-content/fatal-error-handler.php",
        "wp-content/sunrise.php",
        "wp-content/blog-deleted.php",
        "wp-content/blog-inactive.php",
        "wp-content/blog-suspended.php",
        "wp-content/debug.log",
        "wp-content/cache",
        "wp-content/litespeed",
        "wp-content/et-cache",
        "wp-content/w3tc-*",
        "wp-content/uploads/backwpup*",
        "wp-content/uploads/kntnt-extractor",
        "wp-content/uploads/kntnt-extractor-audit",
        "wp-content/uploads/kntnt-extractor-downloads",
        "wp-content/upgrade",
        "wp-content/upgrade-temp-backup",
        "wp-admin",
        "wp-includes",
        "index.php",
        "license.txt",
        "readme.html",
        "wp-activate.php",
        "wp-blog-header.php",
        "wp-comments-post.php",
        "wp-cron.php",
        "wp-links-opml.php",
        "wp-load.php",
        "wp-login.php",
        "wp-mail.php",
        "wp-settings.php",
        "wp-signup.php",
        "wp-trackback.php",
        "xmlrpc.php",
    }
    # No duplicate entries hide behind the set comparison above.
    assert len(build_exclusions.ALWAYS_EXCLUDED) == len(set(build_exclusions.ALWAYS_EXCLUDED))


def test_always_excluded_is_anchored_and_normalised() -> None:
    # Assert — every always-excluded entry is a relative, root-anchored prefix
    # with no leading or trailing slash, the one spelling every consumer matches.
    for prefix in build_exclusions.ALWAYS_EXCLUDED:
        assert not prefix.startswith("/"), prefix
        assert not prefix.endswith("/"), prefix


# --- The credential-bearing shapes, matched ------------------------------------


def excluded(path: str) -> bool:
    """Report whether the always-excluded set drops ``path``, asked of the real
    matcher rather than of the constant.

    The entries are fnmatch-style globs, so a pattern's presence in the constant
    proves nothing about the filenames it actually catches — only the matcher can
    say. ``filter_manifest.is_excluded`` is that matcher, and
    ``tests/test_exclusion_matching_consistency.py`` pins ``baseline_diff.py``'s
    copy to it, so one verdict reached here is both consumers' verdict.
    """

    return filter_manifest.is_excluded(path, tuple(build_exclusions.ALWAYS_EXCLUDED))


def test_the_emacs_auto_save_and_lock_files_beside_wp_config_are_excluded() -> None:
    # Assert — Emacs' auto-save file holds the live file's complete secret family
    # in clear text, and its lock file names the account editing it; the vim swap
    # catcher matches neither shape.
    assert excluded("#wp-config.php#")
    assert excluded(".#wp-config.php")


def test_the_dot_prefixed_wp_config_with_any_suffix_is_excluded() -> None:
    # Assert — the dot-prefixed configuration file itself and every suffix an
    # editor or a manual copy leaves after it, not only vim's swap family: each
    # carries the live file's complete secret family, and the Extractor refuses
    # the whole create when a selection names one (issue #67).
    for name in (
        ".wp-config.php",
        ".wp-config.php.swp",
        ".wp-config.php.swo",
        ".wp-config.php.bak",
        ".wp-config.php.save",
        ".wp-config.php.1",
        ".wp-config.php.orig",
    ):
        assert excluded(name), name


def test_the_reordered_wp_config_backup_names_are_excluded() -> None:
    # Assert — the names an operator leaves behind after a manual edit, with the
    # backup marker ahead of the extension instead of appended to it, which is
    # exactly what the "wp-config.php.*" catcher cannot see.
    for name in (
        "wp-config.bak",
        "wp-config.bak.php",
        "wp-config.old",
        "wp-config.old.php",
        "wp-config.orig",
        "wp-config.orig.php",
        "wp-config.save",
        "wp-config.save.php",
    ):
        assert excluded(name), name


def test_every_openssh_default_key_basename_at_the_root_is_excluded() -> None:
    # Assert — OpenSSH's whole default basename set, the "-sk" hardware-token
    # variants included, and the ".pub" sibling the same prefix deliberately
    # catches: a public key at the install root is not content either.
    for stem in (
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ecdsa-sk",
        "id_ed25519",
        "id_ed25519-sk",
    ):
        assert excluded(stem), stem
        assert excluded(f"{stem}.pub"), stem


def test_wp_config_sample_survives_the_widened_variant_family() -> None:
    # Assert — WordPress' own bundled template carries placeholder values only,
    # and no pattern in the widened family may swallow it; a copy missing it is a
    # copy missing a core file, and nothing reports that.
    assert not excluded("wp-config-sample.php")


def test_ordinary_content_named_like_a_backup_is_not_excluded() -> None:
    # Assert — the widened patterns stay wp-config-specific: a theme's own
    # "config.old" is not the configuration file, and an uploaded screenshot
    # named after a key type is not key material — the root-anchored key family
    # never reaches it.
    assert not excluded("wp-content/themes/x/config.old")
    assert not excluded("wp-content/uploads/id_ed25519-tutorial.png")


# --- The configuration family's anchoring (issue #75) --------------------------


# Every basename in the family that can *only* ever name a copy of the
# configuration file — the plain name, the appended and tilde backups, the
# editor droppings, and the reordered backup names. Each carries the live file's
# complete secret family in clear text wherever it sits.
_UNAMBIGUOUS_CONFIGURATION_SHAPES = (
    "wp-config.php",
    "wp-config.php.bak-20260717-212309",
    "wp-config.php~",
    ".wp-config.php",
    ".wp-config.php.swp",
    ".wp-config.php.bak",
    "#wp-config.php#",
    ".#wp-config.php",
    "wp-config.bak",
    "wp-config.bak.php",
    "wp-config.old",
    "wp-config.old.php",
    "wp-config.orig",
    "wp-config.orig.php",
    "wp-config.save",
    "wp-config.save.php",
)


def test_an_unambiguous_configuration_copy_is_excluded_at_any_depth() -> None:
    # Assert — a backup plugin's staging copy, a duplicated install, a
    # developer's snapshot: a file named like the configuration file is a
    # configuration copy wherever it sits, never content, and this client never
    # asks for one. The Extractor matches the whole family against basename() at
    # any depth and refuses the whole create when a selection names one, so a
    # nested copy that survived this pre-filter cost a live run a round trip.
    for name in _UNAMBIGUOUS_CONFIGURATION_SHAPES:
        for path in (
            name,
            f"wp-content/{name}",
            f"wp-content/uploads/backups/2026/{name}",
        ):
            assert excluded(path), path


def test_wp_config_sample_is_sent_at_the_root_and_nested() -> None:
    # Assert — WordPress' own bundled template, at the install root and wherever
    # a theme or plugin ships a copy of it. The Extractor excepts it by basename
    # too, so dropping a nested one would make this client stricter than the
    # server on the very file the server explicitly protects.
    assert not excluded("wp-config-sample.php")
    assert not excluded("wp-content/themes/acme/wp-config-sample.php")
    assert not excluded("wp-content/plugins/acme/vendor/wp/wp-config-sample.php")


def test_a_nested_name_that_merely_resembles_a_variant_is_still_sent() -> None:
    # Assert — the broad "wp-config-*.php" catcher stays root-anchored: its
    # basename can legitimately belong to something that is not a config copy at
    # all, so a nested one is content and the divergence from the server is
    # accepted here rather than paid for by dropping a legitimate file.
    assert excluded("wp-config-backup.php")
    assert not excluded("wp-content/plugins/acme/wp-config-local.php")


def test_ordinary_content_survives_the_anywhere_matching() -> None:
    # Assert — the anywhere-matched half is basename-exact against the family's
    # own shapes, so ordinary nested content is untouched.
    assert not excluded("wp-content/themes/acme/config.php")
    assert not excluded("wp-content/uploads/2024/05/banner.jpg")
    assert not excluded("wp-content/plugins/acme/wp-config-loader.php")


# --- The assembled set ---------------------------------------------------------


def test_the_default_plan_excludes_thumbnails_and_blobs_but_not_media() -> None:
    # Act — the recommended defaults: thumbnails and heavy blobs excluded, media
    # originals included.
    exclusions = set(build(make_payload()))

    # Assert — the always-excluded constant, plus the DB-known thumbnails and the
    # flagged heavy blobs; the uploads tree itself is not excluded.
    assert set(build_exclusions.ALWAYS_EXCLUDED) <= exclusions
    assert "wp-content/uploads/2024/05/banner-300x200.jpg" in exclusions
    assert "wp-content/uploads/galleries" in exclusions
    assert "wp-content/uploads" not in exclusions


def test_excluding_media_adds_the_uploads_prefix() -> None:
    # Act — --exclude-media pins media_originals to exclude.
    exclusions = set(build(make_payload(decisions={"media_originals": "exclude"})))

    # Assert — the whole uploads tree is anchored into the set.
    assert "wp-content/uploads" in exclusions


def test_a_moved_uploads_directory_still_excludes_the_uploads_level_detritus() -> None:
    # Arrange — a site with a non-default content directory, the layout classify.py
    # honours rather than flags. The Extractor's staging and the backup tool's
    # scratch live under *that* uploads directory, not the standard one.
    exclusions = set(build(make_payload(uploads_prefix="content/files")))

    # Assert — the uploads-level names are re-anchored on the resolved location, so
    # a selection built here can never name the plugin's own staging (which the run
    # itself may reclaim mid-flight) or yesterday's backup log.
    assert "content/files/kntnt-extractor" in exclusions
    assert "content/files/kntnt-extractor-audit" in exclusions
    assert "content/files/kntnt-extractor-downloads" in exclusions
    assert "content/files/backwpup*" in exclusions

    # And the standard spelling stays, since it costs nothing and a manifest that
    # carries both layouts is a manifest neither spelling should miss.
    assert set(build_exclusions.ALWAYS_EXCLUDED) <= exclusions


def test_a_default_uploads_directory_adds_no_second_spelling() -> None:
    # Act — the standard layout, which the constant is already spelled at.
    exclusions = build(make_payload())

    # Assert — re-anchoring is a no-op there: exactly one spelling of each name.
    assert len([p for p in exclusions if p.endswith("/kntnt-extractor")]) == 1
    assert "wp-content/uploads/backwpup*" in exclusions


def test_including_blobs_omits_the_flagged_blobs() -> None:
    # Act — --include-blobs pins heavy_blobs to include.
    exclusions = set(build(make_payload(decisions={"heavy_blobs": "include"})))

    # Assert — the flagged blob path is not excluded, but the always-excluded set
    # still is.
    assert "wp-content/uploads/galleries" not in exclusions
    assert set(build_exclusions.ALWAYS_EXCLUDED) <= exclusions


def test_including_thumbnails_omits_the_exclude_set() -> None:
    # Act — a plan that resolves generated_thumbnails to include.
    exclusions = set(
        build(make_payload(decisions={"generated_thumbnails": "include"}))
    )

    # Assert — the DB-known thumbnail derivative is carried, not excluded.
    assert "wp-content/uploads/2024/05/banner-300x200.jpg" not in exclusions


def test_the_set_is_sorted_deduped_and_trailing_slash_normalised() -> None:
    # Arrange — a classification that repeats a path and spells one with a
    # trailing slash, the two shapes a hand-assembler would let diverge.
    payload = make_payload(
        thumbnails=[
            "wp-content/uploads/a-150x150.jpg",
            "wp-content/uploads/a-150x150.jpg",
        ],
        flagged=[{"path": "wp-content/uploads/galleries/", "size_bytes": 1}],
    )

    # Act.
    exclusions = build(payload)

    # Assert — sorted, no duplicates, no trailing slash.
    assert exclusions == sorted(exclusions)
    assert len(exclusions) == len(set(exclusions))
    assert "wp-content/uploads/galleries" in exclusions
    assert "wp-content/uploads/galleries/" not in exclusions


def test_the_set_is_never_empty() -> None:
    # Arrange — everything the operator could include is included, and the site
    # has no thumbnails or blobs at all.
    payload = make_payload(
        thumbnails=[],
        flagged=[],
        decisions={
            "generated_thumbnails": "include",
            "heavy_blobs": "include",
            "media_originals": "include",
        },
    )

    # Act.
    exclusions = build(payload)

    # Assert — the always-excluded constant guarantees a non-empty set, so
    # filter_manifest.py's "a real resolved exclusion set is never empty" contract
    # holds without the assembler ever emitting an unresolved-looking [].
    assert exclusions == sorted(build_exclusions.ALWAYS_EXCLUDED)
    assert exclusions


def test_selection_and_baseline_share_one_byte_identical_set() -> None:
    # Arrange — the same classifications and plan the clone §5 selection and the
    # §9.12 baseline (and pull's diff) each feed the assembler.
    payload = make_payload()

    # Act — two independent runs, standing in for the two consumers.
    first = run_build(payload)
    second = run_build(payload)

    # Assert — byte-identical output, the AC that the deletion diff is never
    # poisoned by a divergently-assembled set.
    assert first.returncode == 0
    assert first.stdout == second.stdout


# --- Fail-loud contract --------------------------------------------------------


def test_a_non_object_payload_fails_loud() -> None:
    result = run_build(["not", "an", "object"])
    assert result.returncode == 1
    assert b"build_exclusions:" in result.stderr


def test_invalid_json_fails_loud() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], input=b"{not json", capture_output=True
    )
    assert result.returncode == 1
    assert b"build_exclusions:" in result.stderr


def test_excluding_media_without_an_uploads_prefix_fails_loud() -> None:
    # Arrange — a plan that excludes media, but classifications missing the
    # uploads_prefix the exclusion must be anchored on.
    payload = make_payload(decisions={"media_originals": "exclude"})
    del payload["classifications"]["uploads_prefix"]

    # Act.
    result = run_build(payload)

    # Assert — a loud abort rather than a mis-anchored or dropped media exclusion.
    assert result.returncode == 1
    assert b"uploads_prefix" in result.stderr


def test_a_missing_decision_fails_loud() -> None:
    # Arrange — a plan whose decisions omit generated_thumbnails, one of the three
    # gates the set turns on.
    payload = make_payload()
    payload["plan"]["decisions"] = [
        entry
        for entry in payload["plan"]["decisions"]
        if entry["id"] != "generated_thumbnails"
    ]

    # Act.
    result = run_build(payload)

    # Assert — an unresolved plan is malformed input, not a silent default.
    assert result.returncode == 1
    assert b"generated_thumbnails" in result.stderr
