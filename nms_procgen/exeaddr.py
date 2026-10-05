# finds where the game's code actually lives inside NMS.exe.
#
# PLEASE READ before you change anything: there are no fixed addresses in here and
# there never can be. hello games recompiles the whole exe every single patch so
# every function and every struct field moves. the ONLY thing that stays the same
# is roughly what the machine code looks like, so that's what we search for (the
# byte signatures below). if a signature stops matching after a game update it means
# THE GAME changed, not this file -> go re-dump the bytes in ghidra. do not "fix"
# the logic to make it pass, you will just make it lie to you.
#
# i swear i understood all of this for about a week when i wrote it. i don't now.
# if it's broken and you're reading this, i'm sorry, godspeed.
#
# what it actually figures out:
#   - functions: by masked byte sigs of their first bytes (the ?? are the bits that
#     move every build), first dumped on build 25343814
#   - stop points: "function + offset", double checked against the bytes we expect
#   - app ptr + solar-system slot + the gen/planet-gen/info offsets: read straight
#     out of the instructions that use them (planet-count flag is 0x40 past the app
#     ptr, held on every build i checked, fingers crossed)
#   - each global's static instance: from the code that registers it
#     (lea rcx,instance / lea rdx,"GcXxxGlobals" / call)
# cached in data/gamecache/exeaddr.json so we only live through this once per update.
from __future__ import annotations

import json
import os
import re
import struct

from nms_save import gamepath

from .emu import CACHE

# these are raw opcode bytes copied out of a disassembler. the ?? bytes are the ones
# that move around every build. do NOT retype these by hand, you WILL get a digit wrong
# at 2am and spend the next day wondering why nothing matches (ask me how i know).
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
# (function, offset, opcode bytes) of instructions whose 32-bit displacement we read
DISPS = {
    "owner_slot": ("gen", 0x797, "488b88"),            # mov rcx, [rax + slot]: current solar system in the app
    "pg_off": ("planet_sentinels", 0x897, "488b88"),   # mov rcx, [rax + planet generator offset]
}
APP_PTR_LOAD = ("gen", 0x779, "488b05")  # mov rax, [rip + app_ptr]
PLANET_FLAG_FROM_APP_PTR = 0x40
LEA_RCX, LEA_RDX, CALL = bytes.fromhex("488d0d"), bytes.fromhex("488d15"), bytes.fromhex("e8")
# yes this is a regex. over raw x86 machine code. i'm not proud of it but it finds the
# one call site that sets up and calls the generator (lea r8,[rsi+info] ... lea rcx,[rsi+gen]
# ... call gen) and from it we steal the info/gen struct offsets. it works. please leave it alone.
GEN_CALL = re.compile(re.escape(bytes.fromhex("4c8d86")) + b"(.{4}).{0,8}?" + re.escape(bytes.fromhex("488d8e"))
                      + b"(.{4})" + re.escape(bytes.fromhex("4c8d4df0e8")), re.S)
CACHE_FILE = os.path.join(CACHE, "exeaddr.json")


class AddressError(RuntimeError):
    pass


class _Image:
    def __init__(self, path):
        import pefile
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
        # some of these "globals" are actually the same manager object that gets passed in
        # next to a ton of different globals. if one address shows up next to >2 different
        # names it's one of those impostors, throw it out. took me forever to notice this.
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


def _unique(img, name):
    hits = img.find(SIGS[name])
    if len(hits) != 1:
        raise AddressError(f"{name}: {len(hits)} signature matches (game code changed)")
    return hits[0]


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


def _find_all(path):
    from .emu import extract_globals
    img = _Image(path)
    a = {k: _unique(img, k) for k in ("gen", "info", "planet_sentinels", "skip_a", "skip_b", "palette_table")}
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
    for k, (fn, off, op) in DISPS.items():
        a[k] = img.disp(a[fn] + off, bytes.fromhex(op), k)
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
