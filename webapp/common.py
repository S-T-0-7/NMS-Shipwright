"""Shared pieces the route modules use: paths, labels, opening and writing saves, the job list."""
from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from flask import request


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nms_procgen import ROOTS, textures  # noqa: E402
from nms_save import gamefiles, gamepath, gameversion, items, quests, save  # noqa: E402


STATIC = os.path.join(os.path.dirname(__file__), "static")


SHIP_LABELS = {"fighter": "Fighter", "hauler": "Hauler", "explorer": "Explorer", "shuttle": "Shuttle",
               "exotic": "Exotic", "living": "Living Ship", "solar": "Solar", "sentinel": "Sentinel",
               "freighter": "Freighter", "capital_freighter": "Capital Freighter"}


SHIP_MODELS = {k: "MODELS/" + v[len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
               for k, v in ROOTS.items() if k not in ("freighter", "capital_freighter")}


SPECIAL_SHIPS = {}
_special_dir = ROOT / "data" / "special_ships"
if _special_dir.exists():
    for _f in sorted(_special_dir.glob("*.json")):
        with open(_f, encoding="utf-8") as _sf:
            _entry = json.load(_sf)
        SPECIAL_SHIPS[_f.stem] = {"label": _entry.get("Name") or _f.stem, "entry": _entry}


with open(ROOT / "data" / "palettes" / "customisation.json") as _f:
    PALETTES = {k: v["colours"] for k, v in json.load(_f)["palettes"].items() if v["num_colours_enum"] == 5}

@functools.lru_cache(maxsize=None)
def part_names(ship):
    path = ROOT / "nms_procgen" / "names" / f"{ship}.json"
    names = {}
    if path.exists():
        for row in json.load(open(path)):
            names.setdefault(row["id"], row["name"])
    return names


def humanize(part_id):
    """Tidy a raw descriptor id into a readable label: _SUBWINGS_A3 -> 'Subwings A3',
    _WINGS_NONE -> 'Wings (none)'. The curated names in names/<ship>.json override this."""
    tokens = part_id.strip("_").split("_")
    if not tokens or not tokens[0]:
        return part_id
    group, rest = tokens[0].title(), "_".join(tokens[1:])
    if not rest:
        return group
    up = rest.upper()
    if up.startswith(("NULL", "NONE")):
        return f"{group} (none)"
    flag = ""
    if up.endswith("XNEVER"):
        rest, flag = rest[:-6], " (unused)"
    elif up.endswith("XRARE"):
        rest, flag = rest[:-5], " (rare)"
    return f"{group} {rest.title()}{flag}".strip()


def part_label(names, part_id):
    """Curated name if we have one, otherwise a tidied version of the raw id."""
    return names.get(part_id) or humanize(part_id)


def ship_alias(filename):
    base = os.path.basename(filename or "").lower().replace(".scene.mbin", ".descriptor.mbin")
    return next((alias for alias, rel in ROOTS.items() if rel.split("/")[-1] == base), None)


class GameRunning(RuntimeError):
    pass


def _running_by_snapshot(exe):
    """Is `exe` running, asked of Windows directly rather than by starting a program to ask.

    Walking the process list costs about a millisecond. Shelling out to tasklist costs two
    hundred, and the page asks every few seconds, so that was a fifth of a second of the
    machine's attention spent, over and over, on a question with a one-word answer.
    """
    import ctypes
    from ctypes import wintypes

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)       # TH32CS_SNAPPROCESS
    if snap == -1:
        raise OSError("no process snapshot")
    try:
        e = ENTRY()
        e.dwSize = ctypes.sizeof(ENTRY)
        found = k32.Process32First(snap, ctypes.byref(e))
        want = exe.lower().encode()
        while found:
            if e.szExeFile.lower() == want:
                return True
            found = k32.Process32Next(snap, ctypes.byref(e))
        return False
    finally:
        k32.CloseHandle(snap)


_RUNNING = [0.0, False]   # when it was last asked, and what the answer was


def game_running(fresh: bool = False):
    """Whether No Man's Sky is up. `fresh` skips the moment's grace before a write."""
    now = time.monotonic()
    if not fresh and now - _RUNNING[0] < 1.5:
        return _RUNNING[1]
    try:
        answer = _running_by_snapshot("NMS.exe")
    except Exception:   # not Windows, or the call was refused: fall back to asking the shell
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NMS.exe"], capture_output=True,
                                 text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            answer = "NMS.exe" in out
        except OSError:
            answer = False
    _RUNNING[0], _RUNNING[1] = now, answer
    return answer


def open_save(path):
    if not path or not os.path.exists(path):
        raise ValueError("Missing or invalid save path")
    return save.open_save(path)


def write(opened):
    # Asked afresh: the answer the page is showing may be a second or two old, and a second or
    # two is long enough to start the game in.
    if game_running(fresh=True):
        raise GameRunning("No Man's Sky is running -- quit the game first, or it will overwrite this change.")
    return opened.write()


def body():
    return request.get_json(force=True) or {}


def limit_seconds(b, default=120):
    """Seconds a search may run; None (or 0) means "keep going until I press Stop"."""
    v = b.get("seconds", default)
    if v in (None, 0, "", "0"):
        return None
    return max(5.0, min(float(v), 86400.0))


GAME_DATA_ERRORS = (gameversion.GameDataError, gamefiles.GameFileError, gamepath.GamePathError,
                    items.ItemError, quests.QuestDataError)


UPDATE_HINT = ("No Man's Sky looks different than expected -- it was probably updated. "
               "Open Save > Game data and press 'Re-read game files'. If that does not help, this part of "
               "the tool needs updating for the new game version.")


def model_filename(ship):
    if ship in SPECIAL_SHIPS:
        return SPECIAL_SHIPS[ship]["entry"]["Resource"]["Filename"]
    if ship not in SHIP_MODELS:
        raise ValueError(f"unknown ship type {ship!r}")
    return SHIP_MODELS[ship]


NO_SEED_LOOK = set()  # every scannable type's colour comes from its seed (sentinels included)


def parse_look(raw):
    look = {}
    for k in ("primary", "secondary", "undercoat"):
        v = [int(x) for x in (raw or {}).get(k) or []]
        if any(not 0 <= x < 64 for x in v):
            raise ValueError(f"{k} colour index must be 0-63")
        if v:
            look[k] = set(v)
    modes = [str(m).upper() for m in (raw or {}).get("mode") or []]
    if set(modes) - set(textures.mode_names()):
        raise ValueError(f"unknown hull finish; choose from {', '.join(textures.mode_names())}")
    if modes:
        look["mode"] = set(modes)
    return look

JOBS: dict[str, dict] = {}
