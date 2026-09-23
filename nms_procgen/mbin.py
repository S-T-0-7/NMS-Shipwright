"""Reader for NMS *.DESCRIPTOR.MBIN files (cTkModelDescriptorList trees)."""
import functools
import os
import struct

_BUNDLED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gamedata")


@functools.lru_cache(maxsize=1)
def gamedata_dir() -> str:
    """Folder holding the ship part descriptions.

    Nothing from the game is shipped with this tool: the descriptions are copied out of the
    player's own No Man's Sky the first time they are needed (and again after a game update).
    A checked-out source tree may have its own copy, which is used as-is.
    """
    if os.path.isdir(os.path.join(_BUNDLED, "models")):
        return _BUNDLED
    from nms_save import gamefiles
    return gamefiles.extract(os.path.join(gamefiles.CACHE, "gamedata"),
                             ["models/common/spacecraft/*.descriptor.mbin"], "NMSARC.EntitySceneMBIN.pak",
                             keep_dirs=True)


def __getattr__(name):  # GAMEDATA stays as a name, but is looked up when used
    if name == "GAMEDATA":
        return gamedata_dir()
    raise AttributeError(name)


def _i64(b, p): return struct.unpack_from("<q", b, p)[0]
def _i32(b, p): return struct.unpack_from("<i", b, p)[0]
def _u32(b, p): return struct.unpack_from("<I", b, p)[0]
def _cstr(b, p, n): return b[p:p + n].split(b"\0", 1)[0].decode("ascii", "replace")


def _model_list(b, pos, root_hash):
    """cTkModelDescriptorList at pos -> [{"type", "opts": [{"id", "name", "refs", "kids"}]}]."""
    off, cnt = _i64(b, pos), _i32(b, pos + 8)
    groups = []
    for i in range(cnt):
        g = pos + off + i * 0x20                      # cTkResourceDescriptorList
        doff, dcnt = _i64(b, g), _i32(b, g + 8)
        opts = []
        for j in range(dcnt):
            d = g + doff + j * 0xC8                   # cTkResourceDescriptorData
            roff, rcnt = _i64(b, d + 0x30), _i32(b, d + 0x38)
            refs = []
            for k in range(rcnt):
                vp = d + 0x30 + roff + k * 0x10
                so, sl = _i64(b, vp), _i32(b, vp + 8)
                refs.append(b[vp + so:vp + so + sl].split(b"\0", 1)[0].decode() if sl else "")
            coff, ccnt = _i64(b, d + 0x20), _i32(b, d + 0x28)
            kids = []
            for c in range(ccnt):
                e = d + 0x20 + coff + c * 0x10
                toff, name_hash = _i64(b, e), _u32(b, e + 8)
                if toff and name_hash == root_hash:   # only nested cTkModelDescriptorLists
                    kids.append(_model_list(b, e + toff, root_hash))
            opts.append({"id": _cstr(b, d, 0x20), "name": _cstr(b, d + 0x44, 0x80),
                         "refs": refs, "kids": kids})
        groups.append({"type": _cstr(b, g + 0x10, 0x10), "opts": opts})
    return groups


@functools.lru_cache(maxsize=None)
def ref_to_descriptor(ref, gamedata=None):
    """'MODELS/.../X.SCENE.MBIN' -> local path of its X.DESCRIPTOR.MBIN, or None."""
    gamedata = gamedata or gamedata_dir()
    p = ref.lower().replace("/", os.sep)
    if not p.endswith(".scene.mbin"):
        return None
    full = os.path.join(gamedata, p[:-len(".scene.mbin")] + ".descriptor.mbin")
    return full if os.path.exists(full) else None


@functools.lru_cache(maxsize=None)
def load_descriptor(path, gamedata=None):
    """Parse a descriptor file (absolute, or relative to gamedata). Cached; don't mutate."""
    if not os.path.isabs(path):
        path = os.path.join(gamedata or gamedata_dir(), path)
    with open(path, "rb") as f:
        b = f.read()
    return _model_list(b, 0x20, _u32(b, 12))
