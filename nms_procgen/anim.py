# Ship pose animation: reads the game's .ANIM.MBIN (cTkAnimMetadata) and gives the local
# transform of each posed node at a frame. One of the two states is the ship's own scene, exactly
# as it is drawn today, and the other is reached by a movement out of a deploy anim -- its first
# frame against its last. For almost every type the scene is the parked ship and the movement
# flies it; the sail ship is modelled flying, so for it the movement lands it instead (see
# SCENE_IS_FLYING). Both come from ship_pose(). See model3d.ship_model(pose=).
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
# An anim's first frame is the ship parked and its last is it flying, and a frame gives a node's
# transform outright, so it replaces the one the scene holds. The two line up: of the Sentinel's
# 231 posed nodes, 221 start exactly where its scene puts them.
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
    # The sail ship is the one type modelled flying: its scene has the mast up and the sails out,
    # which is why it alone hung 3.5 below the ground "landed" while every other type rests at 0.
    # So its movement is the landing, and three separate anims agree on where that ends -- unfold
    # the sails, go to low flight, or stand in the customiser, each played backwards from the
    # scene, and all three put the hull on the ground at 0.03 and fold it from 14.1 high to 3.4.
    # All three are listed because they corroborate each other rather than divide the work: the
    # best fit claims each joint first and the others agree with it. The sail ship's own part
    # anims (sailship_shared, sailshipsail_*, sailshiptips_*) are deliberately left out -- they
    # fit 0.66 backwards and add 2 joints, but those 2 put the hull 0.98 below the ground.
    "solar": [Anim(_SC + f"sailship/sailshipparts/sailshipanims/sailship_{n}.anim.mbin", backwards=True)
              for n in ("cutomiser", "lowflight", "sailsunfold")],
    "fighter": [Anim(_SC + f"fighters/cockpit/anims/cockpit{c}_landinggear_retract.anim.mbin") for c in "abdef"]
               + [Anim(_SC + "fighters/wings/wings_d/anims/wingd_takeoff.anim.mbin")],
    "explorer": [Anim(_SC + "scientific/accessories/landinggear/anims/landinggear_takeoff.anim.mbin")],
    "shuttle": [Anim(_SC + "shuttle/accessories/anims/landinggear_takeoff.anim.mbin")],
    # The hauler's gear is one fixed accessory, front and rear, and each end animates on its own.
    # Both anims also carry a second rig for the same legs under other names (LANDINGGEAR1_R beside
    # LGROOT_R, REARFLAP1 beside FLAP_R); those are the joints the pivot check below throws out.
    "hauler": [Anim(_SC + f"dropships/accessories/landinggear/anims/landinggear{e}_takeoff.anim.mbin")
               for e in ("front", "rear")],
    # bioshiptakeoff is 501 frames that start and end in the same pose, so it is no use for this --
    # the landing, played backwards, is where the bio ship's legs actually fold.
    "living": [Anim(_SC + "s-class/bioparts/anims/bioshiplanding.anim.mbin", backwards=True)],
    # Unresolved, and long-standing: on a seed carrying WINGS_A, the
    # wings_a takeoff fits perfectly -- both its joints are on the ship and their rest poses match
    # the scene to 0.00 -- and then turns each wing 165 degrees, from standing up to hanging under
    # the hull, so from above the ship has no wings at all. Left as the game's own data has it
    # rather than guessed at, but it is the one pose here that does not look like a ship flying.
    "exotic": [Anim(_SC + "s-class/royalparts/landinggear/anims/landinggear_a_takeoff.anim.mbin"),
               Anim(_SC + "s-class/squidparts/landinggear/anims/landinggear_a_takeoff.anim.mbin"),
               Anim(_SC + "s-class/squidparts/nosesection/anims/nosesection_a_takeoff.anim.mbin"),
               Anim(_SC + "s-class/royalparts/engine/anims/engine_c_takeoff.anim.mbin"),
               Anim(_SC + "s-class/squidparts/engine/anims/engine_a_takeoff.anim.mbin")]
              + [Anim(_SC + f"s-class/royalparts/wings/anims/wings_{w}_takeoff.anim.mbin") for w in "abc"],
    # Freighters have no landed state to take: the game ships no takeoff or landing anim anywhere
    # under industrial/, because they never set down.
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
    """(rotations [n,3] packed uint16, scales [n,3] float, translations [n,3] float) of a frame."""
    rb, rn = array(b, off + frame_lay.off("Rotations"))
    sb, sn = array(b, off + frame_lay.off("Scales"))
    tb, tn = array(b, off + frame_lay.off("Translations"))
    # The list counts uint16s and a quaternion packs into three of them.
    rot = np.frombuffer(b, np.uint16, rn, rb).reshape(-1, 3) if rn else np.zeros((0, 3), np.uint16)
    scl = np.frombuffer(b, np.float32, sn * 4, sb).reshape(-1, 4)[:, :3] if sn else np.zeros((0, 3), np.float32)
    trs = np.frombuffer(b, np.float32, tn * 4, tb).reshape(-1, 4)[:, :3] if tn else np.zeros((0, 3), np.float32)
    return rot, scl, trs


def _unpack_quat(c):
    """One packed rotation -> (x, y, z, w).

    Quaternions are stored "smallest three": the largest component is left out and rebuilt from
    the others, since a unit quaternion's parts square to 1. Three uint16 hold the ones that were
    kept, each scaled to +/-1/sqrt(2) (the biggest the smallest component can be), and the top bit
    of the first two says which one was dropped, so the rebuilt value goes back in its own place.
    """
    dropped = 3 - (((int(c[0]) >> 15) << 1) | (int(c[1]) >> 15))
    kept = [(int(v & 0x7FFF) - 0x3FFF) * (1.0 / 0x3FFF) / np.sqrt(2.0) for v in c]
    rebuilt = np.sqrt(max(0.0, 1.0 - sum(k * k for k in kept)))
    return tuple(kept[:dropped] + [rebuilt] + kept[dropped:])


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
        return _quat_to_m3(_unpack_quat(arot[idx] if idx < n_arot else srot[idx - n_arot]))

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


#  How much of an anim must land on the scene before it is this ship's. A loose gate, because the
#  per-joint pivot check in ship_pose is what really decides: an anim that is not this ship's finds
#  no joint of its own to move and comes out doing nothing, whatever it scored. Keeping the gate
#  tight instead cost the hauler its rear legs, which score 0.50 on an anim that is plainly theirs
#  -- all 8 joints are on the ship -- because half of them are the second rig for the same legs.
FITS = 0.4
REST = 0.02   # how close a joint's rest pose must sit to the scene's to count as the same joint
SLIDE = 1.0   # degrees; under this the movement is a slide, and a slide has no pivot to get wrong


def _turn_of(m) -> float:
    """How far a 4x4's rotation turns, in degrees."""
    return float(np.degrees(np.arccos(np.clip((np.trace(m[:3, :3]) - 1) / 2, -1, 1))))


#  Types whose scene is the flying ship rather than the parked one, so the movement listed for
#  them lands it instead of flying it. Only the sail ship, which is modelled with its mast up.
SCENE_IS_FLYING = frozenset({"solar"})


def ship_pose(ship: str, flying: bool, loc: dict) -> dict:
    """{NODE_NAME_UPPER: 4x4} -- what the state the scene is NOT in does to a node, as a movement
    to lay on its scene transform (`delta @ scene_local`). The state the scene already holds is
    the scene untouched, so that comes back empty.

    For almost every type that is parked: the scene is the ship standing on the ground, and the
    movement flies it. The sail ship is the exception -- it is modelled with its mast up and its
    sails out -- so there the movement lands it and flying is the scene as it came.

    The movement is `last @ inverse(first)` of a deploy anim: a node that does not animate comes
    out as the identity and is left alone. Taking the frame as the pose outright would be the same
    thing wherever the two agree -- and on a Sentinel 221 of its 231 nodes do -- but on the ten
    that do not it drags the node off to where the anim holds it, which left a swing-wing turned
    over on its hinge. Keeping the scene's own placing and adding only the movement cannot.

    `loc` is {node name: [local 4x4, ...]} for the nodes this ship carries -- see _fitting.
    """
    if flying == (ship in SCENE_IS_FLYING):
        return {}
    out: dict = {}
    # Best fit first, and the first to claim a node keeps it: where two candidates both drive a
    # node (the later cockpits all call one J_FrontPad) the one that fits this ship decides.
    for _, a in sorted(_fitting(ship, loc), key=lambda r: -r[0]):
        try:
            parked = pose_locals(a.path, -1 if a.backwards else 0)
            flown = pose_locals(a.path, 0 if a.backwards else -1)
        except Exception:
            continue
        for name, m in parked.items():
            end = flown.get(name)
            if end is None or np.allclose(m, end, atol=1e-6) or name in out:
                continue
            try:
                d = end @ np.linalg.inv(m)
            except np.linalg.LinAlgError:
                continue
            # A turn in the anim is a turn about that joint's own pivot. Where the ship puts the
            # joint somewhere else the pivot is not ours to use, and laying the turn on anyway
            # swings the part about the wrong point: it is what put the hauler's rear leg 2.6
            # below the ground and threw an Exotic's wings over on their hinge, both of which
            # carry a second rig for the part under names the ship also has. A slide has no pivot,
            # so it is safe wherever the joint sits.
            if _turn_of(d) > SLIDE and not any(np.allclose(x, m, atol=REST)
                                               for x in loc.get(name, ())):
                continue
            out[name] = d
    return out


def driven(ship: str, loc: dict) -> frozenset:
    """Every node this ship's deploy anims cover, moving or not.

    What hangs off one of these joints can be placed, because the anim accounts for it. Anything
    else on a joint is a rig the game drives itself -- see model3d's walk.
    """
    out: set = set()
    for _, a in _fitting(ship, loc):
        try:
            out.update(pose_locals(a.path, 0))
        except Exception:
            pass
    return frozenset(out)


def _fitting(ship: str, loc: dict) -> tuple:
    """[(how well it fits, anim)] for the anims that are really this ship's.

    `loc` holds only the nodes this ship actually carries, so an anim belonging to a part the seed
    did not pick finds nothing of its own to land on and is left out. That is what tells one of a
    ship's alternative part sets from another, since they reuse each other's node names.
    """
    out = []
    for a in SHIP_ANIMS.get(ship, []):
        try:
            parked = pose_locals(a.path, -1 if a.backwards else 0)
            flying = pose_locals(a.path, 0 if a.backwards else -1)
        except Exception:  # a part anim this game build does not ship
            continue
        # Judge it on the nodes it actually drives. Counting the still ones too flatters an anim
        # that happens to share a lot of a ship's skeleton without owning the parts that move: an
        # Exotic's wings scored 80% that way and then swung themselves 165 degrees over.
        here = [k for k in parked if k in loc and not np.allclose(parked[k], flying.get(k, parked[k]), atol=1e-6)]
        if not here:
            continue
        fit = sum(any(np.allclose(x, parked[k], atol=REST) for x in loc[k]) for k in here) / len(here)
        if fit >= FITS:
            out.append((fit, a))
    return tuple(out)
