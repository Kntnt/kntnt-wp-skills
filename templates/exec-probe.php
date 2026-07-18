<?php
// Novamira execute-php payload — exec probe (health check step 4). INERT in this
// build: never run against a live site here (see templates/README.md). Sent as a
// fragment evaluated in the WordPress global scope, so no declare()/namespace.
// Echoes exactly one JSON object and nothing else.

// Probe process spawning independently of run-wp-cli, which proves nothing here
// (Novamira may run WP-CLI in-process). A working detached pack job needs exec,
// which managed hosts commonly disable — the whole point of failing early.
$exec_available = function_exists( 'exec' );

// A live round-trip is the real proof: function_exists can be true while
// disable_functions still neuters the call.
$roundtrip = '';
if ( $exec_available ) {
	@exec( 'printf ok', $output, $status );
	$roundtrip = ( 0 === $status ) ? implode( '', $output ) : '';
}

echo json_encode( [
	'exec_available'    => $exec_available && 'ok' === $roundtrip,
	'disable_functions' => (string) ini_get( 'disable_functions' ),
	'exec_roundtrip'    => $roundtrip,
] );
