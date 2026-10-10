# 3D models of procedural ships, from the game's scene + geometry files.
# ship_model(seed, ship) walks the root scene like the game: drops descriptor nodes the
# seed didnt pick, REFERENCE nodes pull in the part's scene, each LOD0 mesh placed w/ its
# accumulated transform. output = 1 compact binary (pack()) that viewer.js draws w/ WebGL.
# geometry read on demand from NMSARC.MeshCommon.pak, reduced to pos+indices under CACHE/models/.
from __future__ import annotations

import functools
import json
import os
import re
import struct
import threading

import numpy as np

from nms_save import gamefiles, gamemeta, gameversion
from nms_save.gamefiles import array, cstr, i32, read, vstr

from . import textures
from .generator import ROOTS, all_parts, generate

MESH_PAK = "NMSARC.MeshCommon.pak"
MODEL_DIR = os.path.join(gamefiles.CACHE, "models")
FORMAT = 2  # bump when the cached mesh format changes
_LOCK = threading.Lock()

# material file name -> how the viewer shades it
# How the game itself classifies a material (cTkMaterialData.Class). Anything invisible in game
# must stay invisible here, or it shows up as stray dark facets over the hull.
MAT_SKIP = {12: "decal", 14: "mask", 58: "reflection plane", 59: "shadow only", 70: "volume", 71: "volume"}
MAT_GLOW = {2, 9, 10, 18, 19, 22}  # lights, glows and holograms: added on top, never solid
MAT_GLASS = {62}                   # canopies, screens, refraction
SKIP_SHADERS = ("PARTICLE", "DEFERREDDECAL")  # effects and decals the game draws over the hull

# ...and the name decides which colour a solid surface takes
MAT_CLASSES = (("glass", re.compile(r"GLASS|CANOPY|WINDOW|SCREEN|COCKPITTRANS|TRANS_")),
               ("light", re.compile(r"LIGHT|GLOW|EMIS|THRUST|FLAME|LASER")),
               ("secondary", re.compile(r"SECONDARY|TERTIARY")),
               ("paint", re.compile(r"PRIMARY")),
               ("metal", re.compile(r"METAL|TRIM|CHROME|GUN|ENGINE|PIPING|INTERIOR|MECH")),
               ("dark", re.compile(r"RUBBER|DARK|BLACK|GRILL|VENT|UNDERCOAT")))
LOD_SUFFIX = re.compile(r"LOD(\d)$", re.I)
DECAL_NAMES = re.compile(r"DECAL|SHADOW|MASKMAT|DEPTHMASK")  # skipped when judging by name only
EFFECTS = re.compile(r"SHIELD|WARPBUBBLE|FORCEFIELD")  # invisible or effect-only shells around ships


@functools.lru_cache(maxsize=4096)
def _material_class(material: str):
    """(cTkMaterialData.Class, shader name) of one material file, or (None, "") if unreadable."""
    if not material:
        return None, ""
    try:
        from nms_save.gamefiles import read as _read
        folder = textures._dir("materials", "models/common/spacecraft/*.material.mbin", "NMSARC.MetadataEtc.pak")
        path = textures._game_path(folder, material)
        if not os.path.exists(path):
            return None, ""
        _, _, mat, _ = textures._scene_layouts()
        b = _read(path)
        if not mat.matches(b):  # not a material after all (or a file still being written)
            return None, ""
        from nms_save.gamefiles import vstr as _vstr
        return b[0x20 + mat.off("Class")], _vstr(b, 0x20 + mat.off("Shader")).split("/")[-1]
    except Exception:  # fall back to the name-based guess
        return None, ""


def name_class(material: str) -> str:
    """Colour group from the material's name alone (used when the material file cannot be trusted)."""
    name = os.path.basename(material.replace("\\", "/")).upper()
    if DECAL_NAMES.search(name):
        return "skip"
    for cls, rx in MAT_CLASSES:
        if rx.search(name):
            return "glow" if cls == "light" else cls
    return "paint"


def mat_class(material: str) -> str:
    """How to draw a material: "skip", "glow", "glass", or the colour group of a solid surface."""
    kind, shader = _material_class(material)
    if any(x in shader.upper() for x in SKIP_SHADERS):
        return "skip"
    if kind in MAT_SKIP:
        return "skip"
    if kind in MAT_GLOW:
        return "glow"
    if kind in MAT_GLASS:
        return "glass"
    name = os.path.basename(material.replace("\\", "/")).upper()
    for cls, rx in MAT_CLASSES:
        if rx.search(name):
            return "glow" if cls == "light" and kind is None else cls
    return "paint"


@functools.lru_cache(maxsize=1)
def _layouts():
    m = gamemeta.exe_meta()
    geo, meta = m.layout("cTkGeometryData"), m.layout("cTkMeshData")
    vl, ve = m.layout("cTkVertexLayout"), m.layout("cTkVertexElement")
    return geo, meta, vl, ve


def _scene_path(ref: str) -> str:
    return ref.replace("\\", "/").upper()


# ---------------------------------------------------------------- geometry --

def _cache_file(geometry: str) -> str:
    return os.path.join(MODEL_DIR, *geometry.lower().replace("\\", "/").split("/")) + ".npz"


def _extract(geometries):
    """Pull the raw geometry files of `geometries` (game paths ending .GEOMETRY.MBIN) out of the pak."""
    from hgpaktool import HGPAKFile
    want = {}
    for g in geometries:
        base = g.lower().replace("\\", "/")
        want[base + ".pc"] = (g, "geo")
        want[base.replace(".geometry.mbin", ".geometry.data.mbin") + ".pc"] = (g, "data")
    raw: dict = {}
    pak = os.path.join(gamefiles.BANKS, MESH_PAK)
    with HGPAKFile(pak) as f:
        for name, blob in f.extract(filters=list(want)):
            key = want.get(name.lower())
            if key:
                raw.setdefault(key[0], {})[key[1]] = blob
    return raw


def _convert(geo: bytes, data: bytes) -> dict:
    """{hash: (positions float16 [n, 3], indices uint32 [m])} for every mesh stream of one geometry."""
    G, MD, VL, VE = _layouts()
    lay = 0x20 + G.off("PositionVertexLayout")
    stride = i32(geo, lay + VL.off("Stride"))
    base, n = array(geo, lay + VL.off("VertexElements"))
    pos_off = next((geo[base + k * VE.size + VE.off("Offset")] for k in range(n)
                    if geo[base + k * VE.size + VE.off("SemanticID")] == 0), 0)
    wide = not i32(geo, 0x20 + G.off("Indices16Bit"))
    out = {}

    def indices(start, size, verts):
        """Index buffer of one mesh. The file's "16 bit" flag is not always right (the sentinel
        ship claims 32 bit and stores 16), so the width that actually fits the mesh wins."""
        first = np.uint32 if wide else np.uint16
        for dtype in (first, np.uint16 if wide else np.uint32):
            step = np.dtype(dtype).itemsize
            if size % step or (size // step) % 3:
                continue
            idx = np.frombuffer(data, dtype, size // step, start)
            if not len(idx) or int(idx.max()) < verts:
                return idx.astype(np.uint32)
        return np.frombuffer(data, first, size // np.dtype(first).itemsize, start).astype(np.uint32)
    base, n = array(data, 0x20)
    for k in range(n):
        q = base + k * MD.size
        h = struct.unpack_from("<Q", data, q + MD.off("Hash"))[0]
        vsize, isize = i32(data, q + MD.off("VertexDataSize")), i32(data, q + MD.off("IndexDataSize"))
        ms, _ = array(data, q + MD.off("MeshDataStream"))
        ps, pn = array(data, q + MD.off("MeshPositionDataStream"))
        verts = np.frombuffer(data, np.float16, pn // 2, ps).reshape(-1, stride // 2)[:, pos_off // 2:pos_off // 2 + 3]
        idx = indices(ms + vsize, isize, len(verts))
        out[h] = (np.ascontiguousarray(verts), idx)
    return out


def _geometry(geometries) -> dict:
    """{geometry path: {hash: (positions, indices)}}, extracting and converting what is missing."""
    gameversion.check()  # a game update throws the converted meshes away
    result, missing = {}, []
    for g in geometries:
        path = _cache_file(g)
        if os.path.exists(path):
            with np.load(path) as z:
                if int(z["format"]) == FORMAT:
                    hashes = z["hashes"]
                    result[g] = {int(h): (z[f"p{i}"], z[f"i{i}"]) for i, h in enumerate(hashes)}
                    continue
        missing.append(g)
    if missing:
        with _LOCK:
            for g, files in _extract(missing).items():
                # A too-small file means the archive was read while the game was updating it.
                if len(files.get("geo", b"")) < 0x400 or len(files.get("data", b"")) < 0x40:
                    continue
                meshes = _convert(files["geo"], files["data"])
                path = _cache_file(g)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                arrays = {"format": np.int32(FORMAT), "hashes": np.array(list(meshes), np.uint64)}
                for i, (p, ix) in enumerate(meshes.values()):
                    arrays[f"p{i}"], arrays[f"i{i}"] = p, ix
                np.savez_compressed(path, **arrays)
                result[g] = meshes
    return result


# ------------------------------------------------------------------- scenes --

def _matrix(t) -> np.ndarray:
    """cTkTransformData (rot degrees XYZ, scale, translation) -> 4x4; rotation applied X, then Y, then Z."""
    rx, ry, rz = np.radians(t[0:3])
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = Z @ Y @ X @ np.diag(t[3:6])
    m[:3, 3] = t[6:9]
    return m


def _nodes(path):
    """Parsed scene: (geometry path, root node) with nodes as (type, name, transform, attrs, children)."""
    b = textures._scene(path)
    if not b:
        return None
    node, attr, _, _ = textures._scene_layouts()
    tr = node.off("Transform")

    def parse(o):
        base, n = array(b, o + node.off("Attributes"))
        attrs = {cstr(b, base + k * attr.size + attr.off("Name"), 0x10): vstr(b, base + k * attr.size + attr.off("Value"))
                 for k in range(n)}
        t = struct.unpack_from("<9f", b, o + tr)
        base, n = array(b, o + node.off("Children"))
        return (cstr(b, o + node.off("Type"), 16), vstr(b, o + node.off("Name")), t, attrs,
                [parse(base + k * node.size) for k in range(n)])
    root = parse(0x20)
    return root[3].get("GEOMETRY", ""), root


_parsed = functools.lru_cache(maxsize=512)(_nodes)


_TRUNC_LEN = 15  # the game stores descriptor part names in a fixed field, truncating longer ones


def _canon(up, options, trunc):
    """A scene node name -> its descriptor option id. Descriptor ids are truncated to _TRUNC_LEN
    characters, so a scene node can be longer than its id (exotic's _SClassShip_Royal is the option
    _SCLASSSHIP_ROY, _SClassShip_SquidxRARE is _SCLASSSHIP_SQU). Without this the Royal/Squid choice
    is never matched and both are drawn at once."""
    if up in options:
        return up
    for o in trunc:  # longest first: only truncated (max-length) ids can be a prefix of a longer name
        if up.startswith(o):
            return o
    return up


def ship_meshes(seed, ship, parts=None, fill=True):
    """[(geometry path, hash, 4x4 world matrix, material class)] for the parts `seed` builds.

    With `parts` (the Designer's picks) and `fill`, the rest of the ship is filled in with the first
    option of every group the picks do not cover, so a half-finished design shows as a whole ship.
    Without `fill` only the picked parts are drawn: the ship is built up piece by piece.
    """
    if parts is not None and not fill:
        return _picked_meshes(ship, {p.upper() for p in parts})
    groups = all_parts(ship)
    options = {p for ps in groups.values() for p in ps}
    group_of = {p: g for g, ps in groups.items() for p in ps}
    trunc = sorted((o for o in options if len(o) >= _TRUNC_LEN), key=len, reverse=True)
    designing = parts is not None
    chosen = {p.upper() for p in parts} if designing else {pid for _, pid in generate(seed, ship)}
    lod = re.compile(r"LOD\d$")

    def keep(name):
        oid = _canon(name.upper(), options, trunc)
        return oid not in options or lod.sub("", oid) in chosen or oid in chosen

    def fill_defaults(children):
        """Give every group among these siblings a part, unless the design already picks one."""
        seen: dict = {}
        for c in children:
            oid = _canon(c[1].upper(), options, trunc)
            g = group_of.get(oid) or group_of.get(lod.sub("", oid))
            if g:
                seen.setdefault(g, []).append(oid)
        for g, names in seen.items():
            if any(n in chosen or lod.sub("", n) in chosen for n in names):
                continue
            real = [n for n in names if "NULL" not in n]  # a part rather than "none of them"
            chosen.add((real or names)[0])
    out = []

    def walk(n, geometry, world, depth):
        typ, name, t, attrs, children = n
        if not keep(name) or depth > 12:
            return
        world = world @ _matrix(t)
        if typ == "MESH":
            # Lower-detail copies sit inside the full-detail mesh and poke through it. Some of them
            # claim LODLEVEL 0, so the name (...LOD2) decides as well.
            suffix = LOD_SUFFIX.search(name)
            if attrs.get("LODLEVEL", "0") != "0" or (suffix and suffix.group(1) != "0"):
                return
            cls = mat_class(attrs.get("MATERIAL", ""))
            if attrs.get("HASH") and not EFFECTS.search(geometry.upper()):
                out.append((geometry, int(attrs["HASH"]), world, cls))
        elif typ == "REFERENCE" and attrs.get("SCENEGRAPH"):
            sub = _parsed(_scene_path(attrs["SCENEGRAPH"]))
            if sub:
                walk(sub[1], sub[0], world, depth + 1)
        elif typ in ("COLLISION", "LIGHT", "JOINT", "EMITTER"):
            return
        if designing and children:
            fill_defaults(children)
        for c in children:
            walk(c, geometry, world, depth)
    root = "MODELS/" + ROOTS[ship][len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
    scene = _parsed(root)
    if not scene:
        raise FileNotFoundError(f"scene {root} not found")
    walk(scene[1], scene[0], np.eye(4), 0)
    kept = [m for m in out if m[3] != "skip"]
    # Never hide the ship: if the material files say almost everything is invisible, they were
    # unreadable (a game update, or a half-finished copy), so fall back to the names alone.
    solid = [m for m in kept if m[3] not in ("glow", "glass")]
    if not solid and out:
        kept = [(g, h, w, name_class(c)) for g, h, w, c in out]
        kept = [m for m in kept if m[3] != "skip"]
    return kept


def _picked_meshes(ship, chosen):
    """Only the picked parts, placed where they sit on a finished ship.

    A picked part can sit inside a part that is not picked (a cockpit inside a hull option), so
    unpicked options are still walked for their transforms, they just draw nothing themselves.
    When a part appears under several parents, the copy under picked parents wins.
    """
    options = {p for ps in all_parts(ship).values() for p in ps}
    trunc = sorted((o for o in options if len(o) >= _TRUNC_LEN), key=len, reverse=True)
    lod = re.compile(r"LOD\d$")
    found: dict = {}  # part -> [(parents all picked, meshes)]

    def walk(n, geometry, world, depth, owner, ok):
        typ, name, t, attrs, children = n
        if depth > 12:
            return
        up = _canon(name.upper(), options, trunc)
        if up in options:
            base = lod.sub("", up)
            picked = up in chosen or base in chosen
            if picked:
                bucket = []
                found.setdefault(base, []).append((ok, bucket))
                owner = bucket
            else:
                owner = None
            ok = ok and picked
        world = world @ _matrix(t)
        if typ == "MESH":
            suffix = LOD_SUFFIX.search(name)
            if attrs.get("LODLEVEL", "0") != "0" or (suffix and suffix.group(1) != "0"):
                return
            if owner is not None and attrs.get("HASH") and not EFFECTS.search(geometry.upper()):
                owner.append((geometry, int(attrs["HASH"]), world, mat_class(attrs.get("MATERIAL", ""))))
        elif typ == "REFERENCE" and attrs.get("SCENEGRAPH"):
            sub = _parsed(_scene_path(attrs["SCENEGRAPH"]))
            if sub:
                walk(sub[1], sub[0], world, depth + 1, owner, ok)
        elif typ in ("COLLISION", "LIGHT", "JOINT", "EMITTER"):
            return
        for c in children:
            walk(c, geometry, world, depth, owner, ok)
    root = "MODELS/" + ROOTS[ship][len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
    scene = _parsed(root)
    if not scene:
        raise FileNotFoundError(f"scene {root} not found")
    base: list = []  # fixed pieces no option owns (cockpit lid, landing gear, guns)
    walk(scene[1], scene[0], np.eye(4), 0, base, True)
    out = [m for m in base if m[3] != "glow"] if chosen else []
    for copies in found.values():
        best = [m for ok, m in copies if ok and m] or [m for _, m in copies if m][:1]
        for m in best:
            out += m
    kept = [m for m in out if m[3] != "skip"]
    if out and not [m for m in kept if m[3] not in ("glow", "glass")]:
        kept = [m for m in ((g, h, w, name_class(c)) for g, h, w, c in out) if m[3] != "skip"]
    return kept


def ship_model(seed, ship, parts=None, fill=True) -> dict:
    """{"groups": {class: (positions float32 [n,3], indices uint32)}, "bounds": (min, max)} in the game's axes
    (Y up, Z forward). The bounds frame exactly what is drawn, so a single picked part fills the view
    instead of sitting tiny inside the whole ship's footprint."""
    meshes = ship_meshes(seed, ship, parts, fill)
    geos = _geometry(sorted({g for g, *_ in meshes if g}))
    acc: dict = {}
    for g, h, world, cls in meshes:
        m = geos.get(g, {}).get(h)
        if m is None:
            continue
        p = m[0].astype(np.float32)
        p = p @ world[:3, :3].T + world[:3, 3]
        if np.linalg.det(world[:3, :3]) < 0:  # mirrored: keep triangles facing outwards
            idx = m[1].reshape(-1, 3)[:, ::-1].ravel()
        else:
            idx = m[1]
        lst = acc.setdefault(cls, [[], [], 0])
        lst[0].append(p)
        lst[1].append(idx + lst[2])
        lst[2] += len(p)
    groups = {cls: (np.concatenate(v[0]).astype(np.float32), np.concatenate(v[1]).astype(np.uint32))
              for cls, v in acc.items() if v[0]}
    allp = np.concatenate([g[0] for g in groups.values()]) if groups else np.zeros((1, 3), np.float32)
    return {"groups": groups, "bounds": (allp.min(0).tolist(), allp.max(0).tolist())}


def pack(model: dict, colours: dict | None = None) -> bytes:
    """Binary for the viewer: u32 header length, JSON header, then per group float32 xyz and uint32 indices."""
    head, blobs, off = {"bounds": model["bounds"], "colours": colours or {}, "groups": []}, [], 0
    for cls, (p, ix) in model["groups"].items():
        head["groups"].append({"class": cls, "vertices": len(p), "indices": len(ix), "offset": off})
        blobs += [p.tobytes(), ix.tobytes()]
        off += p.nbytes + ix.nbytes
    h = json.dumps(head).encode()
    h += b" " * (-(len(h) + 4) % 4)
    return struct.pack("<I", len(h)) + h + b"".join(blobs)
