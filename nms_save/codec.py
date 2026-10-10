"""Low-level decode/encode for .hg save files.

Format reference (verified against community tools -- Chase-san's NMS save
gists, NMSCD/NMS-Save-Decoder -- and confirmed against real save files):

Chunked format:
    repeat until EOF:
        uint32 LE  magic             (must be 0xFEEDA1E5)
        uint32 LE  compressed_size
        uint32 LE  uncompressed_size
        uint32 LE  padding (unused, always 0)
        bytes[compressed_size]  LZ4 block (store_size=False)

Plain format (current-era saves):
    The file *is* the JSON text directly (starts with b'{"').

We always round-trip in whichever format the source file was in, so we
never silently change a save's on-disk shape.
"""
from __future__ import annotations

import io
import struct

import lz4.block

MAGIC = 0xFEEDA1E5
CHUNK_SIZE = 0x80000  # 524288 bytes, matches the game's own chunking


class SaveFormatError(ValueError):
    pass


def _read_uint32(stream: io.BytesIO) -> int:
    data = stream.read(4)
    if len(data) != 4:
        raise SaveFormatError("Unexpected end of file while reading chunk header")
    return struct.unpack("<I", data)[0]


def is_chunked(raw: bytes) -> bool:
    """True if this looks like the LZ4-chunked format, False if plain JSON."""
    if len(raw) < 2:
        raise SaveFormatError("File too small to be a save file")
    return not (raw[0:1] == b"{" and raw[1:2] == b'"')


def decode(raw: bytes) -> tuple[str, bool, int]:
    """Decode raw save bytes to JSON text.

    Returns (json_text, was_chunked, trailing_nul_count). The game
    null-terminates the JSON blob (usually a single trailing 0x00 byte);
    we strip it so json.loads() works, and hand the count back so
    encode() can reproduce it exactly.
    """
    if not is_chunked(raw):
        stripped = raw.rstrip(b"\x00")
        return stripped.decode("utf-8", "surrogateescape"), False, len(raw) - len(stripped)

    stream = io.BytesIO(raw)
    size = len(raw)
    out = bytearray()

    while stream.tell() < size:
        magic = _read_uint32(stream)
        if magic != MAGIC:
            raise SaveFormatError(
                f"Bad chunk magic 0x{magic:08x} at offset {stream.tell() - 4}; "
                "file is not a recognized NMS save"
            )
        compressed_size = _read_uint32(stream)
        uncompressed_size = _read_uint32(stream)
        _read_uint32(stream)  # padding, unused

        block = stream.read(compressed_size)
        if len(block) != compressed_size:
            raise SaveFormatError("Truncated chunk body")

        out += lz4.block.decompress(block, uncompressed_size=uncompressed_size)

    stripped = bytes(out).rstrip(b"\x00")
    return stripped.decode("utf-8", "surrogateescape"), True, len(out) - len(stripped)


def encode(json_text: str, chunked: bool, trailing_nul_count: int = 1) -> bytes:
    """Encode JSON text back to raw save bytes in the requested shape."""
    data = json_text.encode("utf-8", "surrogateescape") + b"\x00" * trailing_nul_count

    if not chunked:
        return data

    out = bytearray()
    size = len(data)
    offset = 0
    while offset < size:
        piece = data[offset : offset + CHUNK_SIZE]
        offset += len(piece)
        block = lz4.block.compress(piece, store_size=False)
        out += struct.pack("<IIII", MAGIC, len(block), len(piece), 0)
        out += block

    return bytes(out)
