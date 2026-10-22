# Posed ship geometry: CPU skinning so a ship can be drawn flying as well as landed.
#
# A skinned part stores every vertex in the scene's bind pose -- the landed ship. anim.ship_pose
# says where the deploy puts each joint; walking the part's own scene (its .SCENE.MBIN, where the
# JOINT nodes live) with that movement applied gives every joint a bind and a posed world matrix in
# the part's model space. Skinning a vertex by sum_i weight_i * (posed_i @ inverse(bind_i)) bends
# the landed mesh into the flying one.
#
# Everything is matched by number, not by guesswork:
#  * Each scene JOINT carries JOINTINDEX, and cTkGeometryData.SkinMatrixLayout holds those same
#    numbers, so a skin matrix resolves to its joint exactly. (The geometry's JointBindings carry
#    no names and their inverse-bind matrices are stored row-major; matching on those geometrically
#    collapses half the skeleton onto the root, so they are not used at all.)
#  * Which slice of SkinMatrixLayout a mesh uses is FIRSTSKINMAT on its SCENE node, not
#    cTkGeometryData.MeshBaseSkinMat, which is a different and longer list.
#
# Vertices carry four blend indices (vertex semantic 5, bytes) into that slice and four weights
# (semantic 6, half floats). Anything unreadable falls back to the rigid mesh, so a posed render
# never fails where the landed one would not.
from __future__ import annotations

import struct

import numpy as np

from nms_save.gamefiles import array, i32

BLEND_INDEX, BLEND_WEIGHT = 5, 6  # cTkVertexElement SemanticIDs in the skinned (data) stream


def _joint_worlds(scene_path: str, pose: dict) -> dict:
    """{JOINTINDEX: (bind 4x4, posed 4x4)} in this part's model space (its scene from identity)."""
    from . import model3d
    sc = model3d._parsed(scene_path)
    if not sc:
        return {}
    out: dict = {}

    def walk(n, wb, wp, depth):
        typ, name, t, attrs, children = n
        if depth > 14:
            return
        wb = wb @ model3d._matrix(t)
        wp = wp @ model3d._local(name, t, pose)  # the deploy's movement on top of the bind local
        if typ == "JOINT" and attrs.get("JOINTINDEX"):
            try:
                out.setdefault(int(attrs["JOINTINDEX"]), (wb, wp))
            except ValueError:
                pass
        if typ == "REFERENCE" and attrs.get("SCENEGRAPH"):
            sub = model3d._parsed(model3d._scene_path(attrs["SCENEGRAPH"]))
            if sub:
                walk(sub[1], wb, wp, depth + 1)
        for c in children:
            walk(c, wb, wp, depth)
    walk(sc[1], np.eye(4), np.eye(4), 0)
    return out


def prepare(geo_path: str, pose: dict):
    """Everything needed to bend one geometry into `pose`, or None if nothing on it moves."""
    from . import model3d
    try:
        raw = model3d._extract([geo_path]).get(geo_path) or {}
        geo, data = raw.get("geo"), raw.get("data")
        if not geo or not data:
            return None
        G, MD, VL, VE = model3d._layouts()
        R = 0x20
        sb, sn = array(geo, R + G.off("SkinMatrixLayout"))
        if not sn:
            return None  # not a skinned part: its nodes carry it instead
        joints = _joint_worlds(geo_path.replace(".GEOMETRY.MBIN", ".SCENE.MBIN"), pose)
        if not joints:
            return None
        # One skin matrix per slot of SkinMatrixLayout, each resolved through its JOINTINDEX.
        slots = np.zeros((sn, 4, 4))
        moved = False
        for p in range(sn):
            found = joints.get(i32(geo, sb + p * 4))
            m = np.eye(4)
            if found is not None:
                wb, wp = found
                try:
                    m = wp @ np.linalg.inv(wb)
                    moved = moved or np.abs(m - np.eye(4)).max() > 1e-9
                except np.linalg.LinAlgError:
                    m = np.eye(4)
            slots[p] = m
        if not moved:
            return None
        lay = R + G.off("VertexLayout")
        stride = i32(geo, lay + VL.off("Stride"))
        eb, en = array(geo, lay + VL.off("VertexElements"))
        sem = {geo[eb + k * VE.size + VE.off("SemanticID")]: geo[eb + k * VE.size + VE.off("Offset")]
               for k in range(en)}
        if BLEND_INDEX not in sem or BLEND_WEIGHT not in sem:
            return None
        blend = {}
        mbase, mn = array(data, 0x20)
        for k in range(mn):
            q = mbase + k * MD.size
            h = struct.unpack_from("<Q", data, q + MD.off("Hash"))[0]
            ms, _ = array(data, q + MD.off("MeshDataStream"))
            nv = i32(data, q + MD.off("VertexDataSize")) // stride
            if nv <= 0:
                continue
            ds = np.frombuffer(data, np.uint8, nv * stride, ms).reshape(nv, stride)
            w = ds[:, sem[BLEND_WEIGHT]:sem[BLEND_WEIGHT] + 8].copy().view(np.float16).astype(np.float64)
            s = w.sum(1, keepdims=True)
            blend[h] = (ds[:, sem[BLEND_INDEX]:sem[BLEND_INDEX] + 4].astype(np.int64),
                        np.divide(w, s, out=np.zeros_like(w), where=s > 0), s[:, 0] > 0)
        return {"slots": slots, "blend": blend}
    except Exception:  # a posed render must never fail where the landed one would not
        return None


def deform(ctx, mesh_hash: int, pos, first_skin_mat: int):
    """Bend one mesh's positions into the pose; returns them unchanged if it cannot be skinned."""
    if not ctx:
        return pos
    try:
        found = ctx["blend"].get(mesh_hash)
        if not found:
            return pos
        bidx, w, weighted = found
        if len(bidx) != len(pos):  # cached positions and this stream disagree: leave it rigid
            return pos
        slots = ctx["slots"]
        p = np.asarray(pos, np.float64)
        vh = np.concatenate([p, np.ones((len(p), 1))], 1)
        acc = np.zeros((len(p), 3))
        for inf in range(4):
            m = slots[np.clip(first_skin_mat + bidx[:, inf], 0, len(slots) - 1)]
            acc += w[:, inf:inf + 1] * np.einsum("nij,nj->ni", m, vh)[:, :3]
        out = p.copy()
        out[weighted] = acc[weighted]  # unweighted vertices keep their landed position
        return out.astype(np.float32)
    except Exception:
        return pos
