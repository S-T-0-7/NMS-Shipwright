"""Corvette layouts: the modules bolted onto a player's ship.

A corvette is stored as a base, not as a ship -- one PersistentPlayerBases entry of type
PlayerShipBase, holding one object per module. Each object is a free transform: a position
and two orientation vectors, with no snapping, attachment or ordering data recorded. The
build menu's restrictions (what may sit where, how many, which way round) are checked while
building and never re-checked when a save is loaded, so a module written here can stand
anywhere, at any angle, bolted to nothing.

Saves come in pairs -- a slot's manual save and its autosave -- and the game decides for
itself which half to read, so an edit goes into both (see write_both).
"""
from __future__ import annotations

import math
import os
import re

from . import save

SHIP_BASE = "PlayerShipBase"
HULL = "^U_PARAGON"
GRID = (6.0, 3.0, 6.0)   # what the build menu snaps to, along x, y and z
MODULE_USER_DATA = 99    # every module carries this; only the hull differs


def layouts(readable: dict) -> list[dict]:
    """Every corvette in a readable save, outermost-first."""
    bases = (readable.get("BaseContext") or {}).get("PlayerStateData", {}).get("PersistentPlayerBases") or []
    return [b for b in bases if (b.get("BaseType") or {}).get("PersistentBaseTypes") == SHIP_BASE]


def modules(entry: dict) -> list[dict]:
    """The modules of one corvette, hull first, as the save stores them."""
    return entry.get("Objects") or []


def _axes(yaw: float | None, up, at):
    if yaw is None:
        return list(up), list(at)
    a = math.radians(yaw)
    return list(up), [math.sin(a), 0.0, math.cos(a)]


def place(entry: dict, part_id: str, position, *, yaw: float | None = None,
          up=(0.0, 1.0, 0.0), at=(0.0, 0.0, 1.0), user_data: int = MODULE_USER_DATA) -> dict:
    """Add a module at `position`, turned `yaw` degrees about the vertical if given.

    Nothing here is checked against the build menu's rules: that is the point.
    """
    objs = entry.setdefault("Objects", [])
    u, a = _axes(yaw, up, at)
    obj = {"Timestamp": max((o.get("Timestamp", 0) for o in objs), default=0) + 1,
           "ObjectID": part_id if part_id.startswith("^") else "^" + part_id,
           "UserData": user_data, "Position": [float(x) for x in position], "Up": u, "At": a}
    objs.append(obj)
    return obj


def move(obj: dict, position=None, *, yaw: float | None = None, up=None, at=None) -> dict:
    """Put one module somewhere else, or turn it, or both."""
    if position is not None:
        obj["Position"] = [float(x) for x in position]
    if up is not None:
        obj["Up"] = [float(x) for x in up]
    if at is not None:
        obj["At"] = [float(x) for x in at]
    if yaw is not None:
        obj["Up"], obj["At"] = _axes(yaw, obj.get("Up", (0.0, 1.0, 0.0)), obj.get("At", (0.0, 0.0, 1.0)))
    return obj


def remove(entry: dict, obj: dict) -> None:
    """Take a module off the ship. The hull is not a module and cannot go."""
    if obj.get("ObjectID") == HULL:
        raise ValueError("the hull cannot be removed")
    (entry.get("Objects") or []).remove(obj)


def _slot_index(name: str) -> int | None:
    m = re.fullmatch(r"save(\d*)\.hg", name, re.I)
    return None if not m else int(m.group(1) or 1)


def halves(path: str) -> list[str]:
    """Both save files of the slot `path` belongs to, the given one first.

    A slot keeps a manual save on the odd file and its autosave on the even one. Only files
    that exist are returned, so a half the game has not written yet is left alone.
    """
    folder, name = os.path.dirname(path), os.path.basename(path)
    i = _slot_index(name)
    if i is None:
        return [path]
    other = i + 1 if i % 2 else i - 1
    sibling = os.path.join(folder, "save.hg" if other == 1 else "save%d.hg" % other)
    return [path] + ([sibling] if other >= 1 and os.path.exists(sibling) else [])


def write_both(path: str, mutate, *, backup: bool = True) -> list[str]:
    """Apply `mutate(readable)` to every half of the slot and write them.

    The game picks a half to read on its own, so editing one and not the other looks exactly
    like the game rejecting the edit. Returns the files written.
    """
    written = []
    for p in halves(path):
        opened = save.open_save(p)
        mutate(opened.readable)
        opened.write(backup=backup)
        written.append(p)
    return written
