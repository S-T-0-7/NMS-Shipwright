"""NMS save file read/write toolkit.

Handles the two save formats Hello Games has used:
  - Chunked + LZ4-block-compressed (older saves): a sequence of chunks,
    each prefixed by a 16-byte header (magic 0xFEEDA1E5, compressed size,
    uncompressed size, padding) followed by an LZ4 block.
  - Plain JSON (current-era saves): the file just starts with b'{"'.

And the save's obfuscated JSON keys (3-char codes) via the mapping.json
shipped by MBINCompiler releases (see data/mapping.json).
"""
