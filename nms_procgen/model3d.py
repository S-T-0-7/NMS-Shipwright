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
from . import shiptex
from .generator import ROOTS, all_parts, generate

MESH_PAK = "NMSARC.MeshCommon.pak"
MODEL_DIR = os.path.join(gamefiles.CACHE, "models")
FORMAT = 5  # bump when the cached mesh format changes
_LOCK = threading.Lock()

# material file name -> how the viewer shades it
# How the game itself classifies a material (cTkMaterialData.Class). Anything invisible in game
# must stay invisible here, or it shows up as stray dark facets over the hull.
MAT_SKIP = {12: "decal", 14: "mask", 58: "reflection plane", 59: "shadow only", 70: "volume", 71: "volume"}
MAT_GLOW = {2, 9, 10, 18, 19, 22}  # lights, glows and holograms: added on top, never solid
MAT_JET = 2                        # an engine's jet flame, which the scene puts at its nozzle

# The gun turret hangs off a chain of hinge joints the game aims as you fly. It used to be aimed
# here too -- every joint in the chain had its turn replaced with a fixed forward one -- on the
# belief that the scene held the barrels down and back under the wing.
#
# It does not. Laid out as the scene has it, the barrel comes out within 5.5 degrees of the ship's
# nose on every type that carries one, and the mounts that do sit at an angle (the sail ship's,
# 0.7 to 16 degrees) are meant to. Forcing the turn bought about a degree of aim and cost the gun
# its seat: it slid 0.46 forward and 0.12 down, out from under the wing it bolts to, which is why
# the guns looked like they were floating. A second fudge then dropped the whole gun 0.45 to stop
# the first one pushing it up through the wing.
#
# So the chain is left exactly as the scene lays it out. The names are kept only to tell these
# joints apart from a rig the game drives, whose meshes are dropped.
GUN_JOINTS = frozenset({"TURRENTROOT", "TURRETROOT", "TURRETJNT", "TURRETENDJNT",  # the game spells it TURRENTROOT
                        "HINGE1JNT", "HINGE2JNT", "HINGE3JNT"})
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
EFFECTS = re.compile(r"[\\/]SHIELDS[\\/]|ENERGYSHIELD|SHIELDSPHERE|SHIELDIMPACT|PLAYERSHIELD"
                     r"|WARPBUBBLE|FORCEFIELD")  # effect-only shells; not the corvette shield generator


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


NORMAL_SEM = 11  # cTkVertexElement semantic of the packed normal, the data stream's one uint32
UV_SEM = 1       # and of the texture coordinates, which ride in the position stream


def _octa_normals(u) -> np.ndarray:
    """Unit normals from the data stream's uint32 per vertex, octahedron-encoded.

    Two unsigned 10-bit numbers, biased by 512 and scaled by 511, give a point on the octahedron
    |x| + |y| + |z| = 1; the half with z below zero is folded back out to its own face. Read
    against a box, whose faces can only be axis-aligned, all 24 vertices come out as exactly the
    face they belong to, and over two dozen ship parts every vector is unit length and sits a mean
    dot of 0.98 from the normals the triangles imply -- the gap being the authored smoothing that
    averaging faces cannot know about.
    """
    e = (np.stack([u & 0x3FF, (u >> 10) & 0x3FF], 1).astype(np.float64) - 512.0) / 511.0
    x, y = e[:, 0].copy(), e[:, 1].copy()
    z = 1.0 - np.abs(x) - np.abs(y)
    fold = z < 0
    x[fold] = (1.0 - np.abs(e[fold, 1])) * np.sign(e[fold, 0])
    y[fold] = (1.0 - np.abs(e[fold, 0])) * np.sign(e[fold, 1])
    n = np.stack([x, y, z], 1)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, length, out=np.zeros_like(n), where=length > 1e-9).astype(np.float16)


def _mesh_normals(data, start, vsize, stride, offset, verts) -> np.ndarray:
    """One mesh's normals, or nothing if this geometry does not carry them where it should.

    Nothing is not a failure: the viewer works them out from the triangles instead, which is all
    it ever had, so a geometry we cannot read this way draws as it did before.
    """
    if offset is None or not stride or not verts or vsize // stride != verts \
            or offset + 4 > stride:
        return np.zeros((0, 3), np.float16)
    row = np.frombuffer(data, np.uint8, verts * stride, start).reshape(verts, stride)
    return _octa_normals(np.ascontiguousarray(row[:, offset:offset + 4]).view(np.uint32).ravel()
                         .astype(np.int64))


def _convert(geo: bytes, data: bytes) -> dict:
    """{hash: (positions, normals, texture coordinates, indices)} for every mesh of one geometry.

    The position stream is sixteen bytes a vertex: four halves of position and, at offset eight,
    four more that are the texture coordinates. Only the first three were ever read.
    """
    G, MD, VL, VE = _layouts()
    lay = 0x20 + G.off("PositionVertexLayout")
    stride = i32(geo, lay + VL.off("Stride"))
    base, n = array(geo, lay + VL.off("VertexElements"))
    pos_off = next((geo[base + k * VE.size + VE.off("Offset")] for k in range(n)
                    if geo[base + k * VE.size + VE.off("SemanticID")] == 0), 0)
    uv_off = next((geo[base + k * VE.size + VE.off("Offset")] for k in range(n)
                   if geo[base + k * VE.size + VE.off("SemanticID")] == UV_SEM), None)
    wide = not i32(geo, 0x20 + G.off("Indices16Bit"))
    dlay = 0x20 + G.off("VertexLayout")        # the data stream, parallel to the position one
    dstride = i32(geo, dlay + VL.off("Stride"))
    ebase, en = array(geo, dlay + VL.off("VertexElements"))
    nrm_off = next((geo[ebase + k * VE.size + VE.off("Offset")] for k in range(en)
                    if geo[ebase + k * VE.size + VE.off("SemanticID")] == NORMAL_SEM), None)
    out = {}

    def indices(start, size, verts):
        """Index buffer of one mesh. The file's "16 bit" flag is not always right (the sentinel
        ship claims 32 bit and stores 16), so the width that actually fits the mesh wins.

        Fitting is not just a question of range. A mesh with more than 65,536 vertices cannot be
        indexed 16 bits at a time at all, yet reading it that way leaves every index looking in
        range, twice as many triangles as there are, and each one spanning the model: the
        corvette's gun, 68,416 vertices, came out as 188,496 shards instead of 94,248 faces.
        """
        first = np.uint32 if wide else np.uint16
        widths = (np.uint32,) if verts > 65536 else (first, np.uint16 if wide else np.uint32)
        for dtype in widths:
            step = np.dtype(dtype).itemsize
            if size % step or (size // step) % 3:
                continue
            idx = np.frombuffer(data, dtype, size // step, start)
            if not len(idx) or int(idx.max()) < verts:
                return idx.astype(np.uint32)
        step = np.dtype(widths[0]).itemsize
        return np.frombuffer(data, widths[0], size // step, start).astype(np.uint32)
    base, n = array(data, 0x20)
    for k in range(n):
        q = base + k * MD.size
        h = struct.unpack_from("<Q", data, q + MD.off("Hash"))[0]
        vsize, isize = i32(data, q + MD.off("VertexDataSize")), i32(data, q + MD.off("IndexDataSize"))
        ms, _ = array(data, q + MD.off("MeshDataStream"))
        ps, pn = array(data, q + MD.off("MeshPositionDataStream"))
        rows = np.frombuffer(data, np.float16, pn // 2, ps).reshape(-1, stride // 2)
        verts = rows[:, pos_off // 2:pos_off // 2 + 3]
        uv = (rows[:, uv_off // 2:uv_off // 2 + 2] if uv_off is not None
              and uv_off // 2 + 2 <= rows.shape[1] else np.zeros((len(rows), 2), np.float16))
        idx = indices(ms + vsize, isize, len(verts))
        out[h] = (np.ascontiguousarray(verts),
                  _mesh_normals(data, ms, vsize, dstride, nrm_off, len(verts)),
                  np.ascontiguousarray(uv), idx)
    return out


# Decoded meshes, held between requests. Reading them back off disk is most of the cost of
# drawing a ship -- a Fighter's 25 geometries are 1,300-odd arrays, each its own zip entry to
# inflate, and it was happening again for every view. The file's size and date are checked on
# each use, so a re-extract after a game update is picked up without anything to invalidate.
_MESHES: dict = {}


def _cached_meshes(path):
    """The meshes of one geometry file, from memory when the file has not moved under us."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    held = _MESHES.get(path)
    if held and held[0] == stamp:
        return held[1]
    try:
        with np.load(path) as z:
            if int(z["format"]) != FORMAT:
                return None
            meshes = {int(h): (z[f"p{i}"], z[f"n{i}"], z[f"t{i}"], z[f"i{i}"])
                      for i, h in enumerate(z["hashes"])}
    except Exception:   # see _geometry: a file that will not open is read again from the pak
        return None
    if len(_MESHES) > 400:        # a few hundred geometries covers every ship type at once
        _MESHES.clear()
    _MESHES[path] = (stamp, meshes)
    return meshes


def _geometry(geometries) -> dict:
    """{geometry path: {hash: (positions, normals, uv, indices)}}, converting what is missing."""
    gameversion.check()  # a game update throws the converted meshes away
    result, missing = {}, []
    for g in geometries:
        # A cache file that will not open -- cut short by a full disk, a crash while it was being
        # written, or the game being updated underneath us -- is no reason to fail the whole ship.
        # It goes back on the list and is read from the pak again, over the top of the bad copy.
        meshes = _cached_meshes(_cache_file(g))
        if meshes is not None:
            result[g] = meshes
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
                for i, (p, nr, uv, ix) in enumerate(meshes.values()):
                    arrays[f"p{i}"], arrays[f"n{i}"] = p, nr
                    arrays[f"t{i}"], arrays[f"i{i}"] = uv, ix
                np.savez_compressed(path, **arrays)
                _MESHES.pop(path, None)
                result[g] = meshes
    return result


# ------------------------------------------------------------------- scenes --

def _matrix(t) -> np.ndarray:
    """cTkTransformData (rot degrees XYZ, scale, translation) -> 4x4.

    The rotation goes Y, then X, then Z. Read off the game's own data rather than guessed:
    a deploy anim stores the same joints as matrices, and where its first frame is the rest
    pose the two must agree. Of the six orders only this one does -- on the explorer's gear
    rig, 7 joints turning about more than one axis, to 1e-4, and on the Sentinel's takeoff,
    23 joints, to 6e-3. Z @ Y @ X, which this used to do, is out by a half turn on both.
    A joint turning about one axis reads the same whatever the order, which is why most of
    a ship looked right regardless and only the multi-axis rigs came out wrong.
    """
    rx, ry, rz = np.radians(t[0:3])
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = Y @ X @ Z @ np.diag(t[3:6])
    m[:3, 3] = t[6:9]
    return m


def _local(name, t, pose):
    """A node's local transform, with the flying pose's movement on it (see anim.ship_pose)."""
    m = _matrix(t)
    d = pose.get(name.upper()) if pose else None
    return d @ m if d is not None else m


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


@functools.lru_cache(maxsize=512)
def _skinned(geometry: str) -> bool:
    """Does this geometry have a skin? If not, its nodes are what place it."""
    try:
        geo = (_extract([geometry]).get(geometry) or {}).get("geo")
        if not geo:
            return False
        G, _, _, _ = _layouts()
        return bool(array(geo, 0x20 + G.off("SkinMatrixLayout"))[1])
    except Exception:
        return False


_TRUNC_LEN = 15


def _canon(up, options, trunc):
    if up in options:
        return up
    for o in trunc:
        if up.startswith(o):
            return o
    return up


SPECIAL_SCENES = {"starborn_phoenix": "MODELS/COMMON/SPACECRAFT/FIGHTERS/WRACERSE.SCENE.MBIN"}


SNAP_NAME = re.compile(r"^(.*?)_(In|Out)_?$")


def snap_points(root) -> list:
    """[(kind, "in"/"out", 4x4 matrix)] for the sockets a placement scene offers.

    The game's own joins are these: a part's `X_In_` locator is laid exactly onto another part's
    `X_Out_` locator of the same kind, frame for frame. Measured against a ship built in game,
    all 43 joined pairs sat within a ten-thousandth of a unit of each other, and 42 of them had
    the two frames in the same orientation, so there is no flip to apply -- the one that differed
    is a part turned half round on a symmetric socket.

    The locators hang under nodes named SnapPoint*, often reached through a REFERENCE to a shared
    snappoints scene rather than sitting in the placement scene itself.
    """
    scene = _parsed(root)
    if not scene:
        return []
    out = []

    def walk(n, world, under, depth):
        typ, name, t, attrs, children = n
        world = world @ _matrix(t)
        if typ == "LOCATOR" and name.upper().startswith("SNAPPOINT"):
            under = True
        if typ == "REFERENCE" and attrs.get("SCENEGRAPH") and depth < 5:
            sub = _parsed(_scene_path(attrs["SCENEGRAPH"]))
            if sub:
                walk(sub[1], world, under, depth + 1)
            return
        hit = SNAP_NAME.match(name)
        if typ == "LOCATOR" and under and hit:
            out.append((hit.group(1), hit.group(2).lower(), world.copy()))
        for c in children:
            walk(c, world, under, depth + 1)
    walk(scene[1], np.eye(4), False, 0)
    return out


def _scene_meshes(root, pose=None):
    scene = _parsed(root)
    if not scene:
        raise FileNotFoundError(f"scene {root} not found")
    out = []

    def walk(n, geometry, world, posed, depth):
        typ, name, t, attrs, children = n
        if depth > 12:
            return
        world = world @ _matrix(t)
        posed = posed @ _local(name, t, pose)
        if typ == "MESH":
            suffix = LOD_SUFFIX.search(name)
            if attrs.get("LODLEVEL", "0") != "0" or (suffix and suffix.group(1) != "0"):
                return
            if attrs.get("HASH") and not EFFECTS.search(geometry.upper()):
                out.append((geometry, int(attrs["HASH"]), world, mat_class(attrs.get("MATERIAL", "")),
                            posed, int(attrs.get("FIRSTSKINMAT") or 0),
                            shiptex.colour_map(attrs.get("MATERIAL", ""))))
        elif typ == "REFERENCE" and attrs.get("SCENEGRAPH"):
            sub = _parsed(_scene_path(attrs["SCENEGRAPH"]))
            if sub:
                walk(sub[1], sub[0], world, posed, depth + 1)
        elif typ in ("COLLISION", "LIGHT", "EMITTER"):
            return
        for c in children:
            walk(c, geometry, world, posed, depth)
    walk(scene[1], scene[0], np.eye(4), np.eye(4), 0)
    kept = [m for m in out if m[3] != "skip"]
    if out and not [m for m in kept if m[3] not in ("glow", "glass")]:
        kept = [(g, h, w, name_class(c), q, f, x) for g, h, w, c, q, f, x in out
                if name_class(c) != "skip"]
    return kept


def ship_meshes(seed, ship, parts=None, fill=True, pose=None, joints=frozenset(), collect=None):
    if ship in SPECIAL_SCENES:
        return _scene_meshes(SPECIAL_SCENES[ship], pose)
    """[(geometry path, hash, 4x4 world matrix, material class, under a joint)] for `seed`'s parts.

    A mesh "under a joint" hangs off the skeleton, so the deploy moves it bodily and it must not
    also be skinned; everything else is placed by its own node and bends with the skin instead.

    With `parts` (the Designer's picks) and `fill`, the rest of the ship is filled in with the first
    option of every group the picks do not cover, so a half-finished design shows as a whole ship.
    Without `fill` only the picked parts are drawn: the ship is built up piece by piece.
    """
    if parts is not None and not fill:
        return _picked_meshes(ship, {p.upper() for p in parts}, pose, joints, collect)
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

    def walk(n, geometry, world, posed, depth, rig):
        typ, name, t, attrs, children = n
        if not keep(name) or depth > 12:
            return
        gun = typ == "JOINT" and name.upper() in GUN_JOINTS
        rig = rig or (typ == "JOINT" and not gun and name.upper() not in joints and _skinned(geometry))
        if collect is not None:
            collect.setdefault(name.upper(), []).append(_matrix(t))
        world = world @ _matrix(t)
        posed = posed @ _local(name, t, pose)
        if typ == "MESH":
            # Lower-detail copies sit inside the full-detail mesh and poke through it. Some of them
            # claim LODLEVEL 0, so the name (...LOD2) decides as well.
            suffix = LOD_SUFFIX.search(name)
            if attrs.get("LODLEVEL", "0") != "0" or (suffix and suffix.group(1) != "0"):
                return
            cls = mat_class(attrs.get("MATERIAL", ""))
            if rig and _material_class(attrs.get("MATERIAL", ""))[0] != MAT_JET:
                return  # a rig the game drives: only its jet still belongs where it is: only the jet still belongs where the scene put it
            if attrs.get("HASH") and not EFFECTS.search(geometry.upper()):
                out.append((geometry, int(attrs["HASH"]), world, cls, posed,
                            int(attrs.get("FIRSTSKINMAT") or 0),
                            shiptex.colour_map(attrs.get("MATERIAL", ""))))
        elif typ == "REFERENCE" and attrs.get("SCENEGRAPH"):
            sub = _parsed(_scene_path(attrs["SCENEGRAPH"]))
            if sub:
                walk(sub[1], sub[0], world, posed, depth + 1, rig)
        elif typ in ("COLLISION", "LIGHT", "EMITTER"):
            return
        if designing and children:
            fill_defaults(children)
        for c in children:
            walk(c, geometry, world, posed, depth, rig)
    root = "MODELS/" + ROOTS[ship][len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
    scene = _parsed(root)
    if not scene:
        raise FileNotFoundError(f"scene {root} not found")
    walk(scene[1], scene[0], np.eye(4), np.eye(4), 0, False)
    kept = [m for m in out if m[3] != "skip"]
    # Never hide the ship: if the material files say almost everything is invisible, they were
    # unreadable (a game update, or a half-finished copy), so fall back to the names alone.
    solid = [m for m in kept if m[3] not in ("glow", "glass")]
    if not solid and out:
        kept = [(g, h, w, name_class(c), q, f, x) for g, h, w, c, q, f, x in out]
        kept = [m for m in kept if m[3] != "skip"]
    return kept


def _picked_meshes(ship, chosen, pose=None, joints=frozenset(), collect=None):
    """Only the picked parts, placed where they sit on a finished ship.

    A picked part can sit inside a part that is not picked (a cockpit inside a hull option), so
    unpicked options are still walked for their transforms, they just draw nothing themselves.
    When a part appears under several parents, the copy under picked parents wins.
    """
    options = {p for ps in all_parts(ship).values() for p in ps}
    trunc = sorted((o for o in options if len(o) >= _TRUNC_LEN), key=len, reverse=True)
    lod = re.compile(r"LOD\d$")
    found: dict = {}  # part -> [(parents all picked, meshes)]

    def walk(n, geometry, world, posed, depth, owner, ok, rig):
        typ, name, t, attrs, children = n
        if depth > 12:
            return
        gun = typ == "JOINT" and name.upper() in GUN_JOINTS
        rig = rig or (typ == "JOINT" and not gun and name.upper() not in joints and _skinned(geometry))
        if collect is not None:
            collect.setdefault(name.upper(), []).append(_matrix(t))
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
        posed = posed @ _local(name, t, pose)
        if typ == "MESH":
            suffix = LOD_SUFFIX.search(name)
            if attrs.get("LODLEVEL", "0") != "0" or (suffix and suffix.group(1) != "0"):
                return
            if rig and _material_class(attrs.get("MATERIAL", ""))[0] != MAT_JET:
                return  # a rig the game drives: only its jet still belongs where it is
            if owner is not None and attrs.get("HASH") and not EFFECTS.search(geometry.upper()):
                owner.append((geometry, int(attrs["HASH"]), world,
                              mat_class(attrs.get("MATERIAL", "")), posed,
                              int(attrs.get("FIRSTSKINMAT") or 0),
                              shiptex.colour_map(attrs.get("MATERIAL", ""))))
        elif typ == "REFERENCE" and attrs.get("SCENEGRAPH"):
            sub = _parsed(_scene_path(attrs["SCENEGRAPH"]))
            if sub:
                walk(sub[1], sub[0], world, posed, depth + 1, owner, ok, rig)
        elif typ in ("COLLISION", "LIGHT", "EMITTER"):
            return
        for c in children:
            walk(c, geometry, world, posed, depth, owner, ok, rig)
    root = "MODELS/" + ROOTS[ship][len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
    scene = _parsed(root)
    if not scene:
        raise FileNotFoundError(f"scene {root} not found")
    base: list = []  # fixed pieces no option owns (cockpit lid, landing gear, guns)
    walk(scene[1], scene[0], np.eye(4), np.eye(4), 0, base, True, False)
    out = [m for m in base if m[3] != "glow"] if chosen else []
    for copies in found.values():
        best = [m for ok, m in copies if ok and m] or [m for _, m in copies if m][:1]
        for m in best:
            out += m
    kept = [m for m in out if m[3] != "skip"]
    if out and not [m for m in kept if m[3] not in ("glow", "glass")]:
        kept = [m for m in ((g, h, w, name_class(c), q, f, x) for g, h, w, c, q, f, x in out)
                if m[3] != "skip"]
    return kept


def _turn_normals(nrm, frame) -> np.ndarray:
    """Carry normals through a part's transform.

    A normal does not ride a matrix the way a position does. Half of a ship's parts are the other
    half mirrored, and under a mirror (or any squash) only the inverse keeps a normal at right
    angles to its surface -- multiplying it like a point tilts it, and the light slides off the
    panel it belongs to.
    """
    if not len(nrm):
        return nrm
    try:
        back = np.linalg.inv(frame[:3, :3])
    except np.linalg.LinAlgError:
        back = frame[:3, :3].T
    n = nrm.astype(np.float64) @ back
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, length, out=np.zeros_like(n), where=length > 1e-9).astype(np.float32)


def _gather(acc, key, pos, nrm, uv, idx, frame):
    """Add one placed mesh to its group, turning the triangles back out if it is mirrored.

    A group is one shading class painted by one texture. A ship has far fewer textures than
    materials -- 25 on a Fighter, 7 on a Sentinel -- so this stays a couple of dozen groups.
    """
    if len(nrm) != len(pos):          # a geometry whose normals we could not read: let the
        nrm = np.zeros_like(pos)      # viewer work them out from the triangles, as it used to
    if len(uv) != len(pos):
        uv = np.zeros((len(pos), 2), np.float32)
    lst = acc.setdefault(key, [[], [], [], [], 0])
    lst[0].append(pos.astype(np.float32))
    lst[1].append(nrm.astype(np.float32))
    lst[2].append(uv.astype(np.float32))
    lst[3].append((idx.reshape(-1, 3)[:, ::-1].ravel() if np.linalg.det(frame[:3, :3]) < 0 else idx)
                  + lst[4])
    lst[4] += len(pos)


def _collected(acc) -> dict:
    return {key: (np.concatenate(v[0]).astype(np.float32), np.concatenate(v[1]).astype(np.float32),
                  np.concatenate(v[2]).astype(np.float32), np.concatenate(v[3]).astype(np.uint32))
            for key, v in acc.items() if v[0]}


def ship_model(seed, ship, parts=None, fill=True, flying=False) -> dict:
    """{"groups": {class: (positions float32 [n,3], indices uint32)}, "bounds": (min, max)} in the game's axes
    (Y up, Z forward). The bounds frame exactly what is drawn.

    `flying` flies the ship instead of parking it: parts hung off the skeleton are carried by
    their joint, and skinned parts are bent by it."""
    from . import anim
    # One pass to see which parts this ship actually carries, so an anim is judged only against
    # those, then the real pass with the pose that comes out of it.
    here: dict = {}
    ship_meshes(seed, ship, parts, fill, None, frozenset(), here)
    flown = anim.ship_pose(ship, True, here)
    joints = anim.driven(ship, here)
    pose = flown if flying else None
    meshes = ship_meshes(seed, ship, parts, fill, pose, joints)
    geos = _geometry(sorted({g for g, *_ in meshes if g}))
    bend: dict = {}
    if pose:
        from . import skin
        bend = {g: skin.prepare(g, pose) for g in geos}
    acc, drawn = {}, set()
    for g, h, world, cls, posed, first, tex in meshes:
        m = geos.get(g, {}).get(h)
        if m is None:
            continue
        # On a skinned part the skeleton does all the moving, so the mesh keeps the place its scene
        # gives it and the skin bends it. A part with no skeleton is carried by its nodes instead,
        # which is where the gear, guns and sail arms hanging off a joint get their movement.
        skinned = bend.get(g) is not None
        frame = world if skinned else posed
        # The same mesh at the same frame twice comes out of the game's own data -- a freighter's
        # cargo scene lists two of its containers at one spot -- and drawing it twice only leaves
        # the two of them fighting over which is in front.
        once = (g, h, frame.round(4).tobytes())
        if once in drawn:
            continue
        drawn.add(once)
        p, nrm = m[0].astype(np.float32), m[1]
        if skinned:
            p = skin.deform(bend[g], h, p, first).astype(np.float32)
            nrm = skin.deform_normals(bend[g], h, nrm, first)
        _gather(acc, (cls, tex), p @ frame[:3, :3].T + frame[:3, 3],
                _turn_normals(nrm, frame), m[2], m[3], frame)
    groups = _collected(acc)
    allp = np.concatenate([g[0] for g in groups.values()]) if groups else np.zeros((1, 3), np.float32)
    return {"groups": groups, "bounds": (allp.min(0).tolist(), allp.max(0).tolist()),
            "posable": bool(flown)}  # offers a landed/flying toggle


def _placement(position, up, at) -> np.ndarray:
    """A module's own frame, from the Up and At the save stores for it."""
    up, at = np.asarray(up, np.float64), np.asarray(at, np.float64)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2] = np.cross(up, at), up, at
    m[:3, 3] = position
    return m


def corvette_model(modules) -> dict:
    """{"groups", "bounds"} for a built corvette, shaped like ship_model's.

    `modules` is (scene, position, up, at) per module, as the save stores them. A module goes
    exactly where its transform puts it: nothing is snapped, and a module whose scene is
    missing is left out rather than taking the rest of the ship down with it.
    """
    placed = [(scene, _placement(pos, up, at)) for scene, pos, up, at in modules]
    scenes = {}
    for scene, _ in placed:
        if scene not in scenes:
            try:
                scenes[scene] = _scene_meshes(scene)
            except FileNotFoundError:
                scenes[scene] = []
    geos = _geometry(sorted({g for ms in scenes.values() for g, *_ in ms if g}))
    acc, drawn = {}, set()
    for scene, place in placed:
        for g, h, world, cls, _, _, tex in scenes[scene]:
            m = geos.get(g, {}).get(h)
            if m is None:
                continue
            w = place @ world
            once = (g, h, w.round(4).tobytes())
            if once in drawn:  # see ship_model: the game's own data repeats a mesh here and there
                continue
            drawn.add(once)
            _gather(acc, (cls, tex), m[0].astype(np.float32) @ w[:3, :3].T + w[:3, 3],
                    _turn_normals(m[1], w), m[2], m[3], w)
    groups = _collected(acc)
    allp = np.concatenate([g[0] for g in groups.values()]) if groups else np.zeros((1, 3), np.float32)
    return {"groups": groups, "bounds": (allp.min(0).tolist(), allp.max(0).tolist()), "posable": False}


def pack(model: dict, colours: dict | None = None) -> bytes:
    """Binary for the viewer: u32 header length, JSON header, then per group float32 xyz
    positions, float32 xyz normals, float32 uv and uint32 indices."""
    head = {"bounds": model["bounds"], "colours": colours or {}, "posable": model.get("posable", False), "groups": []}
    blobs, off = [], 0
    for key, (p, nrm, uv, ix) in model["groups"].items():
        cls, tex = key if isinstance(key, tuple) else (key, "")
        head["groups"].append({"class": cls, "tex": tex, "vertices": len(p),
                               "indices": len(ix), "offset": off})
        blobs += [p.tobytes(), nrm.tobytes(), uv.tobytes(), ix.tobytes()]
        off += p.nbytes + nrm.nbytes + uv.nbytes + ix.nbytes
    h = json.dumps(head).encode()
    h += b" " * (-(len(h) + 4) % 4)
    return struct.pack("<I", len(h)) + h + b"".join(blobs)
