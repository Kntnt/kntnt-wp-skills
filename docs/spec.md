# kntnt-wp-skills — specification

This document specifies the plugin's three skills — `clone` and `pull` over the shared transfer engine, and the standalone scaffold skill `mkwp` — and is the single source of truth for the build. The **architectural decisions** behind it — with rationale and rejected alternatives — are recorded as ADRs in [`docs/adr/`](./adr/); never re-open one as an oversight. The project's **terminology** is defined in [`CONTEXT.md`](../CONTEXT.md) and is binding in code, documentation, and dialogue. All user-facing text and documentation is British English (`en_GB`); identifiers, flags, and config keys are English.

## Problem Statement

A faithful local copy of a production WordPress site is far more fiddly than it looks. The database and uploads are large; they carry real user data that has to move safely; and parts of them — analytics tables, generated thumbnails, oversized galleries — are better left behind or rebuilt locally than carried whole. The localisation steps are riddled with traps that fail silently or subtly: page builders store URLs as escaped JSON that a plain search-replace never touches, a rewrite flush without plugins loaded 404s every localised subpage, a MySQL 8 dump crashes a MariaDB import on collations, a non-default table prefix leaves WordPress staring at tables it cannot see, and a production object-cache drop-in bricks every request against a local Redis it cannot reach. A freshly imported copy also inherits production's outward reach — its real mailer, a running cron, queued campaigns against real subscribers — so a careless copy can act on real people the moment it boots.

Doing all this by hand, again and again for routine refreshes, is slow and easy to get subtly wrong. And not everyone has SSH access to automate it: the operator may have nothing more than WordPress admin on a managed host.

Today the plugin is a scaffold: the help mechanism and manual pages are live, but both skills are wired no-op stubs. This specification covers building the transfer engine and making the stubs real.

## Solution

`kntnt-wp-skills` is a Claude Code plugin that mirrors a live WordPress site down into a local DDEV copy. It ships two user-invoked skills — **`clone`** creates a fresh local copy in an empty directory, **`pull`** refreshes an existing one — over **one shared transfer engine** that does discovery, packing on production, download, verification, remote cleanup, import, and localisation. A clone is a pull with no baseline, so the incremental path is the only path.

The sole channel to production is the **Novamira MCP** server connected to the live site — never SSH. Every run starts with a **health check** that fails early and cheaply on everything that would otherwise surface only after a multi-gigabyte pack. Every decision the engine takes is a **recommendation behind an accept-or-override gate**; interactive mode walks the gates, `--yes` runs unattended and prints a full record, and a **saved plan** collapses a repeat run to a single replay gate. User data is encrypted in transit, packed outside the docroot, and deleted from production the moment the download verifies. The copy stays faithful by default — real mailer active, cron running — with a discovery-driven **mass-send valve** that flips the mail recommendation to capture only when a real campaign is poised to fire (a per-submission form-to-service integration is out of the valve's scope by design), and an always-emitted **risk warning** that itemises the copy's outward-reaching behaviours, including that integration hazard.

A third skill, **`mkwp`**, is standalone: it drives the `mkwp` command to scaffold a brand-new local WordPress site from nothing, sharing the recommendation-gate shape but none of the transfer engine's machinery — no production, no Novamira, no discovery, no baseline. It exists to give the operator the same one-command, gate-confirmed convenience for the "before" a `clone` would later target, or for any ad hoc local WordPress install.

## User Stories

1. As an operator, I want to clone a production WordPress site into an empty directory with one slash command, so that I get a working local DDEV copy without doing the fiddly parts by hand.
2. As an operator, I want to refresh an existing local copy with one slash command, so that routine re-syncs are quick and repeatable.
3. As an operator, I want both skills to reach production solely through the Novamira MCP, so that I never have to hand an AI SSH access to my server.
4. As an operator, I want both skills to run only when I explicitly invoke them, so that nothing ever executes code on production or overwrites my local database autonomously.
5. As an operator, I want a mandatory health check before any heavy work, so that a dead channel, a blocked download path, or a disabled exec capability fails in seconds instead of after a multi-gigabyte pack has run on production.
6. As an operator, I want the health check to confirm the MCP server targets production and not my local site, so that the production-side steps can never run against the wrong site.
7. As an operator, I want to be asked which server to use when several or no connected Novamira servers match the target URL, so that ambiguity never turns into a guess.
8. As an operator, I want a precise remediation message when the health check fails, so that I know exactly what to fix instead of debugging a stack trace.
9. As an operator, I want leftovers of an aborted earlier run swept from production during the health check, so that no stranded workspace outlives a crashed session.
10. As an operator, I want every decision put to me as a recommendation I accept with a single keystroke, so that a routine run is a short walk of accepts rather than a questionnaire.
11. As an operator, I want to decline a recommendation and see the alternatives, so that I stay in control without needing to know the option space in advance.
12. As an operator, I want a `--yes` mode that accepts every recommendation, never pauses, and prints a full record of what was decided and done, so that I can run unattended and read the record on return.
13. As an operator, I want my settled answers remembered per site, so that the next run collapses to a single "replay the saved plan?" gate.
14. As an operator, I want the saved plan to store decisions rather than computed lists, so that nothing in it goes stale as production evolves.
15. As an operator, I want the saved plan committed alongside the project, so that the copy is reproducible on another machine or after a reset.
16. As an operator, I want every table's structure carried always, so that nothing in the copy ever hits a missing table.
17. As an operator, I want operational tables — analytics, cookie consent, email logs, search index — carried empty by recommendation, so that the dump stays small without losing any schema.
18. As an operator, I want production's table prefix adopted locally at clone and verified at pull, so that the imported tables are the ones WordPress actually reads.
19. As an operator, I want the local DDEV database engine and PHP version pinned to production's, so that the import does not crash on collations and the copy behaves like production.
20. As an operator, I want media originals included by default but generated thumbnails excluded and rebuilt locally, so that the transfer skips gigabytes that can be regenerated.
21. As an operator, I want side-loaded files pulled whole, so that nothing that cannot be regenerated is ever lost.
22. As an operator, I want heavy blobs flagged by a deterministic heuristic and offered for exclusion behind a gate, so that a multi-gigabyte gallery never rides along unnoticed.
23. As an operator, I want production's behaviour-relevant configuration defines offered for porting while credentials, salts, paths, and infrastructure defines are auto-excluded, so that plugins keep working without production secrets landing on my machine.
24. As an operator, I want ported defines written into a clearly marked block that the skills own, so that they are visible, editable, and survive future pulls.
25. As an operator, I want a pull to surface any new production define of the portable class, so that configuration drift is brought to my attention instead of silently ignored.
26. As an operator, I want a pull to transfer only files that are new or changed since the last sync, so that a routine refresh moves megabytes, not gigabytes.
27. As an operator, I want the file diff taken against a stored production-side baseline rather than my local files, so that unreliable local mtimes never corrupt the decision of what to transfer.
28. As an operator, I want the scope stored with the baseline, so that excluding a previously included directory never makes its still-present files look production-deleted.
29. As an operator, I want deletion mirroring off by default and gated when on, so that no run — least of all a `--yes` run — ever removes anything as a surprise.
30. As an operator, I want deletions drawn only from provably production-deleted files and from itemised plugin/theme drift, so that local thumbnails, excluded blobs, and my dev tools are structurally immune.
31. As an operator, I want every confirmed deletion moved to a timestamped local trash rather than removed, so that any deletion is reversible until I empty it.
32. As an operator, I want the pack to run as a background job on production that the engine polls, so that a heavy dump never dies to an MCP timeout.
33. As an operator, I want a failed pack to surface its log tail, so that I see why it failed on a host I may not even have shell on.
34. As an operator, I want the poll to detect a dead pack process and stop at an explicit maximum wait, so that a mid-pack death never hangs my session.
35. As an operator, I want all packing to happen outside the docroot with only encrypted artifacts briefly published for download, so that plaintext user data never sits in a web-readable path — not even if my session dies mid-run.
36. As an operator, I want the encryption passphrase generated server-side, fetched only over the authenticated channel, and deleted at the end, so that it is never web-served.
37. As an operator, I want both artifacts checksummed on production and verified after download, so that a truncated or corrupted transfer is caught before it touches my local site.
38. As an operator, I want the remote working dir and download dir deleted immediately after verification, with a self-destruct timer and the next run's sweep as backstops, so that the exposure window is minutes even in the worst case.
39. As an operator, I want the database dumped with consistency flags safe for a live site, so that visitors are not locked out and the dump is not torn.
40. As an operator, I want my database password never returned into model context, so that the control channel cannot leak the one secret that unlocks everything.
41. As a pull operator, I want a rollback backup of the local database taken before the import, stored durably and reported, so that a bad refresh is one import away from undone.
42. As a pull operator, I want my locally deactivated plugins re-applied after import, so that tools I keep off stay off.
43. As a pull operator, I want the object-cache drop-in resolved by the ownership rule and then verified with a real request, so that production's cache configuration cannot brick every page of my copy.
44. As an operator, I want URL rewriting scoped to full URL forms including the escaped-JSON variants, so that page-builder content is localised and email addresses are never corrupted.
45. As an operator, I want the final rewrite flush run with plugins loaded, so that multilingual routes survive and localised subpages do not 404.
46. As an operator, I want thumbnails regenerated as a metadata-driven delta at pull, so that newly registered sizes appear without regenerating the whole library — with a flag to force the lot.
47. As an operator, I want the finished copy smoke-tested with URLs drawn from its own database — including a real localised subpage when a multilingual plugin is active — so that the classic silent failures are caught before the run reports success.
48. As an operator, I want the site's real mailer to stay active by default, so that I can test the send flow end to end.
49. As an operator, I want discovery to detect a poised mass-send and flip the mail recommendation to capture with a loud, specific warning, so that a queued campaign can never blast real subscribers from my copy.
50. As an operator, I want `--live-mail` and `--capture-mail` overrides, so that an unattended run can pin the mail behaviour either way.
51. As an operator, I want cron left running by default with `--no-cron` to opt out, so that the copy behaves like production unless I say otherwise.
52. As an operator, I want a risk warning always emitted itemising the copy's outward-reaching behaviours, so that the faithful-by-default posture is informed, never silent.
53. As a clone operator, I want the local DDEV project name and the clone's directory name both derived from the production URL behind their own confirm gates, so that naming is automatic but never wrong for an oddball domain.
54. As a clone operator, I want the site scaffolded at production's exact core version, so that core files never need to be transferred.
55. As a clone operator, I want to be told that local logins now use production credentials, and be offered removal of the scaffold's default themes and plugins, so that the copy starts clean and I am not locked out by surprise.
56. As an operator, I want `help`, `--help`, or `-h` on either skill — and the plugin's help command — to print the skill's manual page verbatim, so that usage lives in one place and is always current.
57. As a maintainer, I want a consistency test binding manpages, flags, and README links together, so that the documentation cannot silently drift from the implementation.
58. As a maintainer, I want the deterministic engine logic behind one helper surface with a JSON contract, so that the riskiest computations are unit-tested rather than improvised by the model at run time.
59. As a maintainer, I want the help mechanism built as the reference model for the sibling plugins, so that retrofitting them is a mechanical copy.
60. As an operator, I want production left state-neutral after every run, so that the only trace of a sync is the synced copy itself.
61. As an operator, I want form-submission tables excluded by default behind their own carry/empty gate, so that real visitors' names, emails, and messages do not land on my machine unless I deliberately choose to carry them.
62. As an operator, I want a `/mkwp` skill that scaffolds a brand-new local WordPress site with `mkwp`, deriving its flags from context where possible and confirming the rest at recommendation gates, so that starting a fresh local site is as convenient as `clone`/`pull` without needing a production source.
63. As an operator, I want `mkwp` to verify the local `mkwp` binary supports `--dirname` before scaffolding, so that an install too old for the plugin's conventions fails with install guidance instead of a confusing mid-scaffold error.
64. As an operator, I want `mkwp` to recommend installing Novamira on every new site by default, so that the site is already reachable by a later `clone`/`pull` without a separate manual step.
65. As an operator, I want the health check's own dependency step to check `ddev`, the required CLI tools, `mkwp` for `clone`, and the target site's connected Novamira server with its full set of abilities before any heavy work, so a missing dependency fails fast with a precise install instruction instead of deep inside a multi-gigabyte run.

## Implementation Decisions

### Architecture

- Two user-invoked skills over one shared transfer engine; `clone` and `pull` differ only at the bookends, and a clone is a pull against an empty baseline ([ADR-0003](./adr/0003-single-transfer-engine-clone-is-pull.md)). There is one transfer path, not two.
- A third, standalone skill, `mkwp`, sits beside the transfer engine rather than inside it: it drives the `mkwp` command to scaffold a brand-new site, with no production, no Novamira, and no baseline — see *The `mkwp` skill*, below.
- Every skill is user-invoked only — started solely by its slash command, never fired autonomously by the model ([ADR-0002](./adr/0002-skills-user-invoked-only.md)).
- The plugin is decoupled from `mkwp` the command: `mkwp` scaffolds only; import and localisation live in the engine, because `pull` needs them against an already-existing site ([ADR-0004](./adr/0004-decoupled-from-mkwp.md)). `clone` and the `mkwp` skill both scaffold with it, but only `clone` performs the engine-pin-and-restart bookend a fresh, production-shaped import needs.
- The plugin layout mirrors the sibling plugins `kntnt-code-skills` and `kntnt-text-skills`: a manifest, one skill per directory, one help command, helper scripts, and per-skill manpages.

### The deterministic helper seam

- All computation that needs neither production nor DDEV lives in a single helper surface: Python standalone scripts (inline dependency metadata, run via `uv`, per the project coding standard) invoked as a CLI taking JSON in and emitting JSON (or a generated script) out.
- The helper surface owns: the baseline diff, plan resolution over the layered defaults, the define/table/blob/integration classifications, the thumbnail exclude-set computation, the project- and directory-name derivation, the generation of the production-side pack script, the dump sanity checks, saved-plan reading and writing, and the manpage echo.
- The model orchestrates gates and MCP calls; it never computes a diff, a classification, an exclusion set, or a shell script by hand. This realises [ADR-0005](./adr/0005-decision-backbone-gates-and-layered-defaults.md)'s "the AI writes recommendations but never decides freely" as a code boundary, and it is the seam all automated tests exercise (see Testing Decisions).

### Subagent delegation

Four heavy, transport-noisy phases run in pinned subagents shipped under the plugin's `agents/` directory, with model and reasoning effort fixed in each definition's frontmatter, so their MCP round-trip logs, curl/checksum output, and regeneration warning spam never enter the orchestrating agent's own context: `discovery-classify` (discovery+classify), `pack-transfer` (pack+download+decrypt), `manifest-baseline-diff` (manifest+baseline diff), and `thumbnail-smoke-test` (thumbnail-regen+smoke-test). Every gate, the risk warning, plan resolution, and the wp-config edits stay in the main agent — subagents run once and can never ask the operator anything. Each subagent returns a structured **evidence block** (exit codes, artifact paths and SHA256, row/file counts, a `DONE`/`FAILED` marker); a result without one is treated as failed, and the orchestrator re-runs one or two cheap deterministic spot checks itself (`sha256sum -c`, `wp db check`'s exit code) rather than trusting the subagent's prose. Large payloads land in scratchpad files; only summaries and paths cross the agent boundary.

### Control channel

- The Novamira MCP is the sole channel to production; there is no SSH path and none will be added ([ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)). The free AGPL build suffices; the abilities used are `execute-php`, `run-wp-cli` (with background-job retrieval), `read-file`, `write-file`, and `list-directory`.
- `run-wp-cli` always takes its arguments as a JSON array — a single string silently returns the WP-CLI help text with exit 0.
- The production host must allow process spawning; the health check probes this independently, because a working `run-wp-cli` does not prove it (Novamira may run WP-CLI in-process).
- The skills never deactivate or delete Novamira on production — it is the control channel.
- `read-file` and `write-file` are **docroot-only**; they cannot see the outside-docroot working dir where the pack artifacts are staged before publication ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)). All outside-docroot IO — fetching `pass.key`, placing the generated `pack.sh` in the working dir — goes over `execute-php` with `file_get_contents` / `file_put_contents` instead, the same authenticated channel. `pass.key` must never be copied into the docroot, not even transiently.

### Health check (mandatory step 0, every run of both skills)

1. Verify every local and production dependency this run needs, local first since it is cheaper to fail before ever reaching production: `ddev` on `PATH` with its container backend actually responding (`ddev version` plus a cheap Docker/Colima liveness probe); the required CLI tools `uv`, `jq`, `curl`, `shasum`/`sha256sum`, and `openssl`; and, for `clone` only, `mkwp` on `PATH` meeting the `--dirname` floor (≥ 1.5.0) — verdicted by the shared `scripts/mkwp_guard.py` guard, the same one the `mkwp` skill's own version guard reads (§ *The `mkwp` skill*, below), never re-derived per caller. Then, on production: the connected Novamira server whose reported home URL matches the target URL — the operator may have several `novamira-*` servers configured, so ask when several or none match, never guess — and, via its `discover-abilities` call, that all five required abilities are present: `execute-php`, `run-wp-cli`, `read-file`, `write-file`, `list-directory`. On the first missing dependency, stop with a precise, per-dependency remediation message — what to install, where from, the command to re-run; the agent never installs system software itself, though a safely agent-runnable fix may be offered as its own accept-or-override gate — never auto-accepted under `--yes`, which has no operator present to consent to installing system software and so aborts with the remediation message instead of running the fix.
2. Prove the channel is live — not merely connected — with a trivial remote call returning the home URL, the WordPress root path, the PHP version, and the server software.
3. Confirm the server targets production, not the local DDEV site (the verify-targets-prod safety rail).
4. Probe process spawning with a live round-trip, and inspect the disabled-functions configuration; abort with a precise message if blocked (the native background-job fallback is deliberately deferred — [ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)).
5. Sweep production's temp and download bases for stranded workspaces from an aborted earlier run and remove them (belt-and-braces with the self-destruct timer). Runs before the preflight (step 6) so a batched pair of calls can never delete the preflight's own probe directory; this sweep must never run concurrently with an in-flight preflight.
6. Preflight the download path: write a tiny extension-less test file into a throwaway docroot directory, fetch it over HTTPS from the local side, delete it. This exercises permissions, extension rules, basic auth, WAF/CDN behaviour — before the heavy pack.
7. On any failure, abort with a precise remediation message — never a stack trace.

### Discovery (production, read-only)

One remote call gathers everything the recommendations derive from: home and site URLs, root and content paths, uploads base; database total size and top tables by size; a per-top-level-subdirectory size breakdown of uploads; the database server flavour, version, and default collation (MySQL 8 vs MariaDB, to pin DDEV and avoid the collation import crash); whether the content tables are InnoDB (so a single-transaction dump is safe); the PHP version (to pin DDEV's, at major.minor); free disk space and root writability; the table prefix; the active plugins and whether a multilingual plugin is among them (drives verification); the mass-send risk scan (below); the drop-ins present; the theme list; the core version (for scaffold pinning); and the database connection constants — the host may carry a port, and the password is **never** returned into context. It also probes the required binaries (dump, database client, encryption, archiving, checksum, and job-control tools), runs the blob heuristic, and computes the generated-thumbnail exclude-set from the attachment metadata.

The mass-send risk scan: for each recognised bulk-mail engine (FluentCRM, MailPoet, The Newsletter Plugin, Mailchimp for WP, Brevo, …), whether a campaign is queued or scheduled and the recipient-list size — a *poised* campaign, not mere plugin presence, is what flips the mail default. For an unrecognised mailer it falls back to a generic signal (a sending cron event plus a large pending queue) and, when uncertain, does not flip but surfaces the finding.

### The decision backbone

- Every decision is a recommendation with an accept/override gate; `Y` accepts, `n` reveals the alternatives — even multi-valued decisions are expressed this way ([ADR-0005](./adr/0005-decision-backbone-gates-and-layered-defaults.md)).
- Three speeds run over one ordered decision list: interactive (walk each gate), `--yes` (accept every recommendation, print a full record), and replay (a saved plan collapses interactive to a single "Replay the saved plan?" gate; `--yes` runs it silently).
- Defaults layer as: built-in default < live derivation < saved config < this run's answer. `--yes` stops at the saved-config layer.
- The saved plan stores decisions, never computed lists — the inactive-plugin set and blob list re-derive from live state each run, so nothing goes stale.

### The decisions and their recommended defaults

| Decision | Recommended default | Notes |
|---|---|---|
| DB — table structure | All tables, always, with production's exact schema | Nothing ever hits a missing table |
| DB — table content | Full data for content/config/users/CRM; empty for operational tables (analytics / cookie-consent / email-log / search-index) | Binary per table: full or empty |
| User-submission tables | Empty by default, behind its own carry/empty gate | Form-entry tables (WS Form / Fluent Forms / Formidable / WPForms / Gravity Forms); non-regenerable and privacy-sensitive, so it is not folded into the silent operational split ([ADR-0014](./adr/0014-user-submissions-own-gate-default-empty.md)) |
| Table prefix | Adopt production's prefix locally | Written at clone; verified at pull, abort on mismatch |
| DB engine + PHP | Pin DDEV to production's | Engine flavour+version and PHP major.minor, from discovery |
| Media Library originals | Included | Clone: full; pull: delta only |
| Generated thumbnails | Excluded, regenerated locally | Only the DB-known sizes ([ADR-0011](./adr/0011-metadata-driven-thumbnail-regeneration.md)) |
| Side-loaded / orphan files | Pulled whole | Cannot be regenerated, so they are carried |
| Heavy blobs | Excluded, behind a gate | Deterministic heuristic flags outliers; the gate is the authority |
| wp-config defines | Copy the plugin/behaviour class; auto-exclude the infra/secret class | See below |
| Plugins to deactivate (pull) | Preserve the local inactive set | Derived from live local state each run |
| Object-cache drop-in (pull) | Derive from the ownership rule, then verify | keep-local / take-prod / none; auto-remove on failure |
| Mail | Keep the existing mailer active; flips to capture only on a detected poised mass-send | [ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md); `--live-mail` / `--capture-mail` force it |
| Cron | Leave running always; `--no-cron` opts out | The mass-send valve is what keeps this safe |
| Deletion mirroring | No | Itemised and reversible when enabled ([ADR-0010](./adr/0010-deletion-mirroring-opt-in-trash.md)) |

### Thumbnails and regeneration

Exclude from transfer exactly the DB-known generated sizes (from each attachment's registered sizes in its metadata); pull whole everything not in that set, because only DB-registered attachments can be regenerated; regenerate after import — all attachments at clone, the metadata-driven delta at pull (compare each attachment's registered sizes against the files on disk), with `--regenerate-all` as the escape hatch. Full rationale in [ADR-0011](./adr/0011-metadata-driven-thumbnail-regeneration.md).

### User-submission tables

Form-entry tables (WS Form, Fluent Forms, Formidable, WPForms, Gravity Forms) are matched into their own classification family, distinct from the four operational categories folded silently into table content: they are neither regenerable nor operational, and they carry the most privacy-sensitive data the transfer handles. Unlike the operational split, this class gets its own carry/empty gate, default **empty** for privacy minimisation, with the gate as the way back for an operator who needs real entries to debug a form flow locally. The choice is a remembered per-site answer, persisted in the saved plan and replayed like every other decision. Full rationale in [ADR-0014](./adr/0014-user-submissions-own-gate-default-empty.md).

### wp-config defines

Discovery extracts production's defines. The auto-excluded class — copying it would break or mis-key the local site — is: database credentials; auth keys, salts, and nonces (production secrets never come down); domain and path constants; and infrastructure constants (cache toggles, cache-server hosts, cron disabling). The remaining plugin/behaviour defines are offered as a gate, default copy, deselect on decline. Chosen defines are written into the marked block the skills own in the local configuration, separate from the scaffold's DDEV block, and the chosen set is remembered. Because pull never overwrites the local configuration file, ported defines persist; if production later grows a new define of the portable class, the pull report surfaces it.

### Table prefix

Discovery reads production's table prefix. The scaffold assumes the WordPress default; if production differs, the imported tables would exist but WordPress would find none of them. So clone writes production's prefix into the marked block, and pull verifies the local prefix matches production and aborts on mismatch rather than importing tables the local install cannot see.

### Deletion mirroring

Opt-in, default No, and under `--yes` there must be no surprise removals ([ADR-0010](./adr/0010-deletion-mirroring-opt-in-trash.md)). When enabled, each source is itemised: production-deleted files (in the stored baseline but gone from production now, intersected with the current scope) and plugin/theme drift (local plugins/themes with no production counterpart, presented as a checklist). Confirmed items are moved to the timestamped local trash, never hard-deleted, and the path is reported. It is a remembered per-site answer, so "make it identical" is one Yes for that site.

### Mail, cron, and the mass-send valve

The posture — faithful by default with one risk-adaptive valve, cron left running — is a settled departure from the security review ([ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md)). Operationally: the mail gate recommends keeping the site's existing mailer active; when discovery finds a poised mass-send, the gate leads with a loud, specific warning naming the engine, the campaign, and the recipient count, and the recommendation flips to capture. Capture, when chosen, is a mu-plugin that short-circuits the mail function to DDEV's Mailpit at top priority — catching API mailers that never touch sendmail — installed only in the capture branch. Cron always runs unless `--no-cron` writes the cron-disabling define. `--yes` accepts the risk-adaptive recommendation; `--live-mail` forces the real mailer even past a detected campaign; `--capture-mail` forces capture regardless.

### Baseline diff (files)

Production emits a manifest of its **whole** content tree (path + size + mtime), unfiltered — the exclusion set never travels to production as part of a manifest request. The resolved scope is applied locally to filter it before the diff, and the locally-filtered manifest carries that scope forward ([ADR-0006](./adr/0006-baseline-manifest-diff-with-scope.md) addendum). The diff is production-now against the stored baseline — never the local filesystem, because local mtimes are unreliable through the archive-and-sync chain. Clone has no baseline, so everything is new. The diff yields the new/changed set (to pull) and the production-deleted set (for the deletion gate); the deletion set is computed only over paths in scope in both the baseline and this run. Detection is size + mtime. The database is always dumped in full — trimmed it is small and not worth diffing.

### Pack on production (background job)

- All packing happens in a working dir outside the docroot — the system temp dir, else a directory above the WordPress root. If neither is writable, abort rather than fall back to a working dir inside the docroot: the passphrase file lives in that same working dir and must never enter the docroot, not even transiently. The passphrase file, the database-client credentials file, the log, and every intermediate live there, never web-readable. Only the three finished artifacts — `db.enc`, `files.enc`, `SHA256` — are published into a random-named docroot download dir ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)).
- The pack runs as a detached background job launched from the control channel, and the client polls for DONE/FAILED markers — heavy dump-and-archive work inside a single synchronous call would hit MCP timeouts ([ADR-0007](./adr/0007-background-pack-job-with-polling.md)).
- The passphrase is generated server-side into a permission-restricted file in the working dir, passed to the encryption tool by file reference, fetched locally only over `execute-php` (`file_get_contents`) (never over HTTP), and deleted in cleanup.
- The database dump runs in two passes with live-site consistency flags (single transaction, quick, no table locks — safe because discovery confirmed InnoDB; if a content table is not, fall back with a logged consistency caveat): full data for the content tables, schema-only for the empty-classified ones, so every table exists, some with zero rows. The dump is compressed then encrypted to `db.enc`.
- At clone, the file archive is built from an exclusion file of full anchored relative paths (DB-known thumbnails, excluded blobs, drop-ins, the configuration file, logs, caches, upgrade dirs, the Novamira sandbox) with wildcard matching disabled — patterns on the command line would overflow the argument limit and basename patterns would wrongly match same-named originals elsewhere — and streamed straight through encryption to `files.enc`. At pull, only the new/changed set is packed — already filtered locally to scope by the baseline diff (see *Baseline diff (files)*, above) — so no exclusion file applies: it carries nothing left to exclude.
- Checksums are computed over the final artifact names, then the three artifacts are moved into the download dir with world-readable permissions.
- The pack script runs under strict shell error handling with a trap that on failure writes a FAILED marker plus the log tail into the download dir; on success it writes DONE. It also arms a self-destruct — a detached delayed removal of both directories — so the workspace and passphrase vanish even if the client never returns.
- Polling checks DONE, FAILED, and process liveness, with an explicit maximum wait; on FAILED it surfaces the log tail and aborts; a dead process or an exhausted wait aborts with the tail rather than hanging.

### Download, verify, and close the exposure window

The three artifacts are fetched over HTTPS with resume and retry, and the checksums are verified locally against the same names they were computed under. Both artifacts are named `.enc` from creation — never renamed — because managed hosts 404 archive extensions while serving `.enc` and extension-less files fine, and identical create-time/verify-time names keep checksum verification honest ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)). The passphrase then comes down over the authenticated channel, both artifacts are decrypted, and the dump is decompressed. Immediately after checksums pass, both remote directories — download dir and working dir, including passphrase and credentials file — are deleted and verified gone. The self-destruct timer and the next health check's sweep are the backstops.

### Import and localise (local, destructive)

In order:

1. Pull only: back up the local database to the durable, gitignored backups location before anything destructive.
2. Sanity-check the decrypted dump against the discovered prefix: table-creation count, content-table inserts present, each empty-classified table created but empty.
3. Import into DDEV and verify table and post counts.
4. Extract the file archive over the content directory as a merge: the local configuration file and local-only files survive; production's plugin, theme, and media files overwrite.
5. Deletions, if enabled: move the confirmed items to the local trash.
6. Pull only: apply the object-cache ownership rule — no local drop-in → nothing; different owner than production → keep local; same owner → take production's — then verify a real request succeeds and auto-remove the drop-in on failure, reporting it.
7. Write the chosen defines and (at clone) production's table prefix into the marked block; at pull, assert the prefix matches and abort on mismatch.
8. Apply the resolved mail choice (keep the mailer, or install the capture mu-plugin) and the cron choice.
9. Pull only: re-apply the preserved inactive set with plugin and theme code skipped during deactivation, so an object-cache plugin cannot re-drop its drop-in mid-step.
10. URL-scoped search-replace across all tables, skipping the GUID column: passes for the secure/insecure and www/bare URL forms, the protocol-relative forms, and the escaped-slash forms that page builders store inside JSON — never the bare domain, which corrupts email addresses. Serialised objects the replace tool safely skips keep the old domain; harmless.
11. Set the home and site URL options explicitly to the DDEV URL.
12. Regenerate thumbnails for the affected attachments (all at clone; the metadata-driven delta at pull; `--regenerate-all` forces the lot).
13. Flush rewrite rules with plugins loaded — a flush without them silently drops multilingual and custom routes, 404ing localised subpages.
14. Restart the DDEV project to clear the PHP-process caches a cache flush cannot reach.
15. Write the new baseline manifest, with the scope it was taken under.

### Verify

Verify from live state, never assumption, against a deterministic **expectations** object — never an ad-hoc, hand-checked list — checked by the single deterministic helper `scripts/smoke_test.py` (see *Testing Decisions*, below). The expectations object is assembled from what the run already knows: the discovered core version; the DDEV PHP and database engine/version pins; production's table prefix; the local DDEV URL; entity counts (published posts, pages, users, attachments); the table split — the empty-table list in full, and the content-table non-empty assertion restricted to the small set of core tables production is always expected to carry rows for (`posts`, `options`, `users`), never the whole content-table list, since "carried in full" only means the transfer did not silently empty a table, not that production actually put rows in it; the excluded drop-ins expected absent locally — minus the object-cache drop-in whenever the ownership rule (§ *Import and localise*, step 6) resolved to keep it present, since a drop-in can never be expected both absent and present at once — and, at pull, that same drop-in's expected presence; the smoke-test URL list — the front page plus a couple of real published URLs from the database, and, only if discovery found an active multilingual plugin, the localised home and a real localised subpage, the canary for the rewrite bug; the local-asset check for a lingering production-host reference; the expected active-plugin count; and confirmation that the saved plan and baseline are expected to exist. The script asserts success responses and the absence of the WordPress critical-error, fatal-error, and database-connection-error markers in the HTML, runs a database integrity check, and reports a pass/fail/attention verdict per check. It also runs standalone from a terminal for a manual re-verification against a hand-edited or previously generated expectations file, and its `--generate` mode snapshots one from a discovery document.

### Cleanup

Remove the large local scratch artifacts. The pull rollback backup already lives durably — report its path. Production is already state-neutral: temp dirs deleted, nothing started.

### Clone bookends

- Derive two names from the production URL: the local DDEV project name — strip scheme and www, take the main label, sanitise to the scaffolder's charset — and the clone's directory name — strip scheme, userinfo, port, and path, keeping `www.` and every dot verbatim. Each is its own decision in the ordered gate list, so the operator can correct either independently; `--yes` accepts both. No public-suffix-list dependency; the gates cover oddball domains.
- The `mkwp` version guard already ran during the health check's dependency step (§ *Health check*, above); nothing here re-checks it.
- Scaffold, correct the engine, then restart — not "pin before any start": `mkwp` has no `--db=` flag today, so its scaffold unconditionally brings DDEV up once already, on the default database engine, before control returns; that cannot be deferred past the pin below, because `mkwp` performs it internally.
  1. Scaffold with `mkwp` at production's exact core version into the derived directory name (`mkwp`'s `--dirname` flag), with the DDEV project registered under the derived project name; core files are never transferred.
  2. Discard the scaffold's throwaway default-engine database: `ddev stop`, then `ddev delete -Oy` — no data loss, nothing but the placeholder install ever lived in it.
  3. Pin DDEV's database engine+version and PHP version to production's — `ddev config --database=<flavour>:<version> --php-version=<major.minor>` against `.ddev/config.yaml`, the database version truncated to `major.minor` exactly as PHP already is — and write production's table prefix into the marked block. Prefer a future `mkwp --db=` flag once it exists; it does not today.
  4. Restart with `ddev start` on the corrected engine before anything downstream runs.

  This is the same `ddev delete -Oy` plus reconfigure-and-restart cycle a smoke test once had to run late, deep inside an already-populated site, after a scaffolded MariaDB 11.8 collided with a production 11.4 at import; running it deliberately, immediately after scaffold, costs nothing.
- No pre-import backup, no preserved inactive set, no object-cache derivation — nothing local pre-exists.
- After import, local users are production's: the report says to log in with production credentials, and offers to remove the scaffold's default themes and plugins left sitting beside production's.

### Pull bookends

- Pre-import rollback backup, always.
- Verify the local table prefix matches production; abort on mismatch.
- Preserve the local inactive plugin set (derived each run).
- Object-cache ownership derivation, then verify-and-fallback.
- Incremental file transfer against the stored baseline; deletion gate to the local trash.

### The `mkwp` skill

Standalone: it scaffolds a brand-new local WordPress site by driving the `mkwp` command, sharing the recommendation-gate shape with `clone`/`pull` but none of the transfer engine underneath — no production, no Novamira, no discovery, no baseline, no import.

- **Dependency check.** Before anything else, run the **local** portion of `clone`/`pull`'s own dependency step (§ *Health check*, above) — production-side checks (the Novamira ability inventory, the liveness/exec probes) do not apply, since `mkwp` never touches production: `ddev` on `PATH` with its container backend actually responding (`ddev version` plus a cheap Docker/Colima liveness probe); the required CLI tools `uv`, `jq`, `curl`, `shasum`/`sha256sum`, and `openssl`; and the local `mkwp` on `PATH` supporting `--dirname` — the floor is `mkwp` ≥ 1.5.0 ([Kntnt/mkwp#2](https://github.com/Kntnt/mkwp/issues/2)). The `mkwp` version check is verdicted by the shared `scripts/mkwp_guard.py` guard, the same one `clone`'s own health check runs as part of its dependency step; every caller reads the single verdict-and-remediation helper rather than deriving the check independently. Abort with precise install guidance on the first missing dependency.
- **NAME first.** `NAME` is the one value with no sensible universal default (the site's own identity), so it is always settled first — from context or by asking directly, even under `--yes`.
- **The remaining decisions**, each a recommendation behind an accept-or-override gate exactly like `clone`/`pull`'s: `--dirname` (default `NAME`, kept as the default even when the operator names a domain the site is meant to mirror — a diverging `--dirname` is known to break the scaffold outright against every `mkwp` version verified so far, see the caveat below, so the mirrored domain's full host, via the same `derive_directory_name` convention `clone` uses for its own directory naming — issue #11 — is offered only as an explicitly-opted-into, warned-against alternative, never the default recommendation), `--directory`, `--title`, `--email`/`--user`, `--language`, `--php`, `--wp`, `--themes`, `--plugins`, `--mu-plugins`. Every one defaults to `mkwp`'s own default (the flag is simply omitted) unless the conversation's context supplies a better value.
- **Novamira by default.** `--plugins` always recommends **Novamira** alongside anything context names, because the site needs the control channel the moment it becomes a production site `clone`/`pull` reach ([ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)). Novamira has no WordPress.org listing; the exact download URL is resolved at run time from its latest GitHub release, matching the release's asset **by name** against `novamira-*.zip` — never the first asset positionally, which a future checksums or SBOM asset could silently mis-resolve (`github.com/use-novamira/novamira`) — a bare repo URL or a `.git` clone URL both install a plugin that cannot activate (live-verified: neither carries Novamira's bundled `vendor/` directory, which only the packaged release zip does). If resolution fails — the unauthenticated GitHub API's rate limit, a network error, or no matching asset — Novamira is dropped from that run's `--plugins` rather than passed a guessed URL, and the operator is told to add it manually once a working URL is available. If the parked companion-plugin epic ([issue #24](https://github.com/Kntnt/kntnt-wp-skills/issues/24)) ever replaces the control channel, this recommendation switches to the companion plugin instead.
- **No password ever gathered.** `--password` is never offered or passed; the first user's password is always `mkwp`'s own random generation. The whole `mkwp` run is redirected to a log file rather than captured as this skill's tool output — a successful run's own on-screen report prints that password verbatim, so capturing it would carry the password straight into this skill's context — and the operator reads the generated credentials from that log file (or their own terminal, if they run `mkwp` themselves) directly.
- **No persistent config of its own.** Unlike `clone`/`pull`, `mkwp` writes neither `.kntnt-wp-skills.json` nor `.kntnt-wp-skills/` — those exist only once the site is later brought under `clone`.
- **Known upstream caveat (live-verified 2026-07-19).** `mkwp` 1.7.0's own `ddev config` call never passes `--project-name`, so DDEV registers the project under the *directory's* name whenever `--dirname` differs from `NAME` — but `mkwp` still hardcodes the wp-config database host to `ddev-<NAME>-db`, so the scaffold fails outright with a database-connection error before `wp-config.php` is ever written. The skill verifies `wp-config.php` exists after running `mkwp`, diagnoses this specific failure by name from the run log rather than surfacing the raw error, and cleans up the partial scaffold (`ddev delete -Oy` to unregister the DDEV project, then the partial directory) before reporting the failure. The same risk applies to `clone`'s own `--dirname` usage (issue #11) whenever a production host's derived directory name differs from its derived project slug — the common case for a `www.`-prefixed domain — flagged here for a follow-up issue against `Kntnt/mkwp` and this plugin, not fixed by either skill from the outside.

### Run modes and flags

Interactive is the default; `--yes` is autonomous; replay engages automatically when a saved plan exists. The flag surface is deliberately minimal per skill ([ADR-0013](./adr/0013-minimal-flag-surface.md)): `clone`/`pull` share `--yes`, `--include-media` / `--exclude-media`, `--include-blobs`, `--live-mail` / `--capture-mail`, `--no-cron`, `--regenerate-all`, and the help forms (`help`, `--help`, `-h`); `mkwp`'s own surface is unrelated — `--yes`, `--dirname`, `--directory`, `--title`, `--email`, `--user`, `--language`, `--php`, `--wp`, `--themes`, `--plugins`, `--mu-plugins`, and the same help forms. No dry-run, no regex filters, no replay (there is nothing to replay against — `mkwp` has no saved plan).

### Persistent config

Two small per-project files at the local project root:

- `.kntnt-wp-skills.json` — the saved plan: the settled per-site answers, committed so the copy is reproducible. All keys optional; a missing key falls back to the built-in default. It records the source (MCP server and live URL), the target DDEV project, the clone's directory name, the empty-table classification patterns, the user-submissions carry/empty answer ([ADR-0014](./adr/0014-user-submissions-own-gate-default-empty.md)), the scope decisions (media, excluded blobs), the ported defines, the plugin-preservation choice, the object-cache mode, the mail mode (risk-adaptive by default, or pinned live/capture), the cron choice, and the deletion-mirroring answer. There is deliberately no production-mutation key — mutating production is always a separate, explicit instruction.
- `.kntnt-wp-skills/` — derived, gitignored state: the baseline manifest with its scope, the pull rollback backups, and the trash.

### Help mechanism

The single source of truth for usage is one Markdown manpage per skill (NAME, SYNOPSIS, DESCRIPTION, OPTIONS, EXAMPLES, FILES), echoed verbatim by the help script — no rendering, since Claude Code renders Markdown in the terminal ([ADR-0012](./adr/0012-manpage-help-mechanism.md)). Two entry points reach one source: the plugin help command (no argument → overview assembled from the manifest blurb and each manpage's NAME line; a skill name → that manpage verbatim; anything else → the unknown-skill line) and each skill's help-gate as its first step. The README links to the manpages rather than restating usage. This mechanism is the reference model to retrofit the sibling plugins — but the retrofit itself is out of scope here.

### Safety rails (non-negotiable)

- Verify the MCP targets production before anything; no SSH, ever; never deactivate or delete Novamira on production.
- Never mutate production except the short-lived temp dirs, deleted immediately after the pull; any other production mutation is explicit, out of band, confirmed, and never part of `--yes`.
- All remote packing outside the docroot; only encrypted artifacts briefly web-published; the passphrase never web-served; the database password never in context; self-destruct timer and health-check sweep as backstops.
- Pre-import backup before the destructive local step at pull; deletions to trash, never hard removal.
- URL-scoped search-replace only, including the escaped forms; final rewrite flush with plugins loaded.
- Mail faithful by default with the mass-send valve; the risk warning is always emitted — interactive waits for confirmation, `--yes` prints it for the record and proceeds. Each detected per-submission form-to-service integration is a mandatory bullet in that warning, since the valve's poised-campaign scan cannot see a single local form submit ([ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md)).

### Platform constraints (settled the hard way — build to them)

1. `run-wp-cli` given a plain string silently returns the WP-CLI help with exit 0 — arguments always travel as a JSON array.
2. Managed hosts commonly disable process spawning, which kills the detached pack job silently — the health check probes it live and independently; a working `run-wp-cli` proves nothing.
3. Managed hosts 404 archive extensions — artifacts are `.enc` and the checksum file extension-less from creation, and the preflight proves the download path before the pack.
4. Heavy dump-and-archive work in one synchronous MCP call times out — background job plus marker polling, with a trap-written FAILED marker, a process-liveness check, and an explicit maximum wait.
5. Dumping a live site without single-transaction/quick/no-locks flags locks tables or tears data — discovery confirms InnoDB first; a MyISAM content table triggers a logged-caveat fallback.
6. The database host constant may embed a port — split host and port for the client credentials file.
7. MariaDB's "deprecated program name" notice on stderr is harmless — never treat it as failure.
8. The database password never enters model context; the encryption passphrase is server-generated, kept outside the docroot, fetched only over the authenticated channel, and deleted at the end.
9. Archive exclusions as command-line or basename patterns overflow the argument limit and mis-match same-named files — full anchored relative paths in an exclusion file, wildcards disabled.
10. Archiving a live tree emits file-changed warnings — suppress that specific warning class.
11. A MySQL 8 dump's modern collations crash a MariaDB import, and an unpinned PHP diverges from production — pin DDEV's database and PHP to discovery's findings.
12. A non-default production table prefix leaves WordPress finding zero tables — write it at clone, verify it at pull.
13. Bare-domain search-replace corrupts email addresses, and page-builder JSON stores escaped URLs a plain pass misses — URL-scoped passes only, including the escaped-slash forms.
14. A rewrite flush without plugins loaded drops multilingual and custom routes — the final flush loads plugins.
15. A cache flush cannot clear the PHP-process caches — restart the DDEV project.
16. A production object-cache drop-in pointing at a loopback cache host is fatal against DDEV — verify a request after writing it, auto-remove on failure.
17. WP-CLI under newer PHP emits cosmetic deprecation notices on stderr — filter them from reports.
18. The import replaces local users with production's — the report tells the operator to log in with production credentials.
19. Local mtimes are unreliable through the archive-and-sync chain — diff against the stored production-side baseline, never the local filesystem, and store the scope with it.
20. A running cron can autonomously fire a queued campaign at real subscribers — the mass-send valve, the itemised risk warning, and `--no-cron` are the controls.
21. Thumbnail regeneration is DB-only and a file diff misses newly registered sizes — the regeneration delta is metadata-driven, with `--regenerate-all` as the sledgehammer.
22. A form plugin's active service add-on writes a single local submission straight to a live third-party service, and the mass-send valve's poised-campaign scan cannot see it — `classify.py` detects each active form-to-service pairing by name pattern, and a mandated bullet in the itemised risk warning is the control ([ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md)).

### Preconditions (documented in the README)

DDEV up and running (with Docker or equivalent); the free Novamira plugin installed and enabled on production with its MCP server connected in Claude Code, for `clone`/`pull`; `mkwp` ≥ 1.5.0 on the operator's PATH for `clone` and for the `mkwp` skill alike (its `--dirname` flag names the site's directory independently of the DDEV project name); the CLI tools `uv`, `jq`, `curl`, `shasum`/`sha256sum`, and `openssl`. `clone`/`pull`'s health check (§ *Health check*, above) verifies all of this automatically at the start of every run, with guided remediation on anything missing.

## Testing Decisions

- A good test exercises **external behaviour at the seam** — fixtures in, observable outputs out — and never reaches into implementation internals. Tests are named for the behaviour they assert, follow Arrange-Act-Assert, and each is seen failing before the satisfying code exists (red first), per the project coding standard.
- **The single automated seam is the deterministic helper CLI.** Fixture discovery payloads, baselines, saved plans, and local-state snapshots go in as JSON; the assertions are on what comes out: the baseline diff (new/changed and production-deleted sets, including the scope-intersection rule that keeps a scope change from poisoning the deletion set), plan resolution across all four default layers (including that `--yes` stops at the saved-config layer and that flags pin their decisions), the classifications (defines into auto-excluded vs portable, tables into full vs empty, blob flagging, per-submission form-to-service integrations by name-pattern pairing, the thumbnail exclude-set from attachment-metadata fixtures — including the ambiguous same-name original/derivative case), the project- and directory-name derivation, the dump sanity verdicts, the saved-plan round-trip, and the generated pack script's content (anchored exclusion file, artifacts named `.enc` from creation, checksums over final names, DONE/FAILED markers, self-destruct arming).
- **The generated pack script is additionally executed** in a sandboxed temp directory with stub binaries on the path standing in for the database tools, proving its runtime contract at the same seam: the success path yields DONE, three artifacts, and checksums that verify; an induced failure yields FAILED plus the log tail in the download dir; and at no point does plaintext appear in the simulated docroot.
- **The help/docs consistency test** binds the documentation together: every skill has a manpage, every flag documented in a manpage's OPTIONS table is one that skill's own flag registry accepts and vice versa (checked per skill — `mkwp`'s independent surface is never cross-checked against `clone`/`pull`'s), the overview lists each manpage's NAME line, and the README's manpage links resolve.
- **The `mkwp` version guard** is unit-tested at its own seam: `mkwp --help` output (or its absence) in, a pass/fail verdict with a remediation message out.
- Framework: pytest, provisioned by uv, per the Python module of the coding standard. There is no prior test art in this repository — this suite is the first; the existing help script establishes the standalone-script shape the helpers follow.
- **Stated residual, verified by humans at run time rather than CI:** the skill orchestration prose, the real Novamira interaction, the real `mkwp`/DDEV interaction, and the real DDEV import and localisation. These are covered by the engine's own verify phase on every run — the deterministic expectations object `scripts/smoke_test.py` checks (smoke URLs from live state, error greps, database check, and the rest of its check surface) — plus a manual end-to-end smoke — a clone followed by a pull against a real site — before release.

## Out of Scope

- Pushing anything local → production, and any production mutation beyond the short-lived temp dirs.
- Any SSH path ([ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)).
- WordPress multisite; the target is single-site, personal use, driven by hand.
- The native background-job fallback for hosts that block process spawning — deferred until a host actually blocks it ([ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)).
- A checksum-based diff mode — size + mtime suffices now; noted as a possible later addition ([ADR-0006](./adr/0006-baseline-manifest-diff-with-scope.md)).
- DDEV-native Redis provisioning — the drop-in verify-and-remove fallback covers the failure mode.
- `--dry-run`, regex include/exclude filters, a static shipped help file, and the formal blob-threshold engine — cut, and recorded so they are not re-proposed ([ADR-0013](./adr/0013-minimal-flag-surface.md)).
- Retrofitting the sibling plugins with the manpage help model — this plugin is the reference; the retrofit is separate work ([ADR-0012](./adr/0012-manpage-help-mechanism.md)).
- The `mkwp` template-seeder capability — a separate, non-blocking track in the `mkwp` repository ([ADR-0004](./adr/0004-decoupled-from-mkwp.md)).
- A CI-run DDEV integration harness — deliberately not built; the runtime verify phase and the manual smoke carry that layer.
- Team or multi-operator workflows — the tool assumes a single, aware operator ([ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md)).

## Further Notes

- A 20-point security/robustness review was reconciled into this design in full. Most points were adopted outright; the one substantive departure — live mail by default with the mass-send valve, cron left running — is settled in [ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md), and the deliberate deferrals and trade-off choices are recorded in [ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md), [ADR-0006](./adr/0006-baseline-manifest-diff-with-scope.md), and [ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md). None of these is an oversight to fix.
- The manpages for both skills already exist and document the target behaviour, including the full flag surface — they are the usage contract this spec's engine must satisfy, and they remain the single source of usage truth.
- The plugin scaffold, help command, and help script are live; both skills are wired no-op stubs whose only active behaviour is the help-gate. Implementation replaces the stub bodies with the orchestration this spec describes.
- This specification supersedes the earlier design-and-build-plan document; the ADRs and the glossary carry everything that document settled architecturally and terminologically.
- The invocation-level literals behind these decisions — exact commands, flags, filenames, permissions, and timer values — are preserved in [`docs/implementation-notes.md`](./implementation-notes.md), which also carries the security-review reconciliation table as a historic record. This spec is authoritative where they diverge.
