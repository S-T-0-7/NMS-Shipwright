"""The game's own textures for a ship, handed to the viewer still compressed.

A mesh names a material, a material names its samplers, and the first of those is the colour map
the hull is painted with. The maps are .DDS, block-compressed the way the GPU wants them --
BC1, BC4, BC5 and BC7 across the spacecraft textures -- so nothing is decoded here. The file
comes out of the pak, the header says which format it is, and the blocks go to WebGL as they
are. A browser that cannot take one of those formats simply draws the ship untextured.

A ship needs far fewer textures than it has materials: the Fighter's 394 materials share 25
colour maps between them, the Sentinel's 54 share 7. So meshes are grouped by the texture they
use rather than by their material, and a whole ship draws in a couple of dozen passes.
"""
from __future__ import annotations

import functools
import glob
import os
import struct

from nms_save import gamefiles, gamemeta
from nms_save.gamefiles import array, read, vstr

from . import textures

CACHE = os.path.join(gamefiles.CACHE, "shiptex")

# DDS header: the four-character code at 0x54, or DX10 and a DXGI number at 0x80. Only the
# formats the spacecraft textures actually use are named; anything else is left untextured
# rather than guessed at.
FOURCC = {b"DXT1": "BC1", b"DXT3": "BC2", b"DXT5": "BC3", b"ATI1": "BC4", b"ATI2": "BC5",
          b"BC4U": "BC4", b"BC5U": "BC5"}
DXGI = {70: "BC1", 71: "BC1", 72: "BC1", 73: "BC2", 74: "BC2", 75: "BC2", 76: "BC3", 77: "BC3",
        78: "BC3", 79: "BC4", 80: "BC4", 82: "BC5", 83: "BC5", 97: "BC7", 98: "BC7", 99: "BC7"}
SRGB = {72, 75, 78, 99}


@functools.lru_cache(maxsize=1)
def _layouts():
    m = gamemeta.exe_meta()
    return m.layout("cTkMaterialData"), m.layout("cTkMaterialSampler")


@functools.lru_cache(maxsize=1)
def _materials_dir():
    return textures._dir("materials", "models/common/spacecraft/*.material.mbin",
                         "NMSARC.MetadataEtc.pak")


@functools.lru_cache(maxsize=4096)
def maps_for(material: str) -> tuple:
    """The sampler maps of one material, colour map first, as game paths.

    Empty when the material cannot be read, which leaves its meshes drawn in flat colour.
    """
    if not material:
        return ()
    mat, samp = _layouts()
    path = textures._game_path(_materials_dir(), material)
    if not os.path.exists(path):
        return ()
    try:
        b = read(path)
        if not mat.matches(b):
            return ()
        base, n = array(b, 0x20 + mat.off("Samplers"))
        return tuple(vstr(b, base + k * samp.size + samp.off("Map")).upper().replace("\\", "/")
                     for k in range(n))
    except Exception:
        return ()


def colour_map(material: str) -> str:
    """The one texture a mesh is painted with, or "" if it has none."""
    maps = maps_for(material)
    return maps[0] if maps else ""


def _cache_file(dds: str) -> str:
    return os.path.join(CACHE, *dds.lower().split("/"))


@functools.lru_cache(maxsize=1)
def _index() -> dict:
    """{file name: the archive holding it} for every texture in the game.

    Hunting archive by archive is fine when the file is there and an early one holds it, and
    very slow when it is not: a map a material names but the game does not ship meant opening
    all ninety-seven in turn, a second gone to answer no. Listing the lot takes about six
    tenths of a second, once, and every answer after that is a lookup.
    """
    from hgpaktool import HGPAKFile
    out = {}
    for pak in sorted(glob.glob(os.path.join(gamefiles.BANKS, "*.pak"))):
        try:
            with HGPAKFile(pak) as f:
                for name in getattr(f, "filenames", []):
                    if name.endswith(".dds"):
                        out[name] = pak   # a later archive patches an earlier one
        except Exception:
            continue
    return out


@functools.lru_cache(maxsize=2048)
def blob(dds: str) -> bytes | None:
    """One texture, from the cache or out of its archive, or None if the game has no such map."""
    if not dds:
        return None
    path = _cache_file(dds)
    if os.path.exists(path):
        return read(path)
    pak = _index().get(dds.lower())
    if not pak:
        return None
    from hgpaktool import HGPAKFile
    try:
        with HGPAKFile(pak) as f:
            for _, data in f.extract(filters=[dds.lower()]):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as out:
                    out.write(data)
                return data
    except Exception:
        pass
    return None


def describe(data: bytes) -> dict | None:
    """{format, srgb, width, height, mips, offset} for a DDS, or None if it is not one we know.

    `offset` is where the blocks start, so the caller can hand the rest straight to the GPU.
    """
    if not data or len(data) < 128 or data[:4] != b"DDS ":
        return None
    height, width = struct.unpack_from("<II", data, 12)
    mips = max(1, struct.unpack_from("<I", data, 28)[0])
    fourcc = data[84:88]
    if fourcc == b"DX10":
        if len(data) < 148:
            return None
        dxgi = struct.unpack_from("<I", data, 128)[0]
        fmt, srgb, offset = DXGI.get(dxgi), dxgi in SRGB, 148
    else:
        fmt, srgb, offset = FOURCC.get(fourcc), False, 128
    if not fmt:
        return None
    return {"format": fmt, "srgb": srgb, "width": width, "height": height,
            "mips": mips, "offset": offset}
