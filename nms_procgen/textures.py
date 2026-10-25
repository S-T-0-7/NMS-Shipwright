# seed -> ship colours, texture modes + decals, following NMS.exe.
# colours: palette table gen (exeaddr "palette_table") fills 66 base palettes x 5 colours
#   from the resource seed. verified vs nms.center "colors" for 5 fighter seeds.
# textures: each sampler loads <map>.TEXTURE.MBIN, layers merged by (Name, Group), probs +
#   weights averaged. then MWC(seed), per layer in order:
#   - prob>0: 1 step, x = s0/(2^32-1), used if prob > x
#   - used + not SelectToMatchBase: 1 more step for weighted pick
#   - SelectToMatchBase: take the option named like the one picked for BASE
#   colour = table[palette].colours[alt] (alt>3 -> colour 3, 6 -> override, 7 -> none).
# WARN: all maths is float32 like the game. dont switch to float64, picks will drift.
from __future__ import annotations

import functools
import os
import re

import numpy as np

from nms_save import gamefiles, gamemeta
from nms_save.gamefiles import array, cstr, f32, i32, read, vstr

from .generator import ROOTS, all_parts, generate, parse_seed

K, C1, C2, M64 = 0x5A76F899, 0x64DD81482CBD31D7, 0xE36AA5C613612997, (1 << 64) - 1
INV = np.float64(1.0 / 4294967295.0)
PALETTE_NAMES = (
    "Grass Plant Leaf Wood Rock Stone Crystal Sand Dirt Metal Paint Plastic Fur Scale Feather Water Cloud Sky "
    "Space Underbelly Undercoat Snow SkyHorizon SkyFog SkyHeightFog SkySunset SkyNight WaterNear SpaceCloud "
    "SpaceBottom SpaceSolar SpaceLight Warrior Scientific Trader WarriorAlt ScientificAlt TraderAlt RockSaturated "
    "RockLight RockDark PlanetRing Custom_Head Custom_Torso Custom_Chest_Armour Custom_Backpack Custom_Arms "
    "Custom_Hands Custom_Legs Custom_Feet Cave GrassAlt BioShip_Body BioShip_Underbelly BioShip_Cockpit "
    "SailShip_Sails Freighter FreighterPaint PirateBase PirateAlt SpaceStationBase SpaceStationAlt "
    "SpaceStationLights DeepWaterBioLum Slime Hulk").split()
ALT_NAMES = ("Primary", "Alternative1", "Alternative2", "Alternative3", "Alternative4", "Unique", "MatchGround", "None")
PAINT, UNDERCOAT = 10, 20
CACHE = gamefiles.CACHE
TEX_DIR = os.path.join(CACHE, "shiptex")


def _dir(sub, pattern, pak):
    return gamefiles.extract(os.path.join(TEX_DIR, sub), [pattern], pak, keep_dirs=True)


def _game_path(folder, path):
    return os.path.join(folder, *path.lower().split("/"))


# ---------------------------------------------------------------- palettes --

def _mix64(x):
    x = ((x ^ (x >> 33)) * C1) & M64
    x = ((x ^ (x >> 33)) * C2) & M64
    return x ^ (x >> 33)


def _state(seed):
    lo, hi = seed & 0xFFFFFFFF, seed >> 32
    return [lo or 1, (((lo >> 16) | (lo << 16)) & 0xFFFFFFFF) ^ hi ^ lo]


def _step(st):
    t = st[0] * K + st[1]
    st[0], st[1] = t & 0xFFFFFFFF, t >> 32
    return st[0]


def _child(st):
    s = list(st)
    a = _step(s)
    return _mix64((_step(s) << 32) | a), s


@functools.lru_cache(maxsize=1)
def palettes():
    """[(64 RGBA colours, NumColours)] from BASECOLOURPALETTES.MBIN."""
    folder = _dir("colours", "metadata/simulation/solarsystem/colours/basecolourpalettes.mbin", "NMSARC.Precache.pak")
    b = read(_game_path(folder, "metadata/simulation/solarsystem/colours/basecolourpalettes.mbin"))
    out = []
    for p in range((len(b) - 0x20) // 0x410):
        o = 0x20 + p * 0x410
        cols = np.frombuffer(b, np.float32, 256, o).reshape(64, 4)
        out.append((cols, i32(b, o + 0x400)))
    return out


def _norm(mode, i):
    if mode == 1:
        return 0
    if mode == 2:
        return ((i % 8) // 4 + (i // 32) * 8) * 4
    if mode == 3:
        return i % 8
    if mode == 4:
        return ((i % 8) // 2 + (i // 16) * 8) * 2
    return i


def _palette(pals, p, st, n=5):
    cols, idxs = [], []
    table, mode = pals[p]
    for _ in range(n):
        a, b = _step(st) >> 29, _step(st) >> 29
        i = {1: 0, 2: ((b >> 2) + (a >> 2) * 8) * 4, 3: b, 4: ((b >> 1) + (a >> 1) * 8) * 2}.get(mode, b + a * 8)
        c = table[_norm(mode, i)]
        for _tries in range(64):  # the game re-rolls a colour that repeats an earlier one
            if not any(np.sum((c[:3] - d[:3]) ** 2, dtype=np.float32) < np.float32(2.3283064365386963e-10)
                       for d in cols):
                break
            i = (i + 1) % 64
            c = table[_norm(mode, i)]
        cols.append(c)
        idxs.append(i)
    return cols, idxs


@functools.lru_cache(maxsize=256)
def palette_table(seed):
    """[(5 colours, 5 indices)] per palette for this seed."""
    pals = palettes()
    st, table, saved = _state(parse_seed(seed)), [None] * len(pals), None
    for p in range(52):
        if p == PAINT:
            saved = list(st)
        table[p] = _palette(pals, p, st)
    c1, rest = _child(st)
    c2, _ = _child(rest)
    for p in (32, 35, 34, 37, 33, 36):  # race palettes share one seed
        table[p] = _palette(pals, p, _state(c1))
    table[0] = _palette(pals, 0, _state(c2))
    grass = _state(c2)
    table[51] = _palette(pals, 51, grass)
    tail = _state(_child(grass)[0])
    for p in range(52, len(pals)):
        table[p] = _palette(pals, p, saved if p == 56 else tail)
    return table


def colour(table, palette, alt, override=None):
    if alt == 7:
        return None
    if alt == 6:
        return override
    return table[palette][0][alt if alt <= 3 else 3]


# ------------------------------------------------------------ texture lists --

@functools.lru_cache(maxsize=1)
def _layouts():
    m = gamemeta.exe_meta()
    tl = m.layout("cTkProceduralTextureList")
    layer = m.element(tl, "Layers")
    opt = m.element(layer, "Textures")
    pal = m.element(opt, "Palette")
    return tl, layer, opt, pal


@functools.lru_cache(maxsize=None)
def texture_list(path):
    """Parsed *.TEXTURE.MBIN (game path), or None if the game has no such list."""
    folder = _dir("lists", "textures/*.texture.mbin", "NMSARC.Precache.pak")
    full = _game_path(folder, path)
    if not os.path.exists(full):
        return None
    tl, ly, op, pa = _layouts()
    b = read(full)
    if not tl.matches(b):
        raise gamefiles.GameFileError(f"{path} doesn't match NMS.exe's layout")
    layers = []
    for i in range(tl.fields["Layers"]["count"] or 8):
        L = 0x20 + tl.off("Layers") + i * ly.size
        base, n = array(b, L + ly.off("Textures"))
        opts = []
        for j in range(n):
            o = base + j * op.size
            p = o + op.off("Palette")
            opts.append({"name": cstr(b, o + op.off("Name"), 0x20), "alt": i32(b, p + pa.off("ColourAlt")),
                         "palette": i32(b, p + pa.off("Palette")), "weight": f32(b, o + op.off("Probability")),
                         "use": i32(b, o + op.off("TextureGameplayUse")), "texture": vstr(b, o + op.off("TextureName"))})
        layers.append({"name": cstr(b, L + ly.off("Name"), 0x10), "group": cstr(b, L + ly.off("Group"), 0x10),
                       "prob": f32(b, L + ly.off("Probability")), "match_base": bool(b[L + ly.off("SelectToMatchBase")]),
                       "options": opts})
    return layers


def pick(merged, seed, table):
    """[(layer, option or None)] for merged layers [(layer, count, [(option, count)])]."""
    f = np.float32
    st = _state(parse_seed(seed))
    out = []
    for layer, lcount, opts in merged:
        prob = f(layer["prob_sum"]) / f(lcount)
        chosen = None
        if prob > 0:
            x = f(np.float64(_step(st)) * INV)
            if prob > x and layer["match_base"]:
                chosen = "match"
            elif prob > x:
                weights = [f(o["weight_sum"]) / f(c) for o, c in opts]
                total = f(0)
                for w in weights:
                    total = f(total + w)
                r = f(f(np.float64(_step(st)) * INV) * total)
                acc = f(0)
                for (o, _), w in zip(opts, weights):
                    acc = f(acc + w)
                    if acc > r:
                        chosen = o
                        break
        out.append([layer, chosen, opts])
    base = next((c for l, c, _ in out if l["name"] == "BASE" and isinstance(c, dict)), None)
    for row in out:
        if row[1] == "match":
            row[1] = next((o for o, _ in row[2] if base and o["name"] == base["name"]), None)
    return [(l, c) for l, c, _ in out]


# TextureGameplayUse. A spacecraft list tags every option 0, but the robot list a sentinel ship
# draws from tags its OVERLAY options: POLICE is 1 and the four ship ones are 2. Taking only 0
# threw that whole layer away, which is why a sentinel never picked an overlay and its second
# colour could not be predicted.
USE_ANY, USE_SENTINEL = 0, 2


def merge(lists, use=USE_ANY):
    """Merge the layers of several texture lists (one per material sampler), as the game does.

    `use` is the gameplay use whose options count here, besides the untagged ones.
    """
    merged = []
    for layers in lists:
        for layer in layers:
            if not layer["options"]:
                continue
            key = (layer["name"], layer["group"])
            slot = next((m for m in merged if m[0]["key"] == key), None)
            if slot is None:
                slot = [dict(layer, key=key, prob_sum=np.float32(0)), 0, []]
                merged.append(slot)
            slot[0]["prob_sum"] = np.float32(slot[0]["prob_sum"] + np.float32(layer["prob"]))
            slot[1] += 1
            for o in layer["options"]:
                okey = (o["name"], o["alt"], o["palette"])
                have = next((x for x in slot[2] if x[0]["okey"] == okey), None)
                if have is None:
                    if o["use"] not in (USE_ANY, use):
                        continue
                    have = [dict(o, okey=okey, weight_sum=np.float32(0)), 0]
                    slot[2].append(have)
                have[0]["weight_sum"] = np.float32(have[0]["weight_sum"] + np.float32(o["weight"]))
                have[1] += 1
    return [(m[0], m[1], [(o, c) for o, c in m[2]]) for m in merged]


# ------------------------------------------------------- scenes & materials --

@functools.lru_cache(maxsize=1)
def _scene_layouts():
    m = gamemeta.exe_meta()
    node = m.layout("cTkSceneNodeData")
    mat = m.layout("cTkMaterialData")
    return node, m.element(node, "Attributes"), mat, m.element(mat, "Samplers")


def _scene(path):
    folder = _dir("scenes", "models/common/spacecraft/*.scene.mbin", "NMSARC.EntitySceneMBIN.pak")
    full = _game_path(folder, path)
    return read(full) if os.path.exists(full) else None


def _walk(b, o, keep, out, depth=0):
    node, attr, _, _ = _scene_layouts()
    name = vstr(b, o + node.off("Name"))
    if not keep(name):
        return
    base, n = array(b, o + node.off("Attributes"))
    attrs = {cstr(b, base + k * attr.size + attr.off("Name"), 0x10):
             vstr(b, base + k * attr.size + attr.off("Value")).replace("\\", "/") for k in range(n)}
    if attrs.get("MATERIAL"):
        out["materials"].add(attrs["MATERIAL"])
    if attrs.get("SCENEGRAPH"):
        out["refs"].add(attrs["SCENEGRAPH"])
    base, n = array(b, o + node.off("Children"))
    for k in range(n):
        _walk(b, base + k * node.size, keep, out, depth + 1)


@functools.lru_cache(maxsize=None)
def material_lists(path):
    """{texture list path: number of samplers using it} for a material."""
    folder = _dir("materials", "models/common/spacecraft/*.material.mbin", "NMSARC.MetadataEtc.pak")
    full = _game_path(folder, path)
    if not os.path.exists(full):
        return {}
    _, _, mat, smp = _scene_layouts()
    b = read(full)
    base, n = array(b, 0x20 + mat.off("Samplers"))
    out = {}
    for k in range(n):
        m = vstr(b, base + k * smp.size + smp.off("Map"))
        if not m:
            continue
        stem = re.sub(r"(\.[^./]*){1,4}$", "", m)
        lst = stem + ".TEXTURE.MBIN"
        if texture_list(lst):
            out[lst] = out.get(lst, 0) + 1
    return out


def ship_materials(seed, ship):
    """Materials on the parts `seed` builds (the root scene with unpicked options removed)."""
    root = "MODELS/" + ROOTS[ship][len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
    options = {p for ps in all_parts(ship).values() for p in ps}
    chosen = {pid for _, pid in generate(seed, ship)}
    lod = re.compile(r"LOD\d$")

    def keep(name):
        up = name.upper()
        return up not in options or lod.sub("", up) in chosen or up in chosen
    out, todo, seen = {"materials": set(), "refs": set()}, [root], set()
    while todo:
        path = todo.pop()
        if path.upper() in seen:
            continue
        seen.add(path.upper())
        b = _scene(path)
        if b:
            _walk(b, 0x20, keep, out)
        todo.extend(r for r in out["refs"] if r.upper() not in seen)
    return sorted(out["materials"])


def ship_look(seed, ship):
    """Colours, texture modes and decals `seed` gives this ship type."""
    seed = parse_seed(seed)
    table = palette_table(seed)
    picks = {}
    for material in ship_materials(seed, ship):
        lists = material_lists(material)
        if not lists:
            continue
        merged = merge([texture_list(p) for p, c in lists.items() for _ in range(c)],
                       USE_SENTINEL if ship == "sentinel" else USE_ANY)
        for layer, opt in pick(merged, seed, table):
            key = (os.path.basename(next(iter(lists))).split(".")[0], layer["name"])
            if opt is None or key in picks:
                continue
            rgb = colour(table, opt["palette"], opt["alt"])
            picks[key] = {"list": key[0], "layer": layer["name"], "option": opt["name"],
                          "palette": PALETTE_NAMES[opt["palette"]] if opt["palette"] < len(PALETTE_NAMES) else opt["palette"],
                          "alt": ALT_NAMES[opt["alt"]] if 0 <= opt["alt"] < len(ALT_NAMES) else opt["alt"],
                          "rgb": None if rgb is None else [round(float(v), 4) for v in rgb[:3]]}
    paint, under = table[PAINT], table[UNDERCOAT]
    swatch = lambda t, k: {"index": t[1][k], "rgb": [round(float(v), 4) for v in t[0][k][:3]]}
    return {
        "seed": f"0x{seed:016X}", "ship": ship,
        "colours": {"primary": swatch(paint, 0), "secondary": swatch(paint, 1), "undercoat": swatch(under, 0),
                    "decal1": swatch(paint, 2), "decal2": swatch(paint, 3)},
        "textures": sorted(picks.values(), key=lambda p: (p["list"], p["layer"])),
    }


PAINT_ALTS = ("Primary", "Alternative1", "Alternative2", "Alternative3", "Alternative4")


def paint_channels(seed, ship):
    """[{"alt", "layers"}] -- the paint slots this ship really draws, and what each paints.

    A ship is not one colour and a trim: the game gives it five paint slots, and which of them a
    ship uses comes out of its own texture lists. A fighter spends Alternative2 on signage and
    Alternative4 on a tertiary trim; a sentinel interceptor draws its hull from Alternative1 and
    only its pincers from Primary, and then only on seeds whose overlay reads Alternative1 (see
    USE_SENTINEL). Offering a slot the ship never draws paints nothing.
    """
    used = {}
    for t in ship_look(seed, ship)["textures"]:
        if t["palette"] != "Paint" or t["alt"] not in PAINT_ALTS:
            continue
        used.setdefault(t["alt"], []).append(t["layer"])
    return [{"alt": a, "layers": sorted(set(used[a]))} for a in PAINT_ALTS if a in used]


# Which overlay an interceptor wears is one draw: FIXED takes the first two steps of the
# stream, then OVERLAY's own two, and its four options carry equal weight, so the fourth
# output lands in one of four equal buckets. Checked against pick() over 300 seeds, all
# 300 agreeing.
#
# Only the first bucket, option "1", hides the paint. Checked in game 2026-10-25 by painting
# four interceptors the same green: the two on option 2 came out green, the two on option 1
# stayed their seed's orange. The sheets say why -- OVERLAY.1.DDS covers the whole sheet at
# full alpha while OVERLAY.2.DDS covers 85% at an average of 218, so only the first is opaque
# enough to bury what is underneath. Options 3 and 4 read the paint outright.
OVERLAY_STEPS = 4
# Options 1 and 3 draw their own body colour and the paint never reaches it; 2 and 4 let it
# through. Watched in game 2026-10-25, one variable at a time: three overlay-3 ships, one
# left alone, one painted green, one painted black, came out black, black with green pincers,
# and black. The green pincers are the BASE layer, which takes the paint on any seed -- it is
# the body that is fixed. Overlay 1 does the same in orange-brown instead.
PAINTED_BODY = (1, 3)   # buckets of four, i.e. options "2" and "4"

# What each overlay draws with, measured off its own sheet, and what that comes out as on an
# unpainted ship -- every interceptor watched in game so far agrees:
#   1  warm brown, covers the sheet outright  -> orange
#   2  neutral grey, lets the base through    -> whatever the base is, muted
#   3  the darkest sheet of the four          -> near black, whatever the seed
#   4  blue, and only a sixth of the sheet    -> the base, with a trim
BLACK_OVERLAY = "3"


def overlay_bucket(s0, s1):
    """Vectorised: which of the four overlay options a seed draws, as 0-3."""
    a0, a1 = s0, s1
    for _ in range(OVERLAY_STEPS):
        a0, a1 = _np_steps(a0, a1, 1)
    x = (a0.astype(np.float64) * INV).astype(np.float32)
    return (x * np.float32(4.0)).astype(np.float32).astype(np.int64)


def overlay_mask(s0, s1, options):
    """Vectorised: True where the seed's overlay is one of `options` (names, "1".."4")."""
    want = {int(o) - 1 for o in options}
    bucket = overlay_bucket(s0, s1)
    keep = np.zeros(len(bucket), bool)
    for b in want:
        keep |= bucket == b
    return keep


def paintable_mask(s0, s1):
    """Vectorised: True where an interceptor seed's overlay lets the paint reach its body."""
    bucket = overlay_bucket(s0, s1)
    keep = np.zeros(len(bucket), bool)
    for b in PAINTED_BODY:
        keep |= bucket == b
    return keep


def overlay_of(seed):
    """The overlay option one interceptor seed draws, as the texture list names it."""
    overlay = next((t for t in ship_look(seed, "sentinel")["textures"] if t["layer"] == "OVERLAY"), None)
    return overlay["option"] if overlay else ""


def hull_takes_paint(seed, ship):
    """Whether paint reaches this ship's body, which on an interceptor is not a given.

    BASE is the coat under everything and takes the paint on any seed -- on an interceptor it
    is the pincers. OVERLAY goes over the body, and of its four options two draw a colour of
    their own that the paint never gets through: 1 in orange-brown and 3 in near black. Half
    of all seeds, then, and which half decides the colour the ship is stuck with. 2 and 4 let
    the paint through, 4 giving a separate trim as well. Every other ship type shows BASE.

    Watched in game 2026-10-25, a colour at a time: overlay 2 went green, overlay 1 stayed
    orange, and three overlay-3 ships -- bare, green, and black -- all kept black bodies.
    """
    if ship != "sentinel":
        return True
    return overlay_of(seed) in ("2", "4")


# ------------------------------------------------------ search on the look --

PRIMARY_LIST = "TEXTURES/COMMON/SPACECRAFT/FIGHTERS/SHARED/PRIMARY.TEXTURE.MBIN"
PRIMARY_MATERIAL = "MODELS/COMMON/SPACECRAFT/FIGHTERS/WINGS/WINGS_G/WINGSG/PRIMARY.MATERIAL.MBIN"
LOOK_KEYS = ("primary", "secondary", "undercoat", "mode")


@functools.lru_cache(maxsize=1)
def _mode_pick():
    """(option names, float32 running weights) of the shared hull paint's BASE layer."""
    count = material_lists(PRIMARY_MATERIAL).get(PRIMARY_LIST, 1)
    merged = merge([texture_list(PRIMARY_LIST)] * count)
    layer, lcount, opts = merged[0]
    assert layer["name"] == "BASE" and not layer["match_base"]
    f, acc, cum = np.float32, np.float32(0), []
    for o, c in opts:
        acc = f(acc + f(o["weight_sum"]) / f(c))
        cum.append(acc)
    return [o["name"] for o, _ in opts], np.array(cum, np.float32), f(layer["prob_sum"]) / f(lcount)


def mode_names():
    names, cum, _ = _mode_pick()
    return [n for n, w in zip(names, np.diff(np.concatenate([[0], cum]))) if w > 0]


def look_keys(seed):
    """The searchable part of a seed's look: Paint Primary/Secondary and Undercoat colour indices, hull mode."""
    pals, seed = palettes(), parse_seed(seed)
    st = _state(seed)
    for _ in range(PAINT * 10):  # every earlier palette takes 5 colours x 2 steps (re-rolls take none)
        _step(st)
    paint = _palette(pals, PAINT, st)
    for _ in range((UNDERCOAT - PAINT - 1) * 10):
        _step(st)
    under = _palette(pals, UNDERCOAT, st, 1)
    names, cum, prob = _mode_pick()
    st = _state(parse_seed(seed))
    mode = None
    if prob > np.float32(np.float64(_step(st)) * INV):
        r = np.float32(np.float32(np.float64(_step(st)) * INV) * cum[-1])
        k = int(np.searchsorted(cum, r, side="right"))
        mode = names[k] if k < len(names) else None
    return {"primary": paint[1][0], "secondary": paint[1][1], "undercoat": under[1][0], "mode": mode}


def _np_steps(s0, s1, n):
    K64, M32 = np.uint64(K), np.uint64(0xFFFFFFFF)
    for _ in range(n):
        t = s0 * K64 + s1
        s0, s1 = t & M32, t >> np.uint64(32)
    return s0, s1


def look_mask(s0, s1, want):
    """Vectorised pre-filter for look_keys; want = {key: collection of allowed values}."""
    ok = np.ones(len(s0), bool)
    sh = np.uint64(29)
    with np.errstate(over="ignore"):
        if want.get("mode"):
            names, cum, prob = _mode_pick()
            a0, a1 = _np_steps(s0, s1, 1)
            x = (a0.astype(np.float64) * INV).astype(np.float32)
            b0, _ = _np_steps(a0, a1, 1)
            r = ((b0.astype(np.float64) * INV).astype(np.float32) * cum[-1]).astype(np.float32)
            k = np.searchsorted(cum, r, side="right")
            allowed = np.array([n in want["mode"] for n in names] + [False])
            ok &= (prob > x) & allowed[np.minimum(k, len(names))]
        if want.get("primary") is not None or want.get("secondary") is not None:
            p0, p1 = _np_steps(s0, s1, 100)
            a, _ = _np_steps(p0, p1, 1)
            b, q1 = _np_steps(a, _, 1)
            prim = ((b >> sh) + (a >> sh) * np.uint64(8)).astype(np.int64)
            if want.get("primary") is not None:
                ok &= np.isin(prim, list(want["primary"]))
            if want.get("secondary") is not None:
                c, _ = _np_steps(b, q1, 1)
                d, _ = _np_steps(c, _, 1)
                sec = ((d >> sh) + (c >> sh) * np.uint64(8)).astype(np.int64)
                ok &= np.isin(sec, list(want["secondary"])) | np.isin((sec + 63) % 64, list(want["secondary"]))
        if want.get("undercoat") is not None:
            u0, u1 = _np_steps(s0, s1, 200)
            a, _ = _np_steps(u0, u1, 1)
            b, _ = _np_steps(a, _, 1)
            ok &= np.isin(((b >> sh) + (a >> sh) * np.uint64(8)).astype(np.int64), list(want["undercoat"]))
    return ok


def look_matches(seed, want):
    keys = look_keys(seed)
    return all(v is None or keys[k] in v for k, v in want.items() if k in LOOK_KEYS and v)
