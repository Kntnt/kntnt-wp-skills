<?php
// Novamira execute-php payload — the production-side baseline manifest emission
// (Baseline diff section, ADR-0006). INERT in this build: never run against a
// live site here (see templates/README.md). Sent as a fragment evaluated in the
// WordPress global scope, so no declare()/namespace. Echoes exactly one JSON
// object — the raw, unfiltered manifest scripts/filter_manifest.py reads on its
// way to becoming the shape scripts/baseline_diff.py consumes as its `current`
// side — and nothing else.
//
// Unfiltered by design (issue #18): this walk takes no exclusion payload and
// applies no scope filtering — the exclusion set (thousands of entries on a
// real site) never travels to production as part of a manifest request. It
// walks and reports every file under the content tree; the caller filters the
// result locally to the resolved scope afterwards (scripts/filter_manifest.py,
// ADR-0006 addendum), with scope semantics unchanged from the former
// production-side filter.
//
// Read-only: this payload walks the content tree and stats files, it never
// mutates production. It reports production mtimes so both sides of the diff are
// production mtimes; the diff is always production-now against the stored
// baseline, never against the local filesystem (platform constraint 19).

// Anchor every emitted path at the WordPress root, so the entries share the one
// spelling every exclusion consumer (the local filter, the deletion diff) later
// matches against (e.g. "wp-content/uploads/gallery"). Standard single-site
// layout, with the content directory under the root.
$root        = rtrim( ABSPATH, '/' ) . '/';
$content_dir = WP_CONTENT_DIR;

// Walk the whole content tree — no pruning, since no exclusion payload travels
// to production; the resolved scope is applied locally afterwards.
$directory = new RecursiveDirectoryIterator( $content_dir, FilesystemIterator::SKIP_DOTS );
$walker    = new RecursiveIteratorIterator( $directory );

// Record path, size, and mtime for every file under the content tree — the
// size+mtime quick-check pair the diff compares, once the caller has filtered
// this raw walk down to the resolved scope.
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

echo json_encode( [ 'entries' => $entries ] );
