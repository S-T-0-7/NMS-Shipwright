"""Which model each SystemShips entry uses (freighters, frigates, pirates, police...).

Game data METADATA/SIMULATION/SPACE/AISPACESHIPMANAGER.MBIN holds six role lists
(frigates, traders, pirates, police, -, swarm) of model ids and 30 model records
{id, filename, type, class, subtype}. NMS.exe (0x141710310) shuffles the entry's
role list with an MWC seeded by the entry's seed (Fisher-Yates) and takes the
first record with type == entry.ai-type and class == entry.class (frigates, type
6, must also match the subtype).

Verified on the player's pirate freighter: entry 43 of system 139 (role 2, type 3)
-> FREIGHTER_CAPITAL_PIRATE = PIRATEFREIGHTER.SCENE.MBIN, seed 0x902962A6264EDD02.
"""
from __future__ import annotations

import os
import struct
from functools import lru_cache

from .emu import extract_metadata

K, M32 = 0x5A76F899, 0xFFFFFFFF
ROLES = ["frigate", "trader", "pirate", "police", "unused", "swarm"]
# procedural models -> ship alias of the part generator (others have a fixed look)
MODEL_ALIAS = {"FIGHTER_PROC": "fighter", "DROPSHIP_PROC": "hauler", "SCIENTIFIC_PROC": "explorer",
               "SHUTTLE_PROC": "shuttle", "S-CLASS_PROC": "exotic", "BIOSHIP_PROC": "living",
               "SAILSHIP_PROC": "solar", "SENTINELSHIP_PROC": "sentinel", "FREIGHTER_PROC": "freighter",
               "CAPITALFREIGHTER_PROC": "capital_freighter"}


@lru_cache(maxsize=1)
def table():
    """(role lists of ids, {id: record})."""
    b = open(os.path.join(extract_metadata(), "aispaceshipmanager.mbin"), "rb").read()
    d = 0x20

    def arr(h):
        rel, cnt = struct.unpack_from("<qI", b, d + h)
        return (h + rel if cnt else 0), cnt

    def name(o):
        return b[d + o:d + o + 0x20].split(b"\0")[0].decode(errors="replace")

    roles = []
    for r in range(6):
        off, cnt = arr(0x10 * r)
        roles.append([name(off + 0x20 * i) for i in range(cnt)])
    off, cnt = arr(0x60)
    records = {}
    for i in range(cnt):
        o = off + 0x40 * i
        foff, flen = arr(o + 0x20)
        filename = b[d + foff:d + foff + flen].split(b"\0")[0].decode(errors="replace") if flen else ""
        typ, cls, sub, _ = struct.unpack_from("<4i", b, d + o + 0x30)
        base = os.path.basename(filename).upper().replace(".SCENE.MBIN", "")
        records[name(o)] = {"id": name(o), "filename": filename, "model": base, "type": typ, "class": cls,
                            "subtype": sub, "alias": MODEL_ALIAS.get(base)}
    return roles, records


def pick(role: int, ai: int, cls: int, subtype: int, seed: int) -> dict | None:
    """The model record the game uses for a SystemShips entry."""
    roles, records = table()
    ids = roles[role] if 0 <= role < len(roles) else []
    order = list(range(len(ids)))
    lo, hi = seed & M32, seed >> 32
    s0, s1 = (lo or 1), (((lo << 16) | (lo >> 16)) & M32) ^ hi ^ lo
    for i in range(len(ids) - 1, 0, -1):
        t = s0 * K + s1
        s0, s1 = t & M32, t >> 32
        j = (s0 * (i + 1)) >> 32
        order[i], order[j] = order[j], order[i]
    for k in order:
        r = records.get(ids[k])
        if r and r["type"] == ai and r["class"] == cls and (r["subtype"] == subtype or r["type"] != 6):
            return r
    return None
