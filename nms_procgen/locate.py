# Works out which star system a ship seed came from, by running the generator backwards.
# a system's ships are children of one RNG seeded with its universe address (UA):
#     rng = MWC(UA); ...k steps...; ship_seed = mix64((b<<32)|a)
# both steps are invertible, so we reverse step-by-step and keep states that decode to a
# real UA (planet 0, top byte clear, system index < 0x300).
# NOTE: seeds from our own design search were never made by the game, so they usually
# reverse into nothing -- that's expected.
from __future__ import annotations

K = 0x5A76F899
C1, C2 = 0x64DD81482CBD31D7, 0xE36AA5C613612997
M32, M64 = 0xFFFFFFFF, (1 << 64) - 1
_C1_INV, _C2_INV = pow(C1, -1, 1 << 64), pow(C2, -1, 1 << 64)

GALAXIES = ["Euclid", "Hilbert Dimension", "Calypso", "Hesperius Dimension", "Hyades",
            "Ickjamatew", "Butterfly", "Tikomaa", "Occupati", "Budullangr"]
MAX_SYSTEM_INDEX = 0x300


def unmix64(x: int) -> int:
    """Inverse of generator.mix64 (xorshift-33 is its own inverse)."""
    x ^= x >> 33
    x = x * _C2_INV & M64
    x ^= x >> 33
    x = x * _C1_INV & M64
    return x ^ (x >> 33)


def _rot16(v: int) -> int:
    return ((v << 16) | (v >> 16)) & M32


# ---- universe addresses ----------------------------------------------------

def pack_ua(x: int, y: int, z: int, system: int, galaxy: int = 0, planet: int = 0) -> int:
    return ((x & 0xFFF) | (z & 0xFFF) << 12 | (y & 0xFF) << 24 | (galaxy & 0xFF) << 32
            | (system & 0xFFF) << 40 | (planet & 0xF) << 52)


def unpack_ua(ua: int) -> dict:
    def s(v, bits):
        return v - (1 << bits) if v >= 1 << (bits - 1) else v
    return {"x": s(ua & 0xFFF, 12), "z": s(ua >> 12 & 0xFFF, 12), "y": s(ua >> 24 & 0xFF, 8),
            "galaxy": ua >> 32 & 0xFF, "system": ua >> 40 & 0xFFF, "planet": ua >> 52 & 0xF}


def from_visited(v: int) -> int:
    """PlayerStateData.VisitedSystems packs X | Y<<12 | Z<<20 | Sys<<32 (no galaxy)."""
    d = lambda val, bits: val - (1 << bits) if val >= 1 << (bits - 1) else val
    return pack_ua(d(v & 0xFFF, 12), d(v >> 12 & 0xFF, 8), d(v >> 20 & 0xFFF, 12), v >> 32 & 0xFFF)


def describe(ua: int) -> dict:
    u = unpack_ua(ua)
    g = u["galaxy"]
    return {
        **u,
        "ua": f"0x{ua:X}",
        "galaxy_name": GALAXIES[g] if g < len(GALAXIES) else f"Galaxy {g + 1}",
        # signal-booster / galaxy-map style coordinates
        "coords": f"{u['x'] + 0x7FF:04X}:{u['y'] + 0x7F:04X}:{u['z'] + 0x7FF:04X}:{u['system']:04X}",
        # portal glyph code: planet, system, Y, Z, X (hex, 12 glyphs)
        "glyphs": f"{1:X}{u['system']:03X}{u['y'] & 0xFF:02X}{u['z'] & 0xFFF:03X}{u['x'] & 0xFFF:03X}",
    }


def parse_address(text: str, galaxy: int = 0) -> int:
    """UA from portal glyphs ("108B08220992", planet digit first), signal-booster
    coordinates ("0191:0087:0A1F:008B") or a raw UA ("0x8B0008220992")."""
    t = text.strip().replace(" ", "")
    if ":" in t:
        x, y, z, s = (int(p, 16) for p in t.split(":"))
        return pack_ua(x - 0x7FF, y - 0x7F, z - 0x7FF, s, galaxy)
    if t.lower().startswith("0x"):
        return int(t, 16)
    if len(t) != 12:
        raise ValueError("expected 12 portal glyph digits, XXXX:YYYY:ZZZZ:SSSS coordinates, or 0x<UA>")
    s, y, z, x = int(t[1:4], 16), int(t[4:6], 16), int(t[6:9], 16), int(t[9:12], 16)
    sgn = lambda v, bits: v - (1 << bits) if v >= 1 << (bits - 1) else v
    return pack_ua(sgn(x, 12), sgn(y, 8), sgn(z, 12), s, galaxy)


def _plausible(ua: int) -> bool:
    return not ua >> 52 and (ua >> 40 & 0xFFF) < MAX_SYSTEM_INDEX


# ---- the search --------------------------------------------------------------

def origins(seed: int, max_steps: int = 4000) -> list[tuple[int, int]]:
    """(ua, k) pairs: `seed` is the child drawn after k steps of MWC(ua)."""
    # undo the final mix, split back into the two 32-bit rng outputs
    v = unmix64(seed & M64)
    a, b = v & M32, v >> 32
    c = (b - a * K) & M32                # MWC carry after the first draw
    if c > K:
        return []                        # carry out of range -> never an MWC child
    # step backwards; divmod inverts one MWC step, rebuild the UA each step.
    # WARNING: the j-loop handles a fresh state carrying >= K. looks pointless, isn't. keep it.
    s0, s1, out = a, c, []
    for k in range(max_steps):
        p0, p1 = divmod((s1 << 32) | s0, K)
        for j in range(3):
            q0, q1 = p0 - j, p1 + j * K
            if q0 < 0 or q1 > M32:
                break
            for lo in ((q0, 0) if q0 == 1 else (q0,)):
                ua = (q1 ^ _rot16(lo) ^ lo) << 32 | lo
                if _plausible(ua):
                    out.append((ua, k))
        s0, s1 = p0, p1
    return out


def locate(seed: int | str, max_steps: int = 3000, known_systems=(), galaxy: int = 0) -> list[dict]:
    """Candidate origin systems for a seed, best first.

    known_systems: UAs the player has visited/discovered (galaxy byte ignored when
    comparing) - a candidate that matches one is almost certainly the right one.
    A random 64-bit seed yields ~0.13 spurious candidates within 3000 steps, so an
    unvisited candidate is a lead, not a certainty.
    """
    if isinstance(seed, str):
        seed = int(seed, 16)
    known = {ua & ~(0xFF << 32) & ((1 << 52) - 1) for ua in known_systems}
    rows = []
    for ua, k in origins(seed, max_steps):
        rows.append({**describe(ua), "steps": k, "visited": (ua & ~(0xFF << 32)) in known})
    rows.sort(key=lambda r: (not r["visited"], r["galaxy"] != galaxy, r["steps"]))
    return rows


def save_known_systems(readable: dict) -> set[int]:
    """System UAs the player has visited or discovered, from a deobfuscated save."""
    out = set()
    ps = readable.get("BaseContext", {}).get("PlayerStateData", {})
    for v in ps.get("VisitedSystems") or []:
        out.add(from_visited(int(v)))
    dm = readable.get("DiscoveryManagerData", {}).get("DiscoveryData-v1", {})
    for r in (dm.get("Store", {}).get("Record") or []) + (dm.get("Available") or []):
        dd = r.get("DD", {})
        if dd.get("DT") == "SolarSystem" and dd.get("UA") is not None:
            ua = dd["UA"]
            out.add(int(ua, 16) if isinstance(ua, str) else int(ua))
    return out


def save_location(readable: dict) -> int:
    """UA of the system the player is in."""
    ps = readable.get("BaseContext", {}).get("PlayerStateData", {})
    ua = ps.get("UniverseAddress") or {}
    g = ua.get("GalacticAddress") or {}
    return pack_ua(g.get("VoxelX", 0), g.get("VoxelY", 0), g.get("VoxelZ", 0), g.get("SolarSystemIndex", 0),
                   ua.get("RealityIndex", 0))


def save_galaxy(readable: dict) -> int:
    ps = readable.get("BaseContext", {}).get("PlayerStateData", {})
    return int((ps.get("UniverseAddress") or {}).get("RealityIndex", 0))


def system_rng_children(ua: int, count: int, skip: int = 0) -> list[int]:
    """Child seeds MWC(ua) would produce after `skip` steps (forward direction)."""
    lo, hi = ua & M32, ua >> 32
    s0, s1 = (lo or 1), _rot16(lo) ^ hi ^ lo
    def step():
        nonlocal s0, s1
        t = s0 * K + s1
        s0, s1 = t & M32, t >> 32
        return s0
    for _ in range(skip):
        step()
    out = []
    for _ in range(count):
        a = step(); b = step()
        x = (b << 32) | a
        x ^= x >> 33; x = x * C1 & M64; x ^= x >> 33; x = x * C2 & M64; x ^= x >> 33
        out.append(x)
    return out
