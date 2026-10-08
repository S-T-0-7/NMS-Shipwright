"""Shared pieces the route modules use: paths, labels, opening and writing saves, the job list."""
from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
from pathlib import Path

from flask import request


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nms_procgen import ROOTS  # noqa: E402
from nms_save import gamefiles, gamepath, gameversion, items, quests, save  # noqa: E402


STATIC = os.path.join(os.path.dirname(__file__), "static")


SHIP_LABELS = {"fighter": "Fighter", "hauler": "Hauler", "explorer": "Explorer", "shuttle": "Shuttle",
               "exotic": "Exotic", "living": "Living Ship", "solar": "Solar", "sentinel": "Sentinel",
               "freighter": "Freighter", "capital_freighter": "Capital Freighter"}


SHIP_MODELS = {k: "MODELS/" + v[len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
               for k, v in ROOTS.items() if k not in ("freighter", "capital_freighter")}


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
    _WINGS_NONE -> 'Wings (none)'. Just formatting, not a shape description -- the curated
    names in names/<ship>.json (sentinel, fighter) override this."""
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


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NMS.exe"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except OSError:
        return False
    return "NMS.exe" in out


def open_save(path):
    if not path or not os.path.exists(path):
        raise ValueError("Missing or invalid save path")
    return save.open_save(path)


def write(opened):
    if game_running():
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
    if ship not in SHIP_MODELS:
        raise ValueError(f"unknown ship type {ship!r}")
    return SHIP_MODELS[ship]


NO_SEED_LOOK = {"sentinel"}  # sentinel colour comes from its parts and the player's paint, not the seed


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
