"""Quests (missions) in a save: list them by name and skip whole quests.

How the game decides a quest is finished (NMS.exe mission manager):
  * IsMissionComplete: Progress >= the quest's stage count.
  * IsMissionInProgress: 0 <= Progress < stage count.
  * Progress -1 means the quest has not started.
The stage count for the save's MissionVersion is the quest's FinalStageVersions
entry in METADATA/SIMULATION/MISSIONS/TABLES/*.MBIN. A quest the player
finished normally keeps exactly that number, so skipping writes the same value.

Field offsets come from NMS.exe's reflection data (gamemeta), and every file is
checked against the exe's layout guid, so a game update can't make us misread.
"""
from __future__ import annotations

import functools
import glob
import os
import re

from . import gamefiles, gamemeta
from .gamefiles import array as _array, cstr as _cstr, i32 as _i32, read as _read, vstr as _vss

CACHE = gamefiles.CACHE

PLAYER_PATH = ("BaseContext", "PlayerStateData")
NOT_STARTED = -1
UNKNOWN_FINAL = 2 ** 31 - 1  # the game itself stores this for some finished quests (e.g. SENTINEL_CRASH)
ID_RE = re.compile(r"[A-Za-z0-9_?]+\Z")
_MARKUP = re.compile(r"<[^>]*>")


class QuestDataError(RuntimeError):
    pass


# ---------------------------------------------------------------- game data --

def _extract_or_fail(dest, patterns, first_pak):
    try:
        return gamefiles.extract(dest, patterns, first_pak)
    except gamefiles.GameFileError as e:
        raise QuestDataError(str(e)) from None


def _layouts():
    try:
        m = gamemeta.exe_meta()
        table = m.layout("cGcMissionTable")
        seq = m.element(table, "Missions")
        return {"table": table, "seq": seq, "final": m.element(seq, "FinalStageVersions"),
                "loc_table": m.layout("cTkLocalisationTable"),
                "loc": m.element(m.layout("cTkLocalisationTable"), "Table")}
    except gamemeta.MetaError as e:
        raise QuestDataError(str(e)) from None


def _no_match(what):
    return QuestDataError(f"The game's {what} don't match NMS.exe. If Steam is still updating No Man's Sky, "
                          "let it finish (or verify the game files) and try again.")


@functools.lru_cache(maxsize=None)
def missions():
    """{mission id: {"title_key", "title_count", "final": [(progress, version)], ...}} from the game."""
    L = _layouts()
    table, seq, fin = L["table"], L["seq"], L["final"]
    o_id, id_len = seq.off("MissionID"), seq.fields["MissionID"]["size"]
    o_titles, o_final = seq.off("MissionTitles"), seq.off("FinalStageVersions")
    o_flags = [seq.off(f) for f in ("IsRecurring", "RestartOnCompletion")]
    o_critical = seq.off("MissionIsCritical")
    f_progress, f_version = fin.off("Progress"), fin.off("Version")
    folder = _extract_or_fail(os.path.join(CACHE, "missions"), ["metadata/simulation/missions/tables/*.mbin"],
                              "NMSARC.Precache.pak")
    out, files = {}, 0
    for path in sorted(glob.glob(os.path.join(folder, "*.mbin"))):
        b = _read(path)
        if not table.matches(b):
            continue
        files += 1
        base, count = _array(b, 0x20 + table.off("Missions"))
        for i in range(count):
            r = base + i * seq.size
            mid = _cstr(b, r + o_id, id_len)
            if not ID_RE.match(mid):
                raise QuestDataError(f"Unexpected quest record in {os.path.basename(path)}")
            fb, fc = _array(b, r + o_final)
            out[mid] = {
                "table": os.path.basename(path)[:-5],
                "title_key": _vss(b, r + o_titles),
                "title_count": _i32(b, r + o_titles + 0x10),
                "final": [(_i32(b, fb + k * fin.size + f_progress), _i32(b, fb + k * fin.size + f_version))
                          for k in range(fc)],
                "critical": bool(b[r + o_critical]),
                "recurring": any(b[r + o] for o in o_flags),
            }
    if not files or "ACT1_STEP1" not in out:
        raise _no_match("quest tables")
    return out


@functools.lru_cache(maxsize=None)
def strings():
    """English text for localisation ids."""
    L = _layouts()
    table, loc = L["loc_table"], L["loc"]
    o_id, id_len, o_en = loc.off("Id"), loc.fields["Id"]["size"], loc.off("English")
    folder = _extract_or_fail(os.path.join(CACHE, "language"), ["language/nms_*_english.mbin"], "NMSARC.MetadataEtc.pak")
    out = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.mbin"))):
        b = _read(path)
        if not table.matches(b):
            continue
        base, count = _array(b, 0x20 + table.off("Table"))
        for i in range(count):
            e = base + i * loc.size
            text = _vss(b, e + o_en, "utf-8")
            if text:
                out.setdefault(_cstr(b, e + o_id, id_len), text)
    if not out:
        raise _no_match("language files")
    return out


def final_stage(mission_id, version):
    """Progress value a finished quest has at this mission version, or None if unknown."""
    info = missions().get(mission_id)
    if not info or not info["final"]:
        return None
    best = None
    for progress, ver in info["final"]:
        if ver <= version and (best is None or ver >= best[1]):
            best = (progress, ver)
    return (best or max(info["final"], key=lambda p: p[1]))[0]


def game_title(mission_id):
    """The quest's name as the game shows it, or "" for internal helper quests."""
    info = missions().get(mission_id)
    key = info["title_key"] if info else ""
    if key and info["title_count"] > 1:
        key = key.replace("%d", "1")
    text = _MARKUP.sub("", strings().get(key, "")).strip() if key else ""
    return "" if "%" in text else text


def title(mission_id):
    return game_title(mission_id) or mission_id.replace("_", " ").title()


# --------------------------------------------------------------- save edits --

def _state(readable):
    return readable[PLAYER_PATH[0]][PLAYER_PATH[1]]


def _key(entry):
    return f"{entry.get('Mission', '^')[1:]}|{entry.get('Seed', 0)}"


def _status(progress, final):
    if progress < 0:
        return "not_started"
    if final is None:
        return "done" if progress == UNKNOWN_FINAL else "unknown"
    return "done" if progress >= final else "in_progress"


def list_quests(readable):
    """Every quest the save knows about (one row per quest), in save order."""
    state = _state(readable)
    version = int(state.get("MissionVersion", 0))
    current = state.get("CurrentMissionID", "^")[1:]
    rows = {}
    for entry in state.get("MissionProgress", []):
        mid = entry.get("Mission", "^")[1:]
        if not mid:
            continue
        key, progress = _key(entry), int(entry.get("Progress", NOT_STARTED))
        if key in rows:  # the save can hold a quest twice; show the least finished copy
            rows[key]["progress"] = min(rows[key]["progress"], progress)
            rows[key]["status"] = _status(rows[key]["progress"], rows[key]["final"])
            continue
        info = missions().get(mid) or {}
        final = final_stage(mid, version)
        rows[key] = {
            "key": key, "id": mid, "seed": entry.get("Seed", 0), "title": title(mid), "named": bool(game_title(mid)),
            "group": info.get("title_key") or mid, "progress": progress, "final": final,
            "status": _status(progress, final), "current": mid == current, "known": bool(info),
            "recurring": bool(info.get("recurring")), "critical": bool(info.get("critical")),
        }
    return list(rows.values())


def skip_quests(readable, keys):
    """Mark the given quests (keys from list_quests) finished. Returns what changed."""
    state = _state(readable)
    version = int(state.get("MissionVersion", 0))
    wanted = set(keys)
    if not wanted:
        raise ValueError("No quests selected")
    entries = state.get("MissionProgress", [])
    missing = sorted(wanted - {_key(e) for e in entries})
    if missing:
        raise ValueError(f"Quest not in this save: {missing[0].split('|')[0]}")
    changed = {}
    for entry in entries:
        key = _key(entry)
        if key not in wanted:
            continue
        mid = entry["Mission"][1:]
        final = final_stage(mid, version)
        target = UNKNOWN_FINAL if final is None else final
        before = int(entry.get("Progress", NOT_STARTED))
        if before >= target:
            continue
        entry["Progress"] = target
        changed.setdefault(key, {"key": key, "id": mid, "title": title(mid), "from": before, "to": target})
    current = state.get("CurrentMissionID", "^")[1:]
    if current and any(c["id"] == current for c in changed.values()):
        state["CurrentMissionID"] = "^"
        state["CurrentMissionSeed"] = 0
    return list(changed.values())
