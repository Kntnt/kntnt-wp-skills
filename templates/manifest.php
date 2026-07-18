<?php
// Novamira execute-php payload — the production-side baseline manifest emission
// (Baseline diff section, ADR-0006). INERT in this build: never run against a
// live site here (see templates/README.md). Sent as a fragment evaluated in the
// WordPress global scope, so no declare()/namespace. Echoes exactly one JSON
// object — the manifest shape scripts/baseline_diff.py consumes as its `current`
// side (and the skill stores verbatim as the next run's baseline) — and nothing
// else.
//
// Read-only: this payload walks the content tree and stats files, it never
// mutates production. It reports production mtimes so both sides of the diff are
// production mtimes; the diff is always production-now against the stored
// baseline, never against the local filesystem (platform constraint 19). The
// deterministic diff that consumes this manifest lives, tested, in the helper.

// The resolved exclusion set: anchored, WordPress-root-relative paths the engine
// computed from discovery and the gates (DB-known thumbnails, excluded blobs,
// drop-ins, the configuration file, caches, upgrade dirs, the Novamira sandbox).
// The runtime skill replaces this line with that set; the empty default emits a
// full-tree manifest. It is echoed back as the scope the manifest was taken
// under, so a later run can honour the scope-intersection deletion rule.
$exclusions = [];

// Anchor every path at the WordPress root, so the emitted paths and the
// exclusion prefixes share one spelling (e.g. "wp-content/uploads/gallery").
// Standard single-site layout, with the content directory under the root.
$root        = rtrim( ABSPATH, '/' ) . '/';
$content_dir = WP_CONTENT_DIR;

// Walk the content tree, pruning excluded directories so their subtrees are
// never descended — the reason the scope is stored rather than a full-scope
// manifest re-walked each run (ADR-0006).
$directory = new RecursiveDirectoryIterator( $content_dir, FilesystemIterator::SKIP_DOTS );
$filter    = new RecursiveCallbackFilterIterator(
	$directory,
	static function ( $current ) use ( $root, $exclusions ) {
		$relative = substr( $current->getPathname(), strlen( $root ) );
		return ! kntnt_wp_skills_is_excluded( $relative, $exclusions );
	}
);
$walker = new RecursiveIteratorIterator( $filter );

// Record path, size, and mtime for every in-scope file — the size+mtime
// quick-check pair the diff compares.
$entries = [];
foreach ( $walker as $file ) {
	if ( ! $file->isFile() ) {
		continue;
	}
	$relative  = substr( $file->getPathname(), strlen( $root ) );
	$entries[] = [
		'path'  => $relative,
		'size'  => $file->getSize(),
		'mtime' => $file->getMTime(),
	];
}

echo json_encode( [
	'scope'   => [ 'exclusions' => array_values( $exclusions ) ],
	'entries' => $entries,
] );

/**
 * Report whether an anchored, root-relative path falls under any exclusion
 * prefix — an exact match or a descendant of an excluded directory. Mirrors the
 * helper's `is_excluded` exactly, so the manifest is emitted under the same
 * scope the deletion diff later re-tests against. Matching is path-segment
 * aware: excluding `wp-content/uploads/gallery` never swallows a sibling
 * `wp-content/uploads/gallery-archive`.
 *
 * @param string   $path       The anchored, root-relative path to test.
 * @param string[] $exclusions The anchored exclusion prefixes.
 * @return bool True when the path is excluded, false when it is in scope.
 */
function kntnt_wp_skills_is_excluded( $path, $exclusions ) {
	foreach ( $exclusions as $prefix ) {
		$prefix = rtrim( $prefix, '/' );
		if ( $path === $prefix || str_starts_with( $path, $prefix . '/' ) ) {
			return true;
		}
	}
	return false;
}
