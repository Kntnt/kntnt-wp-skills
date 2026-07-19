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

// An unreadable subtree (a root-owned cache dir, a restricted upload
// subtree) must not vanish from the manifest without a trace (issue #18):
// scripts/filter_manifest.py's caller treats it as abort-worthy for the
// deletion gate, since a silently-shrunk tree would otherwise misclassify
// every file under it as production-deleted. This subclass catches the
// unreadable directory itself, via a readability pre-check in
// hasChildren(), before RecursiveIteratorIterator ever has to call the
// throwing getChildren() — and records the path into $unreadable, shared by
// reference across every recursion level so one list accumulates the whole
// walk's findings.
class Kntnt_Wp_Skills_Manifest_Directory_Iterator extends RecursiveDirectoryIterator {

	/** @var string[] Absolute paths this walk could not descend into. */
	public array $unreadable = [];

	public function hasChildren( bool $allow_links = false ): bool {
		if ( ! parent::hasChildren( $allow_links ) ) {
			return false;
		}
		if ( is_readable( $this->getPathname() ) && is_executable( $this->getPathname() ) ) {
			return true;
		}
		$this->unreadable[] = $this->getPathname();
		return false;
	}

	public function getChildren(): static {
		$child             = new static( $this->getPathname(), $this->getFlags() );
		$child->unreadable = &$this->unreadable;
		return $child;
	}

}

// Walk the whole content tree — no pruning, since no exclusion payload travels
// to production; the resolved scope is applied locally afterwards.
// CATCH_GET_CHILD stays on as defense-in-depth for the narrow race between the
// hasChildren() readability check above and getChildren() actually opening
// the directory (permissions revoked in between): without it, that residual
// UnexpectedValueException would still propagate out of the whole walk and
// kill the payload rather than just leaving that one subtree unrecorded.
$directory = new Kntnt_Wp_Skills_Manifest_Directory_Iterator( $content_dir, FilesystemIterator::SKIP_DOTS );
$walker    = new RecursiveIteratorIterator(
	$directory,
	RecursiveIteratorIterator::LEAVES_ONLY,
	RecursiveIteratorIterator::CATCH_GET_CHILD
);

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

// Anchor every unreadable directory at the WordPress root too, the same
// spelling entries use, so the caller can name the exact gap without
// re-deriving a root-relative path from an absolute one.
$unreadable = array_map(
	static fn( string $path ): string => substr( rtrim( $path, '/' ), strlen( $root ) ),
	$directory->unreadable
);

// Substitute rather than abort on an invalid-UTF-8 filename anywhere in the
// tree — without this flag a single such name makes json_encode() return
// false and the whole payload echo nothing.
echo json_encode( [ 'entries' => $entries, 'unreadable' => $unreadable ], JSON_INVALID_UTF8_SUBSTITUTE );
