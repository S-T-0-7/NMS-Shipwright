# finds game code in NMS.exe by byte sig (nthng hardcoded, exe moves evry patch).
# WARN: sig dont match = game changed. redump bytes, dont tuch logic.
# cached data/gamecache/exeaddr.json.
from __future__ import annotations

import json
import os
import re
import struct

from nms_save import gamepath

from .emu import CACHE

# opcode bytes from disasm, ??=moves evry build. WARN: no retype, redump.
SIGS = {
    "gen": "48895c24184c894c24205556574154415541564157488dac2480d8ffffb880280000e8????????482be00f29b4247028",
    "info": "48895c2410574883ec30448bc2c6442446018bc241c1e014448bcac1e008488bda41c1f814c1f814488bf941c1f91848",
    "planet_sentinels": "48895c24104c894c242055565741544155415641574883ec40488bda4c8d3d????????b8676666664d8be141f7e8488b",
    "skip_a": "48895c241848895424105556574154415541564157488d6c24f04881ec10010000488b05????????488d742470488975",
    "skip_b": "405356574883ec204c89742448488d7a104c8b720833db4c897c24504c8bfa41399e482400007e7b48896c24400f1f00",
    "palette_table": "48895c2408488974241048897c2418554154415541564157488bec4883ec5033f6458be0448bea4c8bf9413871087428",
    # two identical copies exist; the right one sits PLANET_INFO_FROM_SENTINELS after planet_sentinels
    "planet_info": "48895c240848896c2410488974241857415641574881ece0010000488bf24d8bf04881c280310000488bf9e8????????"
                   "488d863c350000498bd64c8d8ed03a000048894424204c8d86cf3a0000e8????????33db389e28320000",
}
PLANET_INFO_FROM_SENTINELS = 0x11EB0
# (function, offset, expected bytes): where the emulator stops
STOPS = {
    "stop": ("gen", 0x1658, "8b442474"),                             # after SystemShips is copied out
    "stop_planet": ("planet_sentinels", 0x825, "4c8ba42498000000"),  # after per-preset sentinel levels
}
# (func, offset, opcode, longer sig, opcode pos in sig) for instrs whose disp32 we read.
# opcode alone is 3 bytes, too common to search. sig is the fallback when a patch moves it.
DISPS = {
    "owner_slot": ("gen", 0x797, "488b88", "0f1082????????488b88????????", 7),   # mov rcx,[rax+slot]
    "pg_off": ("planet_sentinels", 0x897, "488b88", "498b80????????488b88????????", 7),  # mov rcx,[rax+pg]
}
DISP_WINDOW = 0x2000  # how far it may have moved. 2+ matches raises rather than guess
# how much of a sig may differ b4 we stop trustin it. a patch recompiles a func but leaves most
# of the prologue alone -- few bytes changed = moved, quarter changed = diffrent func.
FUZZ = 0.15
APP_PTR_LOAD = ("gen", 0x779, "488b05")  # mov rax, [rip + app_ptr]
PLANET_FLAG_FROM_APP_PTR = 0x40
LEA_RCX, LEA_RDX, CALL = bytes.fromhex("488d0d"), bytes.fromhex("488d15"), bytes.fromhex("e8")
# regex over raw x86, finds gen call site + reads info/gen offsets. WARN: works, dont tuch.
GEN_CALL = re.compile(re.escape(bytes.fromhex("4c8d86")) + b"(.{4}).{0,8}?" + re.escape(bytes.fromhex("488d8e"))
                      + b"(.{4})" + re.escape(bytes.fromhex("4c8d4df0e8")), re.S)
CACHE_FILE = os.path.join(CACHE, "exeaddr.json")


class AddressError(RuntimeError):
    pass


def _build(img):
    """Which NMS.exe this was, for error messages.

    A user reported "0 signature matches" on Steam 7.14 while the same build resolved cleanly
    here, and the one line that would have told us which binary they had was the one they
    trimmed out of the report. So the path goes in too: a 2nd install, a leftover folder or a
    modded exe all look identical in a stamp and are obvious in a path.
    """
    where = " at %s" % img.path if img.path else ""
    return "exe %d/%d%s" % (img.build + (where,))


class _Image:
    def __init__(self, path):
        import pefile
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        pe = pefile.PE(data=self.data, fast_load=True)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.build = (pe.FILE_HEADER.TimeDateStamp, len(self.data))
        sec = {s.Name.rstrip(b"\0").decode(): s for s in pe.sections}
        t, r, d = sec[".text"], sec[".rdata"], sec[".data"]
        self.tva, self.text = t.VirtualAddress, self.data[t.PointerToRawData:t.PointerToRawData + t.SizeOfRawData]
        self.rva, self.rdata = r.VirtualAddress, self.data[r.PointerToRawData:r.PointerToRawData + r.SizeOfRawData]
        self.data_range = (self.base + d.VirtualAddress, self.base + d.VirtualAddress + d.Misc_VirtualSize)

    def code(self, va, n):
        o = va - self.base - self.tva
        return self.text[o:o + n]

    def find(self, sig):
        pat = b"".join(b"." if sig[i:i + 2] == "??" else re.escape(bytes.fromhex(sig[i:i + 2]))
                       for i in range(0, len(sig), 2))
        return [self.base + self.tva + m.start() for m in re.finditer(pat, self.text, re.S)]

    def rip_target(self, va, disp_at, length):
        return va + length + struct.unpack_from("<i", self.code(va + disp_at, 4))[0]

    def disp(self, va, opcode, name):
        if self.code(va, len(opcode)) != opcode:
            raise AddressError(f"{name}: instruction not found")
        return struct.unpack_from("<i", self.code(va + len(opcode), 4))[0]

    def globals_table(self, names):
        """{global file name: static instance} from the code that registers each global."""
        start = self.base + self.tva
        leas = {}
        for m in re.finditer(re.escape(LEA_RDX), self.text):
            target = start + m.end() + 4 + struct.unpack_from("<i", self.text, m.end())[0]
            leas.setdefault(target, []).append(start + m.start())
        lo, hi = self.data_range
        cands = {}
        for n in names:
            pat = re.escape(b"\0") + b"(" + re.escape(n.encode()) + b")" + re.escape(b"\0")
            for m in re.finditer(pat, self.rdata, re.I):
                for site in leas.get(self.base + self.rva + m.start(1), []):
                    win = self.code(site - 40, 80)
                    if CALL not in win[40:]:
                        continue
                    for k in range(len(win) - 7):
                        if win[k:k + 3] == LEA_RCX:
                            t = self.rip_target(site - 40 + k, 3, 7)
                            if lo <= t < hi:
                                cands.setdefault(n, set()).add(t)
        # addr next to >2 globals = shared mgr, not a real global. drop it.
        every = [t for v in cands.values() for t in v]
        shared = {t for t in every if every.count(t) > 2}
        table = {}
        for n, v in cands.items():
            v = v - shared
            if len(v) == 1:
                table[n] = v.pop()
        missing = sorted(set(names) - set(table))
        if missing:
            raise AddressError(f"globals not located: {missing}")
        return table


def _near(img, sig, align=0):
    """closest 2 tolerant matches for a sig: [(addr, bytes that differ), ..]. only runs after
    the exact search already failed. ?? positions arent compared. align=16 looks only where a
    compiled func can start, which is 1/16th of the work for the same answer."""
    import numpy as np
    want = [None if sig[i:i + 2] == "??" else int(sig[i:i + 2], 16) for i in range(0, len(sig), 2)]
    text = np.frombuffer(img.text, dtype=np.uint8)
    n = len(text) - len(want)
    if n <= 0:
        return []
    at = np.arange(0, n, align) if align else None
    bad = np.zeros(len(at) if align else n, dtype=np.int32)
    for k, b in enumerate(want):
        if b is None:
            continue
        bad += (text[at + k] if align else text[k:k + n]) != b
    return [(img.base + img.tva + int(at[i] if align else i), int(bad[i]))
            for i in np.argsort(bad, kind="stable")[:2]]


def _locate(img, name):
    """(addr, bytes that differed) or (None, why not). one changed instruction in a prologue
    used to brick the whole app; now it costs accuracy, not the feature. still refuses a close
    call -- 2 candidates inside budget means guessing, and a wrong addr runs wrong code."""
    sig = SIGS[name]
    hits = img.find(sig)
    if len(hits) == 1:
        return hits[0], 0
    if len(hits) > 1:
        return None, "%d signature matches" % len(hits)
    budget = int(sum(sig[i:i + 2] != "??" for i in range(0, len(sig), 2)) * FUZZ)
    for align in (16, 0):   # the aligned sweep answers in a fraction of a second; the full one
        near = _near(img, sig, align)   # is the backstop for a func that didnt start on 16
        if near and near[0][1] <= budget and (len(near) < 2 or near[1][1] > budget):
            return near[0][0], near[0][1]
    return None, ("no match, nearest differs in %d bytes" % near[0][1] if near else "no match")


def _gen_from_call_site(img):
    """gen's address from the one place that calls it, without reading its prologue at all.

    GEN_CALL is a shape rather than a byte pattern -- the 2 leas of the ship's own buffers,
    the lea of the stack slot, then the call -- and the exe contains exactly 1 of it. A patch
    that recompiles the generator rewrites its first instructions and leaves that shape alone,
    which is the difference between "0 signature matches" and a tool that still works. The
    offsets read off the same match are checked against it afterwards either way.
    """
    hits = {img.rip_target(img.base + img.tva + m.end() - 1, 1, 5) for m in GEN_CALL.finditer(img.text)}
    return hits.pop() if len(hits) == 1 else None


def _stop(img, addrs, name):
    fn, off, expect = STOPS[name]
    base, want = addrs[fn], bytes.fromhex(expect)
    if img.code(base + off, len(want)) == want:
        return base + off
    body = img.code(base, off + 0x400)  # the function changed a little: nearest copy of the instruction
    hits = [m.start() for m in re.finditer(re.escape(want), body)]
    if not hits:
        raise AddressError(f"{name}: stop instruction not found")
    return base + min(hits, key=lambda h: abs(h - off))


def _disp(img, addrs, name):
    """disp32 of one instr: by offset if still there, else by sig."""
    fn, off, op, sig, at = DISPS[name]
    va, opcode = addrs[fn] + off, bytes.fromhex(op)
    if img.code(va, len(opcode)) != opcode:
        hits = [h + at for h in img.find(sig) if abs(h + at - va) <= DISP_WINDOW]
        if len(hits) != 1:
            raise AddressError(f"{name}: instruction not found, {len(hits)} nearby sig matches "
                               f"(game code changed) [{_build(img)}]")
        va = hits[0]
    return struct.unpack_from("<i", img.code(va + len(opcode), 4))[0]


def _find_all(path):
    from .emu import extract_globals
    img = _Image(path)
    a, drift, failed = {}, {}, []
    for k in ("gen", "info", "planet_sentinels", "skip_a", "skip_b", "palette_table"):
        va, why = _locate(img, k)
        if va is None and k == "gen":
            va = _gen_from_call_site(img)
            why = "found by its call site, not its own code" if va else why
        if va is None:
            failed.append("%s: %s" % (k, why))
        else:
            a[k] = va
            if why:   # matched, but not the way it is supposed to match. say how.
                drift[k] = why if isinstance(why, str) else "%d bytes differ" % why
    if failed:
        # which ones DID match is the whole diagnosis, so say so. a game patch recompiles a func
        # or 2 and the rest stay put; a GOG/MS Store exe is a diffrent compile and nothing
        # matches. thats a bug report we can act on instead of guess at.
        raise AddressError("%s (game code changed) [%s; still matched: %s]"
                           % ("; ".join(failed), _build(img), ", ".join(sorted(a)) or "nothing"))
    want = a["planet_sentinels"] + PLANET_INFO_FROM_SENTINELS
    a["planet_info"] = min(img.find(SIGS["planet_info"]) or [0], key=lambda h: abs(h - want))
    if abs(a["planet_info"] - want) > 0x4000:
        raise AddressError("planet_info not found")
    for k in STOPS:
        a[k] = _stop(img, a, k)
    fn, off, op = APP_PTR_LOAD
    img.disp(a[fn] + off, bytes.fromhex(op), "app pointer load")
    a["app_ptr"] = img.rip_target(a[fn] + off, 3, 7)
    a["planet_flag"] = a["app_ptr"] + PLANET_FLAG_FROM_APP_PTR
    for k in DISPS:
        a[k] = _disp(img, a, k)
    for m in GEN_CALL.finditer(img.text):
        call = img.base + img.tva + m.end() - 1
        if img.rip_target(call, 1, 5) == a["gen"]:
            a["info_off"], a["gen_off"] = (struct.unpack("<i", g)[0] for g in m.groups())
            break
    else:
        raise AddressError("generator call site not found")
    folder = extract_globals()
    names = sorted(p.split(".")[0] for p in os.listdir(folder) if p.endswith(".global.mbin"))
    a["globals"] = img.globals_table(names)
    if drift:
        a["drift"] = drift
    return img.build, a


def resolve(path: str | None = None) -> dict:
    path = path or os.path.join(gamepath.require(), 'Binaries', 'NMS.exe')
    st = os.stat(path)
    key = f"{st.st_size}-{int(st.st_mtime)}"
    try:
        with open(CACHE_FILE) as f:
            cached = json.load(f)
        if cached.get("key") == key:
            return cached["addresses"]
    except (OSError, ValueError):
        pass
    build, addrs = _find_all(path)
    addrs["build"] = list(build)
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump({"key": key, "addresses": addrs}, f, indent=1)
    return addrs
