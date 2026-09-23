"""Deobfuscate / re-obfuscate save JSON keys using MBINCompiler's mapping.json.

NMS save files use 3-char obfuscated keys (e.g. "@Cs") instead of readable
field names (e.g. "ShipOwnership") to save space. The mapping is global and
1:1 in both directions (verified against data/mapping.json), so a full
round trip through deobfuscate() -> obfuscate() is lossless.
"""
from __future__ import annotations

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MAPPING_PATH = os.path.join(BASE_DIR, "data", "mapping.json")

_key_to_name: dict[str, str] | None = None
_name_to_key: dict[str, str] | None = None


def _load() -> None:
    global _key_to_name, _name_to_key
    if _key_to_name is not None:
        return

    with open(MAPPING_PATH, encoding="utf-8") as f:
        data = json.load(f)

    _key_to_name = {}
    _name_to_key = {}
    for entry in data["Mapping"]:
        key, name = entry["Key"], entry["Value"]
        _key_to_name[key] = name
        # first mapping wins if a name were ever duplicated (not observed)
        _name_to_key.setdefault(name, key)


def deobfuscate(obj):
    """Recursively rename obfuscated keys to readable names.

    Keys with no known mapping are left as-is (this happens for a handful
    of legitimately-short vanilla keys like "X"/"Y"/"Z" which the mapping
    itself maps *to*, not from -- see data/mapping.json).
    """
    _load()
    assert _key_to_name is not None

    if isinstance(obj, dict):
        return {
            _key_to_name.get(k, k): deobfuscate(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [deobfuscate(v) for v in obj]
    return obj


def obfuscate(obj):
    """Recursively rename readable keys back to obfuscated ones."""
    _load()
    assert _name_to_key is not None

    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            new_key = _name_to_key.get(k, k)
            result[new_key] = obfuscate(v)
        return result
    if isinstance(obj, list):
        return [obfuscate(v) for v in obj]
    return obj


# Legitimately-short *real* field names, confirmed by inspecting an actual
# deobfuscated save (they're 3 chars on their own merit, never obfuscated
# in the first place -- not a sign of a stale mapping). Every entry here
# was verified against a real save, not guessed.
#
# NOTE on why this list has to exist at all: after deobfuscate(), every
# leftover 3-char key is *by construction* absent from mapping.json's key
# set (deobfuscate() renames every key it has an entry for -- if a key
# survived, mapping.json has no entry for it, always). So "no mapping
# entry" can't distinguish a stale/missing obfuscation code from a name
# that was simply never obfuscated. This allowlist is the only way to
# separate the two, and it will need entries added if a newer save
# reports more of them.
KNOWN_UNOBFUSCATED_SHORT_KEYS = {"X", "Y", "Z", "W", "UID", "LID", "RID", "Fog", "FoV", "OWS", "USN", "PTK"}


def unmapped_keys(obj, found=None) -> set[str]:
    """Collect keys in a deobfuscated tree that are neither renamed by
    mapping.json nor a known-legitimate short name (KNOWN_UNOBFUSCATED_SHORT_KEYS).

    A non-empty result is a real signal worth checking: either
    data/mapping.json is stale for this save's game version (re-download
    it -- see README), or this is a new legitimate short key that should
    be added to KNOWN_UNOBFUSCATED_SHORT_KEYS.
    """
    if found is None:
        found = set()

    if isinstance(obj, dict):
        for k, v in obj.items():
            if len(k) == 3 and k not in KNOWN_UNOBFUSCATED_SHORT_KEYS:
                found.add(k)
            unmapped_keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            unmapped_keys(v, found)

    return found
