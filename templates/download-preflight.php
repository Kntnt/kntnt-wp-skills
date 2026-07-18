<?php
// Novamira execute-php payload — download preflight (health check step 5). INERT
// in this build: never run against a live site here (see templates/README.md).
// Sent as a fragment evaluated in the WordPress global scope, so no
// declare()/namespace. Echoes exactly one JSON object and nothing else.
//
// After this payload runs, the local side fetches the returned `url` with
// `curl -fsS` over HTTPS and asserts the body echoes back; then it removes the
// directory. This exercises permissions, extension rules, basic auth, and
// WAF/CDN behaviour before a multi-gigabyte pack — managed hosts 404 archive
// extensions, so the probe file is deliberately extension-less.

// Create a throwaway, random-named directory inside the docroot download base.
$token = 'kntnt-wp-skills-preflight-' . bin2hex( random_bytes( 8 ) );
$dir   = rtrim( ABSPATH, '/' ) . '/' . $token;
mkdir( $dir, 0755 );

// Write a tiny extension-less test file with a random body to fetch back.
$body = bin2hex( random_bytes( 16 ) );
$path = $dir . '/probe';
file_put_contents( $path, $body );

// Return the fetch URL and the paths the caller cleans up after the round-trip.
echo json_encode( [
	'url'           => home_url( '/' . $token . '/probe' ),
	'dir'           => $dir,
	'path'          => $path,
	'expected_body' => $body,
] );
