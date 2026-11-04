"""Which scenes draw a corvette module.

A module's row in the game's base-building table names only its placement scene, and that is
locators and collision with usually no mesh in it. The geometry sits beside it under
modules/parts, but under a name taken from the module's family rather than from the placement
scene, and the two disagree often enough that no rule gets from one to the other: the turret
is drawn by a gun, the landing gear by a leg. So the families are spelled out here and the
variant comes off the end of the module id.
"""
from __future__ import annotations

import functools
import glob
import json
import os

from nms_save import gamefiles, gamemeta
from nms_save.gamefiles import array, cstr, read, vstr

BIGGS = "models/common/spacecraft/biggs/"
HULL = "MODELS/COMMON/SPACECRAFT/BIGGS/BIGGS.SCENE.MBIN"

# family code off the module id -> the stems that draw it, {v} being the variant
FAMILIES = {
    "ALK": ["airlock_nesw_{v}"],
    "COK": ["cockpit_1x2_{v}"],
    "GEN": ["generator_{v}", "generator_1x1_{v}"],
    "HAB": ["hab_{v}_1x2_core"],
    "HAB1": ["hab_{v}_1x1_core"],
    "HAB2": ["hab_{v}_2x2_core"],
    "HOP": ["hopper_1x2_{v}"],
    "LND": ["landinggear_leg_{v}"],
    "SHL": ["shieldgenerator_{v}"],
    "TRU": ["backthruster_{v}", "thruster{v}"],
    "TUR": ["gun_{v}"],
    "WNG": ["wing_{v}_l", "wing_{v}_r"],      # a wing is a mirrored pair
}


@functools.lru_cache(maxsize=1)
def scene_index() -> dict:
    """{scene stem: scene path} for everything under the corvette's model tree.

    The parts are spread over several folders and a few sit at the tree root, so the archives
    are listed once and cached rather than guessing where each one lives.
    """
    stamp_file = os.path.join(gamefiles.CACHE, "biggs_scenes.json")
    banks = gamefiles.banks()
    paks = sorted(glob.glob(os.path.join(banks, "*.pak")))
    stamp = [len(paks), max((int(os.path.getmtime(p)) for p in paks), default=0)]
    try:
        with open(stamp_file) as f:
            held = json.load(f)
        if held.get("stamp") == stamp:
            return held["stems"]
    except (OSError, ValueError, KeyError):
        pass
    from hgpaktool import HGPAKFile
    stems = {}
    for pak in paks:
        try:
            with HGPAKFile(pak) as f:
                for name, _ in f.extract(filters=[BIGGS + "**.scene.mbin"]):
                    stem = os.path.basename(name).rsplit(".scene", 1)[0].lower()
                    stems.setdefault(stem, name.upper().replace("\\", "/"))
        except Exception:
            continue
    os.makedirs(gamefiles.CACHE, exist_ok=True)
    with open(stamp_file, "w") as f:
        json.dump({"stamp": stamp, "stems": stems}, f)
    return stems


@functools.lru_cache(maxsize=1)
def catalogue() -> dict:
    """{module id: {"placement", "style", "in_menu", "rotatable", "limit"}} for every corvette module."""
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "tables"),
                               ["metadata/reality/tables/basebuildingobjectstable*"], "NMSARC.Precache.pak")
    meta = gamemeta.exe_meta()
    table, row = meta.layout("cGcBaseBuildingTable"), meta.layout("cGcBaseBuildingEntry")
    b = read(os.path.join(folder, "basebuildingobjectstable.mbin"))
    base, n = array(b, 0x20 + table.off("Objects"))
    out = {}
    for k in range(n):
        o = base + k * row.size
        groups, count = array(b, o + row.off("Groups"))
        if not any(cstr(b, groups + j * 16, 16).startswith("BIGGS") for j in range(count)):
            continue
        out[cstr(b, o + row.off("ID"), 16)] = {
            "placement": vstr(b, o + row.off("PlacementScene")),
            "style": gamefiles.i32(b, o + row.off("Style")),
            "in_menu": bool(b[o + row.off("ShowInBuildMenu")]),
            "rotatable": bool(b[o + row.off("CanRotate3D")]),
            "limit": gamefiles.i32(b, o + row.off("CorvetteBaseLimit")),
        }
    return out


def _split(module_id: str):
    """B_HAB_D -> ("HAB", "D"); the hull and anything unfamiliar give no family."""
    bits = module_id.lstrip("^").split("_")
    if len(bits) < 3 or bits[0] != "B":
        return None, None
    return "_".join(bits[1:-1]), bits[-1]


def scenes_for(module_id: str) -> list[str]:
    """The scenes that draw one module, in the order they should be drawn.

    Empty when nothing is known to draw it, which the modeller treats as a module to leave out
    rather than an error.
    """
    bare = module_id.lstrip("^")
    if bare == "U_PARAGON":
        return [HULL]
    index = scene_index()
    family, variant = _split(bare)
    found = [index[s] for s in (t.format(v=variant.lower()) for t in FAMILIES.get(family or "", []))
             if s in index]
    if found:
        return found
    placement = (catalogue().get(bare) or {}).get("placement", "")
    if not placement:
        return []
    stem = os.path.basename(placement).rsplit(".SCENE", 1)[0].lower()
    plain = stem[:-len("_placement")] if stem.endswith("_placement") else stem
    for cand in (plain + "_core", plain, plain + "_exterior", stem):
        if cand in index:
            return [index[cand]]
    return []
