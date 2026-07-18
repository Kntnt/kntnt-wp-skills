<?php
// Novamira execute-php payload — stranded-workspace sweep (health check step 6).
// INERT in this build: never run against a live site here (see
// templates/README.md). Sent as a fragment evaluated in the WordPress global
// scope, so no declare()/namespace. Echoes exactly one JSON object and nothing
// else.
//
// Belt-and-braces with the pack job's self-destruct timer: remove any
// kntnt-wp-skills-* working directory (outside-docroot temp base) or download
// directory (docroot) left behind by an aborted earlier run, so no stranded
// workspace — and no server-generated passphrase — outlives a crashed session.

// The two bases a pack ever writes to: the system temp dir and the docroot.
$bases   = [ sys_get_temp_dir(), rtrim( ABSPATH, '/' ) ];
$removed = [];

// Remove every leftover workspace under either base, recording what went.
foreach ( $bases as $base ) {
	foreach ( glob( $base . '/kntnt-wp-skills-*', GLOB_ONLYDIR ) as $dir ) {
		$iterator = new RecursiveIteratorIterator(
			new RecursiveDirectoryIterator( $dir, FilesystemIterator::SKIP_DOTS ),
			RecursiveIteratorIterator::CHILD_FIRST
		);
		foreach ( $iterator as $entry ) {
			$entry->isDir() ? rmdir( $entry->getPathname() ) : unlink( $entry->getPathname() );
		}
		if ( rmdir( $dir ) ) {
			$removed[] = $dir;
		}
	}
}

echo json_encode( [ 'removed' => $removed ] );
