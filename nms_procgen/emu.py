# runs real NMS.exe code w/o the game: maps exe into unicorn emulator, fakes imports/
# stack/heap/TEB/app obj, loads *.global.mbin, calls the generators directly.
# reads NMS.exe + NMSARC.globals.pak off disk only, never touches running game.
from __future__ import annotations

import glob
import json
import math
import os
import struct

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_MODE_64, Uc, UcError
from unicorn import x86_const as X

from nms_save import gamepath


def __getattr__(name):  # looked up when used, so the game folder can be chosen in the app
    if name == "NMS_DIR":
        return gamepath.require()
    if name == "EXE":
        return os.path.join(gamepath.require(), "Binaries", "NMS.exe")
    if name == "GLOBALS_PAK":
        return os.path.join(gamepath.require(), "GAMEDATA", "PCBANKS", "NMSARC.globals.pak")
    raise AttributeError(name)


CACHE = os.environ.get("NMS_TOOL_CACHE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gamecache")

BASE = 0x140000000
STUBS, SENTINEL = 0x10000000, 0x10100000
NATIVE = STUBS + 0x20000  # x86 versions of hot imports: no Python callback per call
# hand-asm x86-64 (win64 abi) so hot imports run in-emulator, not via python.
# WARN: no hand-editing hex, assemble + paste.
NATIVE_CODE = {
    # memmove(rcx=dst, rdx=src, r8=n) -> dst; copies backwards when dst overlaps the end of src
    # memmove(rcx=dst, rdx=src, r8=n) -> dst: 32/8/1-byte loops (unicorn runs each `rep` step as its
    # own block, so rep movsb is slow); byte-wise backwards when dst overlaps the end of src
    "memmove": bytes.fromhex("57564889c84889cf4889d64c89c14839f776194a8d14064839d77310488d740eff488d7c0ffffdf3a4fceb504883f920721c0f10260f106e100f11270f116f104883c6204883c7204883e920ebde4883f9087214488b164889174883c6084883c7084883e908ebe64885c9740f8a16881748ffc648ffc748ffc9ebec5e5fc3"),
    # memset(rcx=dst, edx=byte, r8=n) -> dst
    "memset": bytes.fromhex("57" "4989c9" "4889cf" "89d0" "4c89c1" "f3aa" "4c89c8" "5f" "c3"),
    "floorf": bytes.fromhex("660f3a0ac001" "c3"),  # roundss xmm0, xmm0, 1 (round down)
    "ceilf": bytes.fromhex("660f3a0ac002" "c3"),   # roundss xmm0, xmm0, 2 (round up)
}
NATIVE_CODE["memcpy"] = NATIVE_CODE["memmove"]
STACK, STACK_SIZE = 0x20000000, 0x2000000
TEB = 0x2F000000
HEAP, HEAP_SIZE = 0x30000000, 0x20000000
APP, APP_SIZE = 0x60000000, 0x1000000
ARGS = (X.UC_X86_REG_RCX, X.UC_X86_REG_RDX, X.UC_X86_REG_R8, X.UC_X86_REG_R9)
XMM = [getattr(X, f"UC_X86_REG_XMM{i}") for i in range(8)]


_M1 = {"floor": math.floor, "ceil": math.ceil, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
       "acos": math.acos, "asin": math.asin, "atan": math.atan, "exp": math.exp, "log": math.log, "log10": math.log10,
       "log2": math.log2, "trunc": math.trunc,
       "round": lambda x: math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)}
_M2 = {"pow": math.pow, "fmod": math.fmod, "atan2": math.atan2}
MATH1 = {**_M1, **{k + "f": v for k, v in _M1.items()}}
MATH2 = {**_M2, **{k + "f": v for k, v in _M2.items()}}


METADATA_FILES = ("biomelistperstartype.mbin", "biomefilenames.mbin", "aispaceshipmanager.mbin")


def _fresh(dest, pak):
    """True if `dest` was filled from this exact archive (refilled after a game update)."""
    stamp = f"{os.path.getsize(pak)}-{int(os.path.getmtime(pak))}" if os.path.exists(pak) else ""
    path = os.path.join(dest, "_stamp.txt")
    try:
        with open(path) as f:
            if f.read() == stamp:
                return True
    except OSError:
        pass
    for old in glob.glob(os.path.join(dest, "*.mbin")):
        os.remove(old)
    os.makedirs(dest, exist_ok=True)
    with open(path, "w") as f:
        f.write(stamp)
    return False


def extract_metadata(dest: str = os.path.join(CACHE, "metadata")) -> str:
    """Copy the biome tables the planet generator uses out of the game's archives (once per version)."""
    banks = os.path.join(gamepath.require(), "GAMEDATA", "PCBANKS")
    if _fresh(dest, os.path.join(banks, "NMSARC.Precache.pak")) and             all(os.path.exists(os.path.join(dest, f)) for f in METADATA_FILES):
        return dest
    from hgpaktool import HGPAKFile
    need = set(METADATA_FILES)
    for pak in [os.path.join(banks, "NMSARC.Precache.pak")] + sorted(glob.glob(os.path.join(banks, "*.pak"))):
        if not need or not os.path.exists(pak):
            continue
        with HGPAKFile(pak) as f:
            for name, blob in f.extract(filters=["*" + n for n in sorted(need)]):
                base = os.path.basename(name).lower()
                if base in need:
                    with open(os.path.join(dest, base), "wb") as out:
                        out.write(blob)
                    need.discard(base)
    if need:
        raise FileNotFoundError(f"{sorted(need)} not found in the game's archives")
    return dest


def extract_globals(dest: str = os.path.join(CACHE, "globals")) -> str:
    """Copy *.global.mbin out of the game's globals archive (once per version)."""
    pak = os.path.join(gamepath.require(), "GAMEDATA", "PCBANKS", "NMSARC.globals.pak")
    if _fresh(dest, pak) and glob.glob(os.path.join(dest, "*.global.mbin")):
        return dest
    from hgpaktool import HGPAKFile
    with HGPAKFile(pak) as f:
        for name, blob in f.extract(filters=["*.global.mbin"]):
            with open(os.path.join(dest, os.path.basename(name)), "wb") as out:
                out.write(blob)
    return dest


class Emu:
    def __init__(self, exe: str | None = None, globals_dir: str | None = None):
        import pefile
        exe = exe or os.path.join(gamepath.require(), "Binaries", "NMS.exe")
        data = open(exe, "rb").read()
        pe = pefile.PE(data=data, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_TLS"]])
        self.build = (pe.FILE_HEADER.TimeDateStamp, len(data))
        from .exeaddr import resolve
        self.addr = resolve(exe)  # code/data addresses for this build
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_64)
        mu.mem_map(BASE, (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF)
        mu.mem_write(BASE, data[:pe.OPTIONAL_HEADER.SizeOfHeaders])
        for s in pe.sections:
            mu.mem_write(BASE + s.VirtualAddress,
                         data[s.PointerToRawData:s.PointerToRawData + min(s.SizeOfRawData, s.Misc_VirtualSize)])
        for addr, size in ((STUBS, 0x10000), (NATIVE, 0x1000), (SENTINEL, 0x1000), (STACK, STACK_SIZE), (TEB, 0x10000),
                           (HEAP, HEAP_SIZE), (APP, APP_SIZE)):
            mu.mem_map(addr, size)
        self.heap, self.sizes, self.imports = HEAP, {}, {}
        native, at = {}, NATIVE
        for name, code in NATIVE_CODE.items():
            native[name] = at
            mu.mem_write(at, code)
            at += (len(code) + 15) & ~15
        k = 0
        for d in pe.DIRECTORY_ENTRY_IMPORT:
            for imp in d.imports:
                name = (imp.name or b"#").decode()
                if name in native:
                    mu.mem_write(imp.address, struct.pack("<Q", native[name]))
                    continue
                stub = STUBS + 0x10 * k
                k += 1
                mu.mem_write(stub, b"\xc3")  # ret - the hook supplies the result
                mu.mem_write(imp.address, struct.pack("<Q", stub))
                self.imports[stub] = name
        tls = pe.DIRECTORY_ENTRY_TLS.struct
        tmpl = bytes(mu.mem_read(tls.StartAddressOfRawData, tls.EndAddressOfRawData - tls.StartAddressOfRawData))
        block = self.alloc(len(tmpl) + 0x4000)
        mu.mem_write(block, tmpl)
        arr = self.alloc(0x100)
        mu.mem_write(arr, struct.pack("<Q", block))
        mu.mem_write(tls.AddressOfIndex, struct.pack("<I", 0))
        mu.mem_write(TEB, struct.pack("<QQQQQQQ", 0, STACK + STACK_SIZE, STACK, 0, 0, 0, TEB))
        mu.mem_write(TEB + 0x58, struct.pack("<Q", arr))
        mu.reg_write(X.UC_X86_REG_GS_BASE, TEB)
        mu.mem_write(self.addr["app_ptr"], struct.pack("<Q", APP))
        mu.hook_add(UC_HOOK_CODE, self._on_stub, begin=STUBS, end=STUBS + 0x10000)
        mu.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        self.fault = None
        self._load_globals(globals_dir or extract_globals())

    # ---- memory
    def alloc(self, n: int, align: int = 16) -> int:
        self.heap = (self.heap + align - 1) & ~(align - 1)
        a, self.heap = self.heap, self.heap + n
        if self.heap > HEAP + HEAP_SIZE:
            raise MemoryError("emulator heap exhausted")
        return a

    def rq(self, a): return struct.unpack("<Q", self.mu.mem_read(a, 8))[0]
    def ri(self, a): return struct.unpack("<i", self.mu.mem_read(a, 4))[0]
    def wq(self, a, v): self.mu.mem_write(a, struct.pack("<Q", v & (1 << 64) - 1))
    def wi(self, a, v): self.mu.mem_write(a, struct.pack("<i", v))

    def load_mbin(self, path: str) -> int:
        """Load an MBIN into emulator memory (arrays fixed up); returns the struct's address."""
        b = open(path, "rb").read()
        h = self.alloc(len(b) + 0x100, 0x100)
        self.mu.mem_write(h, b)
        # MBIN arrays = (rel offset, count, 0xAAAAAA01); magic marks a ptr. fix rel -> abs addr.
        for p in (i - 12 for i in range(12, len(b) - 3, 4)
                  if struct.unpack_from("<I", b, i)[0] == 0xAAAAAA01 and (i - 12) % 8 == 0):
            rel, cnt = struct.unpack_from("<qI", b, p)
            self.mu.mem_write(h + p, struct.pack("<Q", h + p + rel if cnt else 0))
        return h + 0x20

    def patch_return(self, func_addr: int, value: int = 0):
        """Make a game function return immediately (mov rax, value; ret)."""
        self.mu.mem_write(func_addr, b"\x48\xb8" + struct.pack("<Q", value & (1 << 64) - 1) + b"\xc3")

    def _load_globals(self, folder):
        for path in glob.glob(os.path.join(folder, "*.global.mbin")):
            inst = self.addr["globals"].get(os.path.basename(path).split(".")[0])
            if not inst:
                continue
            b = open(path, "rb").read()
            h = self.alloc(len(b))
            self.mu.mem_write(h, b)
            starts = []
            for p in (i - 12 for i in range(12, len(b) - 3, 4)
                      if struct.unpack_from("<I", b, i)[0] == 0xAAAAAA01 and (i - 12) % 8 == 0):
                rel, cnt = struct.unpack_from("<qI", b, p)
                if cnt:
                    starts.append(p + rel)
                self.mu.mem_write(h + p, struct.pack("<Q", h + p + rel if cnt else 0))
            end = min(starts) if starts else len(b)
            self.mu.mem_write(inst, bytes(self.mu.mem_read(h + 0x20, end - 0x20)))

    # ---- imports
    def _xmm(self, i, f32):
        v = self.mu.reg_read(XMM[i])
        return (struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0] if f32
                else struct.unpack("<d", struct.pack("<Q", v & (1 << 64) - 1))[0])

    def _set_xmm(self, i, val, f32):
        bits = (struct.unpack("<I", struct.pack("<f", val))[0] if f32
                else struct.unpack("<Q", struct.pack("<d", val))[0])
        self.mu.reg_write(XMM[i], bits)

    def _malloc(self, n, align=16):
        a = self.alloc(max(n, 1), align)
        self.sizes[a] = n
        return a

    # fakes return value for every import (maths, malloc, memcpy...).
    # WARN: import problm = silent 0 = weird fault later. add missing ones here.
    def _on_stub(self, mu, addr, size, _):
        fn = self.imports.get(addr)
        if fn is None:
            return
        rcx, rdx, r8 = (mu.reg_read(r) for r in ARGS[:3])
        ret = 0
        try:
            if fn in MATH1:
                f32 = fn.endswith("f") and fn[:-1] in MATH1
                self._set_xmm(0, MATH1[fn](self._xmm(0, f32)), f32)
            elif fn in MATH2:
                f32 = fn.endswith("f")
                self._set_xmm(0, MATH2[fn](self._xmm(0, f32), self._xmm(1, f32)), f32)
            elif fn in ("frexp", "frexpf"):
                m, ex = math.frexp(self._xmm(0, fn == "frexpf"))
                self._set_xmm(0, m, fn == "frexpf")
                mu.mem_write(rdx, struct.pack("<i", ex))
            elif fn in ("ldexp", "ldexpf"):
                e = struct.unpack("<i", struct.pack("<I", rdx & 0xFFFFFFFF))[0]
                self._set_xmm(0, math.ldexp(self._xmm(0, fn == "ldexpf"), e), fn == "ldexpf")
            elif fn in ("modf", "modff"):
                fr, wh = math.modf(self._xmm(0, fn == "modff"))
                self._set_xmm(0, fr, fn == "modff")
                mu.mem_write(rdx, struct.pack("<f" if fn == "modff" else "<d", wh))
            elif fn in ("memcpy", "memmove"):
                if r8:
                    mu.mem_write(rcx, bytes(mu.mem_read(rdx, r8)))
                ret = rcx
            elif fn == "memset":
                if r8:
                    mu.mem_write(rcx, bytes([rdx & 0xFF]) * r8)
                ret = rcx
            elif fn in ("malloc", "??2@YAPEAX_K@Z", "??_U@YAPEAX_K@Z"):
                ret = self._malloc(rcx)
            elif fn == "_aligned_malloc":
                ret = self._malloc(rcx, max(16, rdx))
            elif fn == "calloc":
                ret = self._malloc(rcx * rdx)
            elif fn in ("realloc", "_aligned_realloc"):
                ret = self._malloc(rdx, max(16, r8) if fn.startswith("_") else 16)
                if rcx and self.sizes.get(rcx):
                    mu.mem_write(ret, bytes(mu.mem_read(rcx, min(self.sizes[rcx], rdx))))
        except (ValueError, OverflowError, ZeroDivisionError):
            self._set_xmm(0, float("nan"), False)
        mu.reg_write(X.UC_X86_REG_RAX, ret)

    def _on_unmapped(self, mu, access, addr, size, value, _):
        self.fault = (addr, mu.reg_read(X.UC_X86_REG_RIP))
        return False

    # ---- calling
    def call(self, fn: int, *args: int, until: int = SENTINEL, count: int = 100_000_000) -> dict:
        mu = self.mu
        rsp = ((STACK + STACK_SIZE - 0x20000) & ~0xF) - 8
        mu.mem_write(rsp, struct.pack("<Q", SENTINEL))
        mu.reg_write(X.UC_X86_REG_RSP, rsp)
        for r, v in zip(ARGS, args):
            mu.reg_write(r, v & (1 << 64) - 1)
        self.fault = None
        try:
            mu.emu_start(fn, until, count=count)
        except UcError as e:
            return {"ok": False, "error": str(e), "fault": self.fault}
        pc = mu.reg_read(X.UC_X86_REG_RIP)
        return {"ok": pc == until, "rax": mu.reg_read(X.UC_X86_REG_RAX), "pc": pc}
