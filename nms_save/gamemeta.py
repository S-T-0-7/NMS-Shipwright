"""Class layouts read from NMS.exe's reflection data.

The exe describes every data class it loads from *.MBIN files. Each class entry is
{name*, name hash, layout guid, members*, member count, size}, and each member is
0x58 bytes: {name*, hash, type|size<<32, count|offset<<32, class entry* (for structs and lists), ...}.
A game file's MBIN header repeats the class's name hash and layout guid, so a reader
can check a file against the exe and take field offsets from it, instead of
hard-coding them and breaking on the next game update.
"""
from __future__ import annotations

import functools
import os
import struct

from . import gamepath

PICK_HINT = ("No Man's Sky was not found on this PC. Open Save > Game data and choose the folder "
             "the game is installed in (the one with Binaries\\NMS.exe).")


def nms_dir() -> str:
    """Where the game is installed on this PC ("" if it was not found)."""
    return gamepath.find()


def exe_path() -> str:
    return os.path.join(nms_dir() or "", "Binaries", "NMS.exe")


def __getattr__(name):  # NMS_DIR and EXE stay as names, but are looked up when used
    if name == "NMS_DIR":
        return nms_dir()
    if name == "EXE":
        return exe_path()
    raise AttributeError(name)


MEMBER_SIZE = 0x58


class MetaError(RuntimeError):
    pass


class ClassLayout:
    def __init__(self, name, name_hash, guid, size, fields):
        self.name, self.name_hash, self.guid, self.size, self.fields = name, name_hash, guid, size, fields

    def off(self, field):
        try:
            return self.fields[field]["offset"]
        except KeyError:
            raise MetaError(f"{self.name} has no field {field!r} in this game version") from None

    def matches(self, mbin: bytes) -> bool:
        """True if an MBIN file was written for this exact layout."""
        return len(mbin) >= 0x20 and struct.unpack_from("<IQ", mbin, 0x0C) == (self.name_hash & 0xFFFFFFFF, self.guid)


class ExeMeta:
    def __init__(self, path=None):
        path = path or exe_path()
        import pefile
        try:
            with open(path, "rb") as f:
                self.data = f.read()
            pe = pefile.PE(data=self.data, fast_load=True)
        except OSError as e:
            raise MetaError(f"No Man's Sky was not found at {path} (set NMS_DIR if it is installed elsewhere)") from e
        except Exception as e:  # not a Windows program, or a partly downloaded update
            raise MetaError(f"{path} could not be read as the game program ({e}). "
                            "Let any game update finish, then try again.") from e
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.build = (pe.FILE_HEADER.TimeDateStamp, len(self.data))
        self.sections = [(s.Name.rstrip(b"\0"), s.VirtualAddress, s.Misc_VirtualSize, s.PointerToRawData, s.SizeOfRawData)
                         for s in pe.sections]
        pe.close()

    def offset(self, va):
        rva = va - self.base
        for _, v, vs, raw, rs in self.sections:
            if v <= rva < v + min(vs, rs):
                return raw + rva - v
        return None

    def va(self, off):
        for _, v, vs, raw, rs in self.sections:
            if raw <= off < raw + rs:
                return self.base + v + off - raw
        return None

    def cstr(self, va, limit=128):
        o = self.offset(va) if va else None
        if o is None:
            return None
        end = self.data.find(b"\0", o, o + limit)
        return self.data[o:end].decode("ascii", "replace") if end > o else None

    @functools.lru_cache(maxsize=None)
    def layout(self, name) -> ClassLayout:
        needle = b"\0" + name.encode() + b"\0"
        rdata = next((s for s in self.sections if s[0] == b".rdata"), None)
        start, stop = (rdata[3], rdata[3] + rdata[4]) if rdata else (0, len(self.data))
        pos = self.data.find(needle, start, stop)
        while pos != -1:
            ptr = struct.pack("<Q", self.va(pos + 1))
            ref = self.data.find(ptr)
            while ref != -1:
                found = self._entry(name, ref)
                if found:
                    return found
                ref = self.data.find(ptr, ref + 1)
            pos = self.data.find(needle, pos + 1, stop)
        raise MetaError(f"{name} not found in NMS.exe (game updated in an unexpected way?)")

    def element(self, layout, field) -> ClassLayout:
        """Layout of the class stored in `field` (a struct member or a list's elements)."""
        ptr = layout.fields.get(field, {}).get("class")
        ref = self.offset(ptr) if ptr else None
        found = self._entry(None, ref) if ref is not None else None
        if not found:
            raise MetaError(f"{layout.name}.{field} has no class layout in this game version")
        return found

    def _entry(self, name, ref):
        name_hash, guid, members, count, size = struct.unpack_from("<QQQII", self.data, ref + 8)
        mo = self.offset(members) if members else None
        if mo is None or not 0 < count < 4096 or not 0 < size < 0x1000000:
            return None
        fields = {}
        for i in range(count):
            q = struct.unpack_from("<6Q", self.data, mo + i * MEMBER_SIZE)
            fname = self.cstr(q[0])
            if not fname:
                return None
            fields[fname] = {"type": q[2] & 0xFFFFFFFF, "size": q[2] >> 32, "count": q[3] & 0xFFFFFFFF,
                             "offset": q[3] >> 32, "class": q[4]}
        if any(f["offset"] >= size for f in fields.values()):
            return None
        name = name or self.cstr(struct.unpack_from("<Q", self.data, ref)[0]) or "?"
        return ClassLayout(name, name_hash, guid, size, fields)


@functools.lru_cache(maxsize=1)
def exe_meta():
    exe = exe_path()
    if not nms_dir():
        raise MetaError(PICK_HINT)
    if not os.path.exists(exe):
        raise MetaError(f"NMS.exe not found at {exe}. " + PICK_HINT)
    return ExeMeta(exe)
