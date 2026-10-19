# Ship pose animation: reads the game's .ANIM.MBIN (cTkAnimMetadata) and gives the local
# transform of each posed node at a frame. "Flight" = the last frame of a ship's takeoff anim,
# "landed" = the ship's default scene pose (no override). See model3d.pose_model().
#
# Format (verified vs sentineltakeoff.anim.mbin): rotations are 3 int16 per quaternion
# (x,y,z = i16/32767, w = sqrt(max(0, 1-x^2-y^2-z^2))); translations/scales are Vec4f. Each node
# owns one rot/trans/scale channel; the per-frame arrays hold the ANIMATED channels and
# StillFrameData the constant ones, animated indices first (still index = channelIndex - animCount).
from __future__ import annotations

import functools
import os

import numpy as np

from nms_save import gamefiles, gamemeta
from nms_save.gamefiles import array, i32, read, vstr

# ship type -> (anim folder relative to the ship root, takeoff anim file). Flight pose is this
# anim's last frame; landed is the untouched scene. Only ships with a real deploy need an entry.
TAKEOFF = {
    "sentinel": "models/common/spacecraft/sentinelship/anims/sentineltakeoff.anim.mbin",
    "solar": "models/common/spacecraft/sailship/sailshipparts/sailshipanims/sailship_takeoff.anim.mbin",
}
ANIM_PAK = "NMSARC.AnimMBIN.pak"


@functools.lru_cache(maxsize=1)
def _layouts():
    m = gamemeta.exe_meta()
    meta = m.layout("cTkAnimMetadata")
    node = m.layout("cTkAnimNodeData")
    frame = m.layout("cTkAnimNodeFrameData")
    return meta, node, frame


def _frame_channels(b, off, frame_lay):
    """(rotations [n,3] int16, scales [n,3] float, translations [n,3] float) of one frame block."""
    rb, rn = array(b, off + frame_lay.off("Rotations"))
    sb, sn = array(b, off + frame_lay.off("Scales"))
    tb, tn = array(b, off + frame_lay.off("Translations"))
    rot = np.frombuffer(b, np.int16, rn, rb).reshape(-1, 3) if rn else np.zeros((0, 3), np.int16)
    scl = np.frombuffer(b, np.float32, sn * 4, sb).reshape(-1, 4)[:, :3] if sn else np.zeros((0, 3), np.float32)
    trs = np.frombuffer(b, np.float32, tn * 4, tb).reshape(-1, 4)[:, :3] if tn else np.zeros((0, 3), np.float32)
    return rot, scl, trs


def _quat_to_m3(q):
    """Unit quaternion (x,y,z,w) -> 3x3 rotation (column-vector convention, matching model3d)."""
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


@functools.lru_cache(maxsize=8)
def pose_locals(anim_path: str, frame: int = -1) -> dict:
    """{NODE_NAME_UPPER: 4x4 local transform} for each node the anim poses, at `frame`
    (-1 = last). Nodes not in the dict keep their scene transform."""
    full = _extract_anim(anim_path)
    if not full:
        return {}
    b = read(full)
    meta, node_lay, frame_lay = _layouts()
    R = 0x20
    frame_count = i32(b, R + meta.off("FrameCount"))
    node_count = i32(b, R + meta.off("NodeCount"))
    f = frame_count - 1 if frame < 0 else max(0, min(frame, frame_count - 1))

    srot, sscl, strs = _frame_channels(b, R + meta.off("StillFrameData"), frame_lay)
    afb, afn = array(b, R + meta.off("AnimFrameData"))
    arot, ascl, atrs = _frame_channels(b, afb + f * frame_lay.size, frame_lay) if afn else (srot[:0], sscl[:0], strs[:0])
    n_arot, n_ascl, n_atrs = len(arot), len(ascl), len(atrs)

    def rot(idx):
        r = arot[idx] if idx < n_arot else srot[idx - n_arot]
        xyz = r.astype(np.float64) / 32767.0
        w = np.sqrt(max(0.0, 1.0 - float(xyz @ xyz)))
        return _quat_to_m3((xyz[0], xyz[1], xyz[2], w))

    def vec(idx, anim, still, n_anim, default):
        if idx < n_anim:
            return anim[idx]
        j = idx - n_anim
        return still[j] if j < len(still) else default

    nd_base, nd_n = array(b, R + meta.off("NodeData"))
    out = {}
    for k in range(min(nd_n, node_count)):
        o = nd_base + k * node_lay.size
        name = vstr(b, o + node_lay.off("Node")).upper()
        ri, si, ti = (i32(b, o + node_lay.off(x)) for x in ("RotIndex", "ScaleIndex", "TransIndex"))
        m = np.eye(4)
        m[:3, :3] = rot(ri) @ np.diag(vec(si, ascl, sscl, n_ascl, np.ones(3)))
        m[:3, 3] = vec(ti, atrs, strs, n_atrs, np.zeros(3))
        out[name] = m
    return out


def _extract_anim(rel_path: str):
    """Pull one .anim.mbin out of the anim pak; returns the on-disk path or None."""
    from nms_save.gamefiles import CACHE
    dest = os.path.join(CACHE, "anims")
    folder = gamefiles.extract(dest, [rel_path], ANIM_PAK, keep_dirs=True)
    full = os.path.join(folder, *rel_path.split("/"))
    return full if os.path.exists(full) else None


def flight_pose(ship: str) -> dict:
    """{NODE_NAME_UPPER: local 4x4} for the flying pose, or {} if this ship has no deploy anim."""
    rel = TAKEOFF.get(ship)
    return pose_locals(rel, -1) if rel else {}
