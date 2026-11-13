"""Which scenes draw a corvette module.

A module's row in the base-building table names only its placement scene, and that is locators
and collision with no mesh in it. The model comes from a second table: basebuildingpartstable
holds one part per shape, each carrying a model per style, and the module's Style field is the
index into it -- so B_TUR_A, style 33, lands on GUN_A and B_TRU_J, style 42, on ZENGINEJ.

Nothing in the module's row names its part, so the family code in the id does that job here.

Interior walls, stairs and floors are left out deliberately. Their part is chosen by which hab
the piece sits inside and which way the wall runs, and the row records neither, so there is no
honest answer from the id alone.

So is the hull, U_PARAGON, which has no row at all: it anchors the base rather than being built
into it, and a corvette's body is nothing but the modules bolted to it. The one scene named after
it, BIGGS.SCENE.MBIN, holds seventeen meshes and every one of them is a hologram -- the blue
preview the build station projects, not the ship.
"""
from __future__ import annotations

import functools
import os
import re

from nms_save import gamefiles, gamemeta
from nms_save.gamefiles import array, cstr, i32, read, vstr

# family code off the module id -> the parts that make it up, {v} being the variant
PARTS = {
    "ALK": ["_BIGGS_EXTHATCHALK1X1{v}"],
    "COK": ["_BIGGS_COK_{v}"],
    "CON": ["_BIGGS_CON1X1_{v}"],
    "CON2": ["_BIGGS_CON1X2_"],
    "DECO": ["_BIGGS_EXTDECORATION"],
    "GEN": ["_BIGGS_GEN1X1_{v}"],
    "HAB": ["_BIGGS_HAB_1X2_CORE"],
    "HAB1": ["_BIGGS_HAB_1X1_CORE"],
    "HOP": ["_BIGGS_HOP1X2_"],
    "LND": ["_BIGGS_LND1X1"],
    "MAG": ["_BIGGS_MAG{v}"],
    "SHL": ["_BIGGS_EXTSHL1X1{v}"],
    "TRU": ["_BIGGS_EXTTRU1X1"],
    "TUR": ["_BIGGS_EXTTUR1X1"],
}

# Wings and the lettered connectors are handed, and the game keeps a separate module for each
# side: B_WNG_A is the left wing and B_WNG_A_R the right, B_WNG_P_T and B_WNG_P_B the top and
# bottom, B_CON_L_0 and B_CON_R_0 the two connectors. Sixty-four wing modules, sixty-four wing
# parts, one apiece.
#
# Taking the side from the family instead drew every part the family had: a left-hand module
# came out with its mirrored twin standing beside it, and a right-hand one drew nothing at all.
WING = re.compile(r"^B_WNG_([A-Z])(?:_(\d+))?(?:_([RTB]))?$")
CONNECTOR = re.compile(r"^B_CON_([LR])_(\d+)$")


def _sided(module_id: str):
    """The one part a handed module draws, or None if it is not one of them."""
    m = WING.match(module_id)
    if m:
        letter, piece, side = m.group(1), m.group(2), m.group(3) or "L"
        return "_BIGGS_EXTWNG%s1X2%s%s" % (side, letter, "_" + piece if piece else "")
    m = CONNECTOR.match(module_id)
    if m:
        return "_BIGGS_CON1X1_%s_%s" % m.groups()
    return None


@functools.lru_cache(maxsize=1)
def parts() -> dict:
    """{part id: {style: scene path}} for every corvette part the game can draw."""
    folder = gamefiles.extract(os.path.join(gamefiles.CACHE, "parts"),
                               ["metadata/reality/tables/basebuildingpartstable*"], "NMSARC.Precache.pak")
    meta = gamemeta.exe_meta()
    table = meta.layout("cGcBaseBuildingPartsTable")
    part = meta.layout("cGcBaseBuildingPart")
    style = meta.layout("cGcBaseBuildingPartStyleModel")
    b = read(os.path.join(folder, "basebuildingpartstable.mbin"))
    base, n = array(b, 0x20 + table.off("Parts"))
    out = {}
    for k in range(n):
        o = base + k * part.size
        pid = cstr(b, o + part.off("ID"), 32)
        if not pid.startswith("_BIGGS"):
            continue
        models, count = array(b, o + part.off("StyleModels"))
        out[pid] = {i32(b, models + j * style.size + style.off("Style")):
                    vstr(b, models + j * style.size + style.off("Model")) for j in range(count)}
    return out


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
            "style": i32(b, o + row.off("Style")),
            "in_menu": bool(b[o + row.off("ShowInBuildMenu")]),
            "rotatable": bool(b[o + row.off("CanRotate3D")]),
            "limit": i32(b, o + row.off("CorvetteBaseLimit")),
        }
    return out


def _split(module_id: str):
    """B_HAB_D -> ("HAB", "D"); the hull and anything unfamiliar give no family."""
    bits = module_id.lstrip("^").split("_")
    if len(bits) < 3 or bits[0] != "B":
        return None, None
    return "_".join(bits[1:-1]), bits[-1]


def _part_ids(family: str, variant: str) -> list[str]:
    """The parts one module is built from.

    Most families name their part outright. The lettered series carry the letter in the family
    code and the piece in the variant instead, so they are worked out rather than listed.
    Handed parts do not come through here at all; see _sided.
    """
    if family.startswith("STR_"):
        return ["_BIGGS_EXTSTR_1X1_" + variant]
    if family.startswith("DECO_"):
        return ["_BIGGS_EXTDECORATION" + ("" if variant == "0" else variant)]
    return [t.format(v=variant) for t in PARTS.get(family, [])]


#  A structural piece that leans to one side carries its direction in the suffix, and the
#  compass points come in mirrored pairs: _NE against _NW, and _NETB against _NWTB, with any
#  trailing number kept. Measured on six families, every NE/NW pair is an exact reflection in X
#  -- B_STR_D_NE spans x 0..6 and B_STR_D_NW spans -6..0, same in y and z.
#
#  _E and _W are named by the same scheme and are almost certainly a pair too, but neither of
#  them resolves to a model, so that one is inferred rather than measured.
COMPASS = [("_NETB", "_NWTB"), ("_NE", "_NW"), ("_E", "_W")]


def _compass_twin(mid: str):
    """The opposite-handed structural module, keeping any trailing variant number.

    The direction is the end of the id, and only the end: B_STR_E_E is family E facing east,
    and looking for "_E" anywhere in it finds the family letter first.
    """
    base = mid.rstrip("0123456789")
    number = mid[len(base):]
    for a, b in COMPASS:
        for here, there in ((a, b), (b, a)):
            if base.endswith(here):
                return base[:-len(here)] + there + number
    return None


@functools.lru_cache(maxsize=1)
def handed() -> dict:
    """{module id: the module that is its mirror image}, both ways round.

    Mirroring is not turning. The game keeps a module per side, authored as the other one
    reflected, and swaps one for the other -- wings, the lettered connectors, and the structural
    pieces that lean. Guessing this from the id costs you: taking an "_R" suffix to mean
    right-hand asks for hull blocks that do not exist, and missing the _NE/_NW pairs leaves
    every aerofoil on the far side of the ship facing the wrong way.
    """
    cat, out = catalogue(), {}
    for mid in cat:
        other = None
        m = WING.match(mid)
        if m and m.group(3) in (None, "R"):           # top and bottom are not a left-right pair
            other = mid + "_R" if m.group(3) is None else mid[:-2]
        elif CONNECTOR.match(mid):
            other = (mid.replace("_L_", "_R_") if CONNECTOR.match(mid).group(1) == "L"
                     else mid.replace("_R_", "_L_"))
        else:
            other = _compass_twin(mid)
        if other and other in cat:
            out[mid] = other
    return out


@functools.lru_cache(maxsize=256)
def snaps_for(module_id: str) -> tuple:
    """The sockets one module offers, as (kind, "in"/"out", 16 floats column-major).

    They come off the placement scene rather than the model: the placement scene is the thing
    the build menu moves around, and the sockets are what it lines up.
    """
    from nms_procgen import model3d
    entry = catalogue().get(module_id.lstrip("^"))
    if not entry or not entry["placement"]:
        return ()
    out = []
    for kind, io, mat in model3d.snap_points(entry["placement"]):
        out.append((kind, io, tuple(float(mat[r][c]) for c in range(4) for r in range(4))))
    return tuple(out)


def scenes_for(module_id: str) -> list[str]:
    """The scenes that draw one module, in the order they should be drawn.

    Empty when nothing is known to draw it, which the modeller treats as a module to leave out
    rather than an error.
    """
    bare = module_id.lstrip("^")
    entry = catalogue().get(bare)
    family, variant = _split(bare)
    if entry is None or family is None:
        return []
    one = _sided(bare)
    table, out = parts(), []
    for pid in ([one] if one else _part_ids(family, variant)):
        models = table.get(pid)
        if not models:
            continue
        # a part with one model offers it whatever style the module asks for
        model = models.get(entry["style"]) or (len(models) == 1 and next(iter(models.values())))
        if model:
            out.append(model)
    return out
