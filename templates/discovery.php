<?php
// Novamira execute-php payload — the single read-only discovery call (Discovery
// section). INERT in this build: never run against a live site here (see
// templates/README.md). Sent as a fragment evaluated in the WordPress global
// scope, so no declare()/namespace. Echoes exactly one JSON object — the raw
// `discovery` shape scripts/discovery.py parses — and nothing else.
//
// Read-only: this payload gathers facts, it never mutates production. The
// per-engine mass-send poised detection is the part most in need of runtime
// validation; the deterministic flip logic that consumes it lives, tested, in
// the helper.

global $wpdb;

// The recognised bulk-mail engines and the multilingual plugins are the only
// hard-coded slug sets; everything else is read from live state.
$recognised_mailers = [ 'fluentcrm', 'mailpoet', 'newsletter', 'mailchimp-for-wp', 'brevo' ];

// Resolve the WordPress paths and versions the document is anchored on.
$uploads      = wp_get_upload_dir();
$uploads_base = $uploads['basedir'];
$core_version = get_bloginfo( 'version' );

// Read the database server's identity — flavour, version, and default collation
// pin DDEV and avoid the MySQL-8-dump-into-MariaDB collation crash.
$db_version         = (string) $wpdb->get_var( 'SELECT VERSION()' );
$db_version_comment = (string) $wpdb->get_var( "SELECT @@version_comment" );
$db_collation       = (string) $wpdb->get_var( "SELECT @@collation_database" );

// Size the database: the grand total and the heaviest tables, for the report
// and the operator's sense of the transfer.
$table_rows = $wpdb->get_results(
	"SELECT table_name AS name, (data_length + index_length) AS size_bytes
	 FROM information_schema.tables
	 WHERE table_schema = DATABASE()
	 ORDER BY size_bytes DESC",
	ARRAY_A
);
$total_size = 0;
$top_tables = [];
foreach ( $table_rows as $row ) {
	$size        = (int) $row['size_bytes'];
	$total_size += $size;
	if ( count( $top_tables ) < 20 ) {
		$top_tables[] = [ 'name' => $row['name'], 'size_bytes' => $size ];
	}
}

// Confirm the content tables are InnoDB, so a single-transaction dump is safe on
// the live site (a MyISAM content table triggers the logged-caveat fallback).
$posts_engine          = $wpdb->get_var(
	$wpdb->prepare(
		"SELECT engine FROM information_schema.tables
		 WHERE table_schema = DATABASE() AND table_name = %s",
		$wpdb->posts
	)
);
$content_tables_innodb = ( 'InnoDB' === $posts_engine );

// Break the uploads tree down by top-level subdirectory, so a heavy gallery
// stands out. `du` needs exec, already proven by the health check.
$uploads_subdirectories = [];
foreach ( glob( $uploads_base . '/*', GLOB_ONLYDIR ) as $subdir ) {
	@exec( 'du -sb ' . escapeshellarg( $subdir ), $du_output, $du_status );
	$size                     = ( 0 === $du_status && $du_output ) ? (int) strtok( end( $du_output ), "\t" ) : 0;
	$uploads_subdirectories[] = [ 'path' => basename( $subdir ), 'size_bytes' => $size ];
	$du_output                = [];
}

// List the drop-ins present — the object-cache one is resolved by the ownership
// rule at pull, the rest inform the risk warning.
$dropins = [];
foreach ( [ 'object-cache.php', 'advanced-cache.php', 'db.php', 'db-error.php', 'maintenance.php' ] as $dropin ) {
	if ( file_exists( WP_CONTENT_DIR . '/' . $dropin ) ) {
		$dropins[] = $dropin;
	}
}

// Gather the attachment metadata the thumbnail exclude-set is later derived
// from: each attachment's original file and its registered generated sizes.
$attachment_rows = $wpdb->get_results(
	"SELECT p.ID AS id, f.meta_value AS file, m.meta_value AS metadata
	 FROM {$wpdb->posts} p
	 JOIN {$wpdb->postmeta} f ON f.post_id = p.ID AND f.meta_key = '_wp_attached_file'
	 LEFT JOIN {$wpdb->postmeta} m ON m.post_id = p.ID AND m.meta_key = '_wp_attachment_metadata'
	 WHERE p.post_type = 'attachment'",
	ARRAY_A
);
$attachments = [];
foreach ( $attachment_rows as $row ) {
	$metadata = $row['metadata'] ? maybe_unserialize( $row['metadata'] ) : [];
	$sizes    = [];
	if ( is_array( $metadata ) && ! empty( $metadata['sizes'] ) ) {
		foreach ( $metadata['sizes'] as $size ) {
			if ( ! empty( $size['file'] ) ) {
				$sizes[] = $size['file'];
			}
		}
	}
	$attachments[] = [ 'id' => (int) $row['id'], 'file' => $row['file'], 'sizes' => $sizes ];
}

// Probe the binaries the pack script needs, so a missing tool fails the health
// check rather than a half-finished dump.
$binaries = [];
foreach ( [ 'mysqldump', 'mysql', 'openssl', 'tar', 'gzip', 'sha256sum', 'nohup', 'bash' ] as $binary ) {
	@exec( 'command -v ' . escapeshellarg( $binary ), $probe_output, $probe_status );
	$binaries[ $binary ] = ( 0 === $probe_status );
	$probe_output        = [];
}

// Scan for a poised mass-send: for each recognised engine present, whether a
// campaign is queued or scheduled and how large its recipient list is. Only a
// poised campaign — never mere presence — is allowed to flip the mail default,
// a decision the helper makes; the payload only reports the facts.
$mass_send_engines = [];
$active_plugins    = (array) get_option( 'active_plugins', [] );
foreach ( $recognised_mailers as $engine ) {
	$present = false;
	foreach ( $active_plugins as $plugin ) {
		if ( str_starts_with( $plugin, $engine . '/' ) ) {
			$present = true;
			break;
		}
	}
	if ( ! $present ) {
		continue;
	}
	// Poised detection is engine-specific and validated at runtime; the
	// on-site senders (FluentCRM, MailPoet, Newsletter) query their campaign
	// tables, while the cloud senders (Mailchimp for WP, Brevo) never blast
	// from the local copy and so stay unposed here.
	$poised    = kntnt_wp_skills_scan_poised_campaign( $wpdb, $engine );
	$mass_send_engines[] = [
		'engine'             => $engine,
		'present'            => true,
		'queued_or_scheduled' => $poised['queued_or_scheduled'],
		'campaign'           => $poised['campaign'],
		'recipient_count'    => $poised['recipient_count'],
	];
}

// The unrecognised-mailer fallback: a generic signal (a scheduled sending cron
// plus a pending queue) that the helper surfaces without flipping.
$sending_cron = false;
foreach ( _get_cron_array() ?: [] as $events ) {
	foreach ( array_keys( $events ) as $hook ) {
		if ( preg_match( '/(send|mail|newsletter|campaign|queue)/i', $hook ) ) {
			$sending_cron = true;
			break 2;
		}
	}
}
$pending_queue_size = kntnt_wp_skills_pending_queue_size( $wpdb );

echo json_encode( [
	'home_url'               => home_url(),
	'site_url'               => site_url(),
	'root_path'              => ABSPATH,
	'content_path'           => WP_CONTENT_DIR,
	'uploads_base'           => $uploads_base,
	'core_version'           => $core_version,
	'php_version'            => phpversion(),
	'server_software'        => $_SERVER['SERVER_SOFTWARE'] ?? '',
	'disk_free_bytes'        => (int) disk_free_space( ABSPATH ),
	'root_writable'          => is_writable( ABSPATH ),
	'table_prefix'           => $wpdb->prefix,
	'database'               => [
		'version'               => $db_version,
		'version_comment'       => $db_version_comment,
		'default_collation'     => $db_collation,
		'total_size_bytes'      => $total_size,
		'top_tables'            => $top_tables,
		'content_tables_innodb' => $content_tables_innodb,
		// The password is deliberately omitted: it never enters model context
		// (safety rail 8). The helper strips it defensively even so.
		'connection'            => [
			'DB_HOST'    => defined( 'DB_HOST' ) ? DB_HOST : '',
			'DB_NAME'    => defined( 'DB_NAME' ) ? DB_NAME : '',
			'DB_USER'    => defined( 'DB_USER' ) ? DB_USER : '',
			'DB_CHARSET' => defined( 'DB_CHARSET' ) ? DB_CHARSET : '',
			'DB_COLLATE' => defined( 'DB_COLLATE' ) ? DB_COLLATE : '',
		],
	],
	'uploads_subdirectories' => $uploads_subdirectories,
	'active_plugins'         => array_values( $active_plugins ),
	'dropins'                => $dropins,
	'themes'                 => array_keys( wp_get_themes() ),
	'mass_send'              => [
		'engines'      => $mass_send_engines,
		'unrecognised' => [
			'sending_cron_scheduled' => $sending_cron,
			'pending_queue_size'     => $pending_queue_size,
		],
	],
	'attachments'            => $attachments,
	'binaries'               => $binaries,
] );

/**
 * Best-effort poised-campaign scan for one recognised engine. Runtime-validated:
 * the table names and statuses below are the well-known ones per engine, but a
 * given install may differ, so the caller treats a false as "not poised" rather
 * than "proven safe".
 *
 * @param wpdb   $wpdb   The WordPress database handle.
 * @param string $engine The recognised engine slug.
 * @return array{queued_or_scheduled: bool, campaign: ?string, recipient_count: int}
 */
function kntnt_wp_skills_scan_poised_campaign( $wpdb, $engine ) {
	$none = [ 'queued_or_scheduled' => false, 'campaign' => null, 'recipient_count' => 0 ];

	// FluentCRM keeps campaigns in fc_campaigns; a scheduled or working one with
	// recipients is poised.
	if ( 'fluentcrm' === $engine ) {
		$table = $wpdb->prefix . 'fc_campaigns';
		if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) {
			return $none;
		}
		$row = $wpdb->get_row(
			"SELECT title, recipients_count FROM {$table}
			 WHERE status IN ('scheduled','working') ORDER BY id DESC LIMIT 1",
			ARRAY_A
		);
		return $row
			? [ 'queued_or_scheduled' => true, 'campaign' => $row['title'], 'recipient_count' => (int) $row['recipients_count'] ]
			: $none;
	}

	// MailPoet keeps scheduled newsletters and a sending queue; a scheduled
	// newsletter with a queued task is poised.
	if ( 'mailpoet' === $engine ) {
		$table = $wpdb->prefix . 'mailpoet_newsletters';
		if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) {
			return $none;
		}
		$row = $wpdb->get_row(
			"SELECT subject FROM {$table} WHERE status = 'scheduled' ORDER BY id DESC LIMIT 1",
			ARRAY_A
		);
		return $row
			? [ 'queued_or_scheduled' => true, 'campaign' => $row['subject'], 'recipient_count' => 0 ]
			: $none;
	}

	// The Newsletter Plugin keeps emails; a scheduled one is poised.
	if ( 'newsletter' === $engine ) {
		$table = $wpdb->prefix . 'newsletter_emails';
		if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) {
			return $none;
		}
		$row = $wpdb->get_row(
			"SELECT subject, total FROM {$table} WHERE status = 'sending' ORDER BY id DESC LIMIT 1",
			ARRAY_A
		);
		return $row
			? [ 'queued_or_scheduled' => true, 'campaign' => $row['subject'], 'recipient_count' => (int) $row['total'] ]
			: $none;
	}

	// Mailchimp for WP and Brevo send from their cloud, never from this copy, so
	// they are never poised locally.
	return $none;
}

/**
 * Best-effort pending-queue size for the unrecognised-mailer fallback. Reads
 * Action Scheduler's pending count when present, else zero. Runtime-validated.
 *
 * @param wpdb $wpdb The WordPress database handle.
 * @return int The pending queue size, or zero when none is detectable.
 */
function kntnt_wp_skills_pending_queue_size( $wpdb ) {
	$table = $wpdb->prefix . 'actionscheduler_actions';
	if ( $wpdb->get_var( $wpdb->prepare( 'SHOW TABLES LIKE %s', $table ) ) !== $table ) {
		return 0;
	}
	return (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$table} WHERE status = 'pending'" );
}
