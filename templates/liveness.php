<?php
// Novamira execute-php payload — liveness probe (health check step 2). INERT in
// this build: never run against a live site here (see templates/README.md).
// Sent as a fragment evaluated in the WordPress global scope, so no
// declare()/namespace. Echoes exactly one JSON object and nothing else.

// Return the four facts the health check compares against the target URL to
// prove the channel is live — not merely connected — and points at the right
// site (the verify-targets-prod safety rail).
echo json_encode( [
	'home_url'        => home_url(),
	'abspath'         => ABSPATH,
	'php_version'     => phpversion(),
	'server_software' => $_SERVER['SERVER_SOFTWARE'] ?? '',
] );
