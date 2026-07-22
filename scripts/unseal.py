# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pynacl==1.5.0",
# ]
# ///
"""Open a Kntnt Extractor sealed container into an importable dump and its files.

This helper is the deterministic seam that replaces the retired pack/decrypt
machinery (ADR-0016, ADR-0017). An extraction's data comes down sealed to the
run's own ephemeral X25519 key pair, so the secret that opens it never leaves
this machine and a leaked artifact is useless without it. Three modes cover the
run's lifecycle:

- ``keygen`` generates the run's ephemeral key pair, writes the raw private key
  to a file (the public half is what ``POST /extractions`` carries), and prints
  only the base64 public key — the private key is never emitted into model
  context.
- ``unseal`` opens a downloaded ``KNTNTEXT`` container with that private key:
  each segment's symmetric key is unsealed (``crypto_box_seal_open``), each
  segment decrypted (``crypto_secretbox_open``), and the whole reassembled — the
  table dumps concatenated into one importable ``.sql`` with a connection-safe
  preamble the plugin's per-table DDL lacks, and each file written to disk by its
  installation-root-relative path.
- ``seal`` is a development/test aid that builds a container mirroring the
  plugin's PHP ``Sealed_Writer`` byte for byte, so the reader can be round-trip
  tested without the plugin. It is never used at run time.

Integrity is authenticated, not checksummed: a tampered or truncated container
fails the ``crypto_secretbox_open``/``crypto_box_seal_open`` and this helper
exits non-zero with a diagnostic on stderr, leaving no reassembled dump behind —
the bad transfer is caught before it can touch the local site.

## Wire format (from Kntnt Extractor ``Sealed_Writer``, FORMAT_VERSION 1)

```
MAGIC "KNTNTEXT" (8 bytes) | FORMAT_VERSION (1 byte)
repeated per segment, in order:
    sk_length   (8 bytes, unsigned 64-bit little-endian)
    sealed_key  (sk_length bytes, crypto_box_seal of the segment's secretbox key)
    nonce       (24 bytes, crypto_secretbox nonce)
    ct_length   (8 bytes, unsigned 64-bit little-endian)
    ciphertext  (ct_length bytes, crypto_secretbox output: 16-byte MAC || data)
trailer:
    sealed_index (crypto_box_seal of the length-prefixed name list)
    index_length (8 bytes, unsigned 64-bit little-endian)  <- the final 8 bytes
```

Segments are written full-data tables first (one each), then structure-only
tables (one DDL-only each), then files split into bounded parts sharing one
installation-root-relative name. The reader locates the sealed index from the
final 8 bytes, unseals the ordered names, walks the self-framed records, and
reassembles by name.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

from nacl.bindings import (
    crypto_box_PUBLICKEYBYTES,
    crypto_box_keypair,
    crypto_box_seal,
    crypto_box_seal_open,
    crypto_secretbox,
    crypto_secretbox_KEYBYTES,
    crypto_secretbox_NONCEBYTES,
    crypto_secretbox_open,
    randombytes,
)
from nacl.exceptions import CryptoError

# Container framing constants, fixed by the plugin's Sealed_Writer.
MAGIC = b"KNTNTEXT"
FORMAT_VERSION = 1
HEADER = MAGIC + bytes([FORMAT_VERSION])
# PHP pack('P') / unpack('P'): unsigned 64-bit, little-endian.
LENGTH_STRUCT = "<Q"
LENGTH_SIZE = 8

# The connection-safe preamble prepended to the reassembled dump. The plugin's
# per-table DDL is mysqldump-compatible but carries no global header, so import
# into DDEV needs the charset, foreign-key, and SQL-mode setup here (ADR-0017).
SQL_PREAMBLE = (
    "-- Reassembled by kntnt-wp-skills unseal.py from a Kntnt Extractor sealed container.\n"
    "-- The plugin's per-table DDL carries no global preamble; this makes it import cleanly.\n"
    "/*!40101 SET NAMES utf8mb4 */;\n"
    "SET @KNTNT_OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS;\n"
    "SET FOREIGN_KEY_CHECKS=0;\n"
    "SET @KNTNT_OLD_SQL_MODE=@@SQL_MODE;\n"
    "SET SQL_MODE='NO_AUTO_VALUE_ON_ZERO';\n"
    "\n"
)
SQL_TRAILER = (
    "\n"
    "SET FOREIGN_KEY_CHECKS=@KNTNT_OLD_FOREIGN_KEY_CHECKS;\n"
    "SET SQL_MODE=@KNTNT_OLD_SQL_MODE;\n"
)


class UnsealError(Exception):
    """A container is malformed, fails its authenticated open, or mismatches the
    expected selection — anything that must abort the reassembly loudly."""


def _pack_length(value: int) -> bytes:
    """Frame a length as the plugin's 8-byte little-endian prefix."""

    return struct.pack(LENGTH_STRUCT, value)


def _read_length(buffer: bytes, offset: int) -> tuple[int, int]:
    """Read an 8-byte length prefix at ``offset``; return it and the new offset."""

    end = offset + LENGTH_SIZE
    if end > len(buffer):
        raise UnsealError("Sealed container ends inside a length prefix.")
    (value,) = struct.unpack(LENGTH_STRUCT, buffer[offset:end])
    return value, end


def _take(buffer: bytes, offset: int, length: int) -> tuple[bytes, int]:
    """Slice ``length`` bytes at ``offset``, refusing to read past the end."""

    end = offset + length
    if length < 0 or end > len(buffer):
        raise UnsealError("Sealed container is truncated: a segment runs past its end.")
    return buffer[offset:end], end


# --- keygen -----------------------------------------------------------------


def run_keygen(config: dict[str, Any]) -> dict[str, Any]:
    """Generate the run's ephemeral X25519 key pair.

    Writes the raw 32-byte private key to ``private_key_path`` (mode 0600) and
    returns the base64 public key. The private key stays on disk between the
    ``POST /extractions`` and the later unseal; it is never returned here, so it
    cannot enter model context.
    """

    private_key_path = Path(config["private_key_path"])
    public_key, private_key = crypto_box_keypair()

    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    # Create restricted before writing so the secret is never briefly world-readable.
    fd = os.open(private_key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(private_key)

    return {"public_key": base64.b64encode(public_key).decode()}


# --- unseal -----------------------------------------------------------------


def _decode_index(payload: bytes) -> list[str]:
    """Decode the length-prefixed name list from the unsealed index payload."""

    names: list[str] = []
    offset = 0
    while offset < len(payload):
        length, offset = _read_length(payload, offset)
        raw, offset = _take(payload, offset, length)
        names.append(raw.decode("utf-8"))
    return names


def _parse_segments(container: bytes, public_key: bytes, private_key: bytes) -> list[tuple[str, bytes]]:
    """Validate the header, unseal the index, and decrypt every segment in order.

    Returns the ordered ``(name, plaintext)`` pairs. Raises ``UnsealError`` on any
    framing fault or authenticated-open failure — the container is never trusted
    past a byte that does not verify.
    """

    if not container.startswith(HEADER):
        raise UnsealError("Not a KNTNTEXT container, or an unsupported format version.")

    # The final 8 bytes frame the sealed index; unseal it for the ordered names.
    if len(container) < len(HEADER) + LENGTH_SIZE:
        raise UnsealError("Sealed container is too short to hold its trailer.")
    index_length, _ = _read_length(container, len(container) - LENGTH_SIZE)
    index_end = len(container) - LENGTH_SIZE
    index_start = index_end - index_length
    if index_start < len(HEADER):
        raise UnsealError("Sealed container's index overlaps its segment records.")
    sealed_index = container[index_start:index_end]
    try:
        names = _decode_index(crypto_box_seal_open(sealed_index, public_key, private_key))
    except CryptoError as error:
        raise UnsealError("Sealed container index failed to open — wrong key or corrupt.") from error

    # Walk the self-framed segment records between the header and the trailer.
    segments: list[tuple[str, bytes]] = []
    offset = len(HEADER)
    for name in names:
        sealed_key_length, offset = _read_length(container, offset)
        sealed_key, offset = _take(container, offset, sealed_key_length)
        nonce, offset = _take(container, offset, crypto_secretbox_NONCEBYTES)
        ciphertext_length, offset = _read_length(container, offset)
        ciphertext, offset = _take(container, offset, ciphertext_length)
        try:
            key = crypto_box_seal_open(sealed_key, public_key, private_key)
            plaintext = crypto_secretbox_open(ciphertext, nonce, key)
        except CryptoError as error:
            raise UnsealError(f"Segment '{name}' failed its authenticated open — corrupt or truncated.") from error
        segments.append((name, plaintext))

    if offset != index_start:
        raise UnsealError("Sealed container has trailing bytes between its segments and index.")

    return segments


def _validate_selection(names: list[str], tables: list[str], structure_only: list[str], files: list[str]) -> None:
    """Confirm the container's ordered names match the expected selection.

    Tables come first (one segment each), then structure-only tables, then the
    file parts whose distinct names, in first-appearance order, are the file set.
    A mismatch means the container is not what this run asked for, so it is
    refused rather than reassembled into the wrong thing.
    """

    table_count = len(tables) + len(structure_only)
    if names[:len(tables)] != tables:
        raise UnsealError("Container's full-data table segments do not match the requested tables.")
    if names[len(tables):table_count] != structure_only:
        raise UnsealError("Container's structure-only segments do not match the requested tables.")

    distinct_files: list[str] = []
    for name in names[table_count:]:
        if name not in distinct_files:
            distinct_files.append(name)
    if distinct_files != files:
        raise UnsealError("Container's file segments do not match the requested files.")


def _safe_destination(files_root: Path, name: str) -> Path:
    """Resolve ``name`` under ``files_root``, refusing any path that escapes it."""

    if name.startswith("/") or ".." in Path(name).parts:
        raise UnsealError(f"File segment '{name}' is not a safe relative path.")
    destination = (files_root / name).resolve()
    root = files_root.resolve()
    if root != destination and root not in destination.parents:
        raise UnsealError(f"File segment '{name}' resolves outside the files root.")
    return destination


def run_unseal(config: dict[str, Any]) -> dict[str, Any]:
    """Open a downloaded container into the reassembled dump and its files.

    Nothing is written until every segment has decrypted and the selection has
    validated, so a container that fails anywhere leaves no partial dump behind.
    """

    container_path = Path(config["container_path"])
    private_key_path = Path(config["private_key_path"])
    sql_path = Path(config["sql_path"])
    files_root = Path(config["files_root"])
    tables: list[str] = config.get("tables", [])
    structure_only: list[str] = config.get("structure_only", [])
    files: list[str] = config.get("files", [])

    private_key = private_key_path.read_bytes()
    if len(private_key) != crypto_box_PUBLICKEYBYTES:
        raise UnsealError("The run's private key is not a 32-byte X25519 secret key.")
    # Recover the matching public key so both halves of the seal are available;
    # crypto_box_seal_open needs the public key alongside the private one.
    public_key = _public_from_private(private_key)

    container = container_path.read_bytes()
    segments = _parse_segments(container, public_key, private_key)
    _validate_selection([name for name, _ in segments], tables, structure_only, files)

    table_count = len(tables) + len(structure_only)

    # Reassemble the dump: preamble, every table segment in order, trailer.
    sql_parts = [SQL_PREAMBLE]
    for _, plaintext in segments[:table_count]:
        text = plaintext.decode("utf-8")
        sql_parts.append(text if text.endswith("\n") else text + "\n")
    sql_parts.append(SQL_TRAILER)

    # Group consecutive same-named file parts and write each file whole.
    file_bytes: dict[str, bytearray] = {}
    file_order: list[str] = []
    for name, plaintext in segments[table_count:]:
        if name not in file_bytes:
            file_bytes[name] = bytearray()
            file_order.append(name)
        file_bytes[name].extend(plaintext)

    # Resolve every destination up front so a hostile path aborts before any write.
    destinations = {name: _safe_destination(files_root, name) for name in file_order}

    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text("".join(sql_parts), encoding="utf-8")

    for name in file_order:
        destination = destinations[name]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bytes(file_bytes[name]))

    return {
        "sql_path": str(sql_path),
        "tables_written": len(tables),
        "structure_only_written": len(structure_only),
        "files_written": len(file_order),
        "bytes_sql": sql_path.stat().st_size,
    }


def _public_from_private(private_key: bytes) -> bytes:
    """Derive the X25519 public key from a raw private key."""

    from nacl.bindings import crypto_scalarmult_base

    public = crypto_scalarmult_base(private_key)
    if len(public) != crypto_box_PUBLICKEYBYTES:
        raise UnsealError("Derived public key has the wrong length.")
    return public


# --- seal (development / test aid) ------------------------------------------


def run_seal(config: dict[str, Any]) -> dict[str, Any]:
    """Build a container mirroring the plugin's ``Sealed_Writer`` (dev/test only).

    Not used at run time — the plugin seals in production. It exists so the reader
    can be round-trip tested against the exact documented wire format.
    """

    container_path = Path(config["container_path"])
    public_key = base64.b64decode(config["public_key"])
    segments: list[dict[str, str]] = config["segments"]

    body = bytearray(HEADER)
    names: list[str] = []
    for segment in segments:
        name = segment["name"]
        plaintext = base64.b64decode(segment["data"])
        key = randombytes(crypto_secretbox_KEYBYTES)
        nonce = randombytes(crypto_secretbox_NONCEBYTES)
        ciphertext = crypto_secretbox(plaintext, nonce, key)
        sealed_key = crypto_box_seal(key, public_key)
        body += _pack_length(len(sealed_key)) + sealed_key + nonce + _pack_length(len(ciphertext)) + ciphertext
        names.append(name)

    index = b"".join(_pack_length(len(name.encode())) + name.encode() for name in names)
    sealed_index = crypto_box_seal(index, public_key)
    body += sealed_index + _pack_length(len(sealed_index))

    container_path.parent.mkdir(parents=True, exist_ok=True)
    container_path.write_bytes(bytes(body))
    return {"container_path": str(container_path), "segments_written": len(segments)}


MODES = {"keygen": run_keygen, "unseal": run_unseal, "seal": run_seal}


def main() -> int:
    """Dispatch on the mode argument; read config JSON from stdin, emit result JSON."""

    if len(sys.argv) != 2 or sys.argv[1] not in MODES:
        sys.stderr.write(f"usage: unseal.py {{{'|'.join(MODES)}}} < config.json\n")
        return 2

    try:
        config = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        sys.stderr.write(f"unseal.py: invalid JSON on stdin: {error}\n")
        return 2

    try:
        result = MODES[sys.argv[1]](config)
    except (UnsealError, KeyError, OSError, ValueError) as error:
        sys.stderr.write(f"unseal.py: {error}\n")
        return 1

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
