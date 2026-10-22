# Ship pose animation: reads the game's .ANIM.MBIN (cTkAnimMetadata) and gives the local
# transform of each posed node at a frame. "Landed" is the ship's own scene, exactly as it is
# drawn today; both poses come from ship_pose(), which reads a deploy anim's first frame for
# parked and its last for flying. See model3d.ship_model(pose=).
#
# Format (verified vs sentineltakeoff.anim.mbin): rotations are 3 int16 per quaternion
# (x,y,z = i16/32767, w = sqrt(max(0, 1-x^2-y^2-z^2))); translations/scales are Vec4f. Each node
# owns one rot/trans/scale channel; the per-frame arrays hold the ANIMATED channels and
# StillFrameData the constant ones, animated indices first (still index = channelIndex - animCount).
from __future__ import annotations

import functools
import os
from typing import NamedTuple

import numpy as np

from nms_save import gamefiles, gamemeta
from nms_save.gamefiles import array, i32, read, vstr

# Which anims take a ship from parked to flying. Most ships have no single "takeoff" -- the gear
# and wings each animate in their own part's anim, and which ones bite depends on the parts the
# seed picked, so every candidate for a ship type is listed and matched to the scene by node name.
# A part the ship does not have simply poses nothing.
#
# Only the MOVEMENT between an anim's first and last frame is used, laid on top of where the scene
# puts the part. An anim frame cannot be used as the pose outright: a mesh is skinned to the pose
# its own scene stores, so a skin matrix has to come out as the identity when nothing is animating,
# and taking the skeleton from the anim instead drags the whole ship out of shape.
#
# `backwards` is for an anim that ends parked rather than starting there.
#
# The shared gun turret anim (shared/weapons/anim/shipgun_takeoff) is deliberately NOT here: its
# nodes do not line up with where any ship's scene puts them -- on all seven types not one of its
# moving nodes agrees -- so it only ever swung the under-wing guns round backwards and down.
_SC = "models/common/spacecraft/"


class Anim(NamedTuple):
    path: str
    backwards: bool = False


SHIP_ANIMS = {
    "sentinel": [Anim(_SC + "sentinelship/anims/sentineltakeoff.anim.mbin")],
    # The sail ship's "takeoff" throws its sail arms right over; its tuck-in, played backwards from
    # stowed, is the one that folds the mast down the way the game flies it.
    "solar": [Anim(_SC + "sailship/sailshipparts/sailshipanims/sailship_tuckin.anim.mbin", backwards=True)],
    "fighter": [Anim(_SC + f"fighters/cockpit/anims/cockpit{c}_landinggear_retract.anim.mbin") for c in "abdef"]
               + [Anim(_SC + "fighters/wings/wings_d/anims/wingd_takeoff.anim.mbin")],
    "explorer": [Anim(_SC + "scientific/accessories/landinggear/anims/landinggear_takeoff.anim.mbin")],
    "shuttle": [Anim(_SC + "shuttle/accessories/anims/landinggear_takeoff.anim.mbin")],
    "exotic": [Anim(_SC + "s-class/royalparts/landinggear/anims/landinggear_a_takeoff.anim.mbin"),
               Anim(_SC + "s-class/squidparts/landinggear/anims/landinggear_a_takeoff.anim.mbin"),
               Anim(_SC + "s-class/squidparts/nosesection/anims/nosesection_a_takeoff.anim.mbin")]
              + [Anim(_SC + f"s-class/royalparts/wings/anims/wings_{w}_takeoff.anim.mbin") for w in "abc"],
}
ANIM_PAK = "NMSARC.AnimMBIN.pak"

# Anims are authored with the axes cycled round (X->Y->Z), so a node that never moves still reads
# as a constant turn. Undoing it turns an anim's transform back into one the scene can use.
AXES = np.eye(4)
AXES[:3, :3] = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float)
UNAXES = AXES.T


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


@functools.lru_cache(maxsize=32)
def ship_pose(ship: str, flying: bool) -> dict:
    """{NODE_NAME_UPPER: 4x4} -- what flying does to each node, as a movement, not a pose.

    An anim stores its nodes in its own axes (a node that never moves still reads as a constant
    turn, the game's X->Y->Z swap), so `last @ inverse(first)` is taken: that cancels the constant
    and leaves only the movement, which is laid on the node's scene transform as `delta @ local`.
    Parked is the scene untouched, so this is empty unless `flying`.
    """
    if not flying:
        return {}
    out: dict = {}
    clash: set = set()
    for a in SHIP_ANIMS.get(ship, []):
        try:
            first, last = pose_locals(a.path, 0), pose_locals(a.path, -1)
        except Exception:  # a part anim this game build does not ship: the rest still works
            continue
        if a.backwards:  # an anim that ends parked: its first frame is the flying one
            first, last = last, first
        for name, a0 in first.items():
            aL = last.get(name)
            if aL is None or np.allclose(a0, aL, atol=1e-6):
                continue  # this node is still for the whole anim: leave the scene alone
            try:
                d = aL @ np.linalg.inv(a0)
            except np.linalg.LinAlgError:
                continue
            was = out.get(name)
            if was is not None and not np.allclose(was, d, atol=1e-6):
                clash.add(name)  # two parts' anims disagree about this node
            out[name] = d
    # A ship carries one of the alternative part sets, not both, and the names repeat between them
    # (two landing gears both calling a node BackLeg2JNT). Guessing tears the ship apart, so a node
    # the candidates disagree about is left where the scene has it.
    for name in clash:
        out.pop(name, None)
    return out


def posable(ship: str) -> bool:
    """True when parking and flying this ship actually look different."""
    return bool(ship_pose(ship, True))
