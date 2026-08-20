<?php
/**
 * Plugin Name: Kntnt WP Skills — Mailpit capture
 * Description: Routes every outgoing message to DDEV's Mailpit so a local copy of a production site can never mail real people. Installed only when the transfer engine resolves the mail decision to capture.
 * Version: 1.0.0
 *
 * Dropped into wp-content/mu-plugins by the clone/pull engine's capture branch.
 * It short-circuits wp_mail at the highest possible priority — before any
 * plugin's own mailer runs — and delivers over SMTP to Mailpit. Because it
 * intercepts wp_mail itself rather than sendmail, it also captures API mailers
 * (Postmark, SendGrid, Brevo, …) that never touch the local MTA.
 *
 * @package Kntnt\Wp_Skills\Mailpit
 */

declare(strict_types=1);

namespace Kntnt\Wp_Skills\Mailpit;

use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\Exception as PHPMailerException;

// DDEV exposes Mailpit's SMTP endpoint here; the host runs unauthenticated.
const MAILPIT_HOST = '127.0.0.1';
const MAILPIT_PORT = 1025;

// PHP_INT_MIN wins the priority race against any mailer plugin, so capture
// happens before an API mailer can send. Two args: the short-circuit value and
// wp_mail's attributes.
add_filter( 'pre_wp_mail', __NAMESPACE__ . '\\capture', PHP_INT_MIN, 2 );

/**
 * Deliver a wp_mail call to Mailpit and short-circuit the real mailer.
 *
 * Returning a non-null value tells WordPress the mail was handled and stops
 * wp_mail before it constructs its own PHPMailer, so no plugin override runs.
 *
 * @param null|bool            $short_circuit The incoming short-circuit value; ignored.
 * @param array<string, mixed> $atts          wp_mail's arguments: to, subject, message, headers, attachments.
 * @return bool True when Mailpit accepted the message, false otherwise.
 */
function capture( ?bool $short_circuit, array $atts ): bool {

	// Ensure the bundled PHPMailer classes are loaded — pre_wp_mail can fire
	// before wp_mail would normally autoload them.
	if ( ! class_exists( PHPMailer::class ) ) {
		require_once ABSPATH . WPINC . '/PHPMailer/PHPMailer.php';
		require_once ABSPATH . WPINC . '/PHPMailer/SMTP.php';
		require_once ABSPATH . WPINC . '/PHPMailer/Exception.php';
	}

	// Normalise the recipient list, which wp_mail accepts as a string or an array.
	$to = $atts['to'] ?? [];
	if ( ! is_array( $to ) ) {
		$to = explode( ',', (string) $to );
	}

	// Point a fresh PHPMailer at Mailpit; no auth, no encryption — it is a
	// local sink that accepts everything.
	$mailer           = new PHPMailer( true );
	$mailer->isSMTP();
	$mailer->Host     = MAILPIT_HOST;
	$mailer->Port     = MAILPIT_PORT;
	$mailer->SMTPAuth = false;
	$mailer->CharSet  = 'UTF-8';

	// A sender is mandatory; derive the same default wp_mail would use.
	$sitename = wp_parse_url( network_home_url(), PHP_URL_HOST ) ?: 'localhost';
	$sitename = ltrim( strtolower( (string) $sitename ), 'w.' );
	$mailer->setFrom( "wordpress@{$sitename}", '', false );

	// Copy the message across, letting headers refine the defaults.
	$mailer->Subject = (string) ( $atts['subject'] ?? '' );
	$mailer->Body    = (string) ( $atts['message'] ?? '' );
	apply_message_headers( $mailer, $atts['headers'] ?? [] );

	// Attach recipients and any files, then hand off to Mailpit.
	foreach ( array_filter( array_map( 'trim', $to ) ) as $recipient ) {
		$mailer->addAddress( $recipient );
	}
	foreach ( (array) ( $atts['attachments'] ?? [] ) as $attachment ) {
		$mailer->addAttachment( (string) $attachment );
	}

	// A failed capture must not fall through to the real mailer, so swallow the
	// error and report a handled-but-unsent result.
	try {
		return $mailer->send();
	} catch ( PHPMailerException $exception ) {
		return false;
	}
}

/**
 * Apply the subset of wp_mail headers that change how a message is delivered.
 *
 * @param PHPMailer            $mailer  The mailer to configure.
 * @param string|array<string> $headers Raw headers, as a newline string or an array of lines.
 */
function apply_message_headers( PHPMailer $mailer, string|array $headers ): void {

	// Accept either wp_mail header form and reduce to individual lines.
	$lines = is_array( $headers ) ? $headers : explode( "\n", str_replace( "\r\n", "\n", $headers ) );

	// Dispatch each recognised header; anything else is passed through verbatim.
	foreach ( array_filter( array_map( 'trim', $lines ) ) as $line ) {
		if ( ! str_contains( $line, ':' ) ) {
			continue;
		}
		[ $name, $value ] = array_map( 'trim', explode( ':', $line, 2 ) );
		match ( strtolower( $name ) ) {
			'content-type' => $mailer->isHTML( str_contains( strtolower( $value ), 'text/html' ) ),
			'from'         => $mailer->setFrom( extract_address( $value ), extract_name( $value ), false ),
			'reply-to'     => $mailer->addReplyTo( extract_address( $value ), extract_name( $value ) ),
			'cc'           => $mailer->addCC( extract_address( $value ), extract_name( $value ) ),
			'bcc'          => $mailer->addBCC( extract_address( $value ), extract_name( $value ) ),
			default        => $mailer->addCustomHeader( $name, $value ),
		};
	}
}

/**
 * Extract the bare address from a ``Name <email>`` or plain ``email`` value.
 *
 * @param string $value The raw header value.
 * @return string The email address.
 */
function extract_address( string $value ): string {
	if ( preg_match( '/<([^>]+)>/', $value, $matches ) ) {
		return trim( $matches[1] );
	}
	return trim( $value );
}

/**
 * Extract the display name from a ``Name <email>`` value, empty when absent.
 *
 * @param string $value The raw header value.
 * @return string The display name, or an empty string.
 */
function extract_name( string $value ): string {
	if ( preg_match( '/^(.*?)<[^>]+>/', $value, $matches ) ) {
		return trim( $matches[1], " \t\"" );
	}
	return '';
}
