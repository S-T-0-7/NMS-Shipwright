"""Which ships a star system has, computed with the game's own generator code.

NMS.exe's star-system generator (located per game build by exeaddr.py) is run in an emulator (see emu.py)
for any universe address. It fills cGcSolarSystemData, from which we read:

  * SentinelCrashSiteShipSeed (+0x2490) - the Sentinel interceptor found at the
    system's crash sites. Only dissonant systems (a planet with corrupted
    sentinels) have them.
  * SystemShips (+0x24a0) - 50 entries of 0x40 bytes: {name[0x20], seed, valid,
    role, subtype, class, ai-type}. The first 21 (role 1, ai-type 0) are the
    space-station pool ("21 ships per system"); class 1 hauler, 2 fighter,
    3 explorer, 4 shuttle, 6 exotic, 8 solar (pool ships converted by chance).
    The rest are freighter fleets, pirates and the POLICE sentinel ship.
  * PlanetGenerationInputs (+0x21a0, 0x58 bytes each): seed, biome (+0x10) and a
    flag (+0x18). Feeding {planet UA, seed, biome | flag<<16} to the game's
    planet-info function (the one that rebuilds planets from
    discovery records) gives each planet's sentinel level for the four sentinel
    presets (+0x34cc, 24 bytes apart); level 3 = corrupted => dissonant system.

Verified against the player's save: the two crash-site interceptors (systems 139
and 190), a station explorer (103), a station hauler (85), the planet seeds and
biomes of all 11 discovered planets, and dissonance (139 and 190 dissonant,
the start system not).

Three generator steps that only touch live-game objects (asteroid lists,
palettes) are skipped; none of them uses the RNG that seeds ships.
"""
from __future__ import annotations

import json
import os
import threading
import struct
import time

from . import aiships
from .emu import APP, Emu, extract_metadata
from .locate import describe, pack_ua, unpack_ua

OWNER_SIZE = 0x530000  # the solar-system object; the offsets inside it come from exeaddr
NORMAL = 2                 # sentinel preset used for dissonance (0 none, 1 low, 2 normal, 3 high)

CLASS_NAMES = {0: "freighter", 1: "hauler", 2: "fighter", 3: "explorer", 4: "shuttle", 6: "exotic",
               7: "living", 8: "solar", 9: "sentinel", 10: "corvette"}
CLASS_TO_ALIAS = {1: "hauler", 2: "fighter", 3: "explorer", 4: "shuttle", 6: "exotic", 7: "living",
                  8: "solar", 9: "sentinel"}
BIOMES = ["Lush", "Toxic", "Scorched", "Radioactive", "Frozen", "Barren", "Dead", "Exotic", "Red", "Green",
          "Blue", "Test", "Swamp", "Lava", "Waterworld", "Gas giant"]
SENTINEL_LEVELS = ["none", "low", "aggressive", "corrupted"]
RACES = {0: "Gek", 1: "Vy'keen", 2: "Korvax", 3: "Robots", 4: "Atlas", 5: "Diplomats", 6: "Exotics", 7: "none", 8: "Autophage"}
MODEL_LABELS = {"FIGHTER": "fighter", "DROPSHIP": "hauler", "SCIENTIFIC": "explorer", "SHUTTLE": "shuttle",
                "ROYAL": "exotic", "SAILSHIP": "solar", "ALIEN": "living ship", "ROBOT": "sentinel interceptor",
                "DROPSHIP_ROBOT": "sentinel hauler", "FREIGHTER": "freighter", "FREIGHTER_CAPTIAL": "capital freighter",
                "FREIGHTER_SMALL": "small freighter", "FREIGHTER_TINY": "tiny freighter",
                "FREIGHTER_CAPITAL_PIRATE": "pirate dreadnought", "FREIGHTER_POLICE": "sentinel freighter",
                "FREIGHTER_SWARM_HIVE": "swarm hive", "SWARM_DRONE": "swarm drone", "BIGGS": "corvette"}


class SystemGen:
    """One emulator, reused for any number of systems (~110 systems/s, ~50/s with planets)."""

    def __init__(self, exe: str | None = None):
        self.e = e = Emu(exe) if exe else Emu()
        self.a = a = e.addr  # found per game build (exeaddr)
        for k in ("skip_a", "skip_b", "palette_table"):
            e.patch_return(a[k])
        meta = extract_metadata()
        self.biome_list = e.load_mbin(os.path.join(meta, "biomelistperstartype.mbin"))
        self.biome_files = e.load_mbin(os.path.join(meta, "biomefilenames.mbin"))
        self.weather = e.alloc(0x2000)
        blank = e.alloc(0x1000)
        self.biome_arr = e.alloc(8 * 64)   # stand-in per-biome file lists (only feed cosmetic fields)
        for k in range(64):
            e.wq(self.biome_arr + 8 * k, blank)
        self.owner = e.alloc(OWNER_SIZE, 0x1000)
        self.gen, self.pg = self.owner + a["gen_off"], self.owner + a["pg_off"]
        e.wq(APP + a["owner_slot"], self.owner)          # the game's current solar system == generator owner
        e.wi(a["planet_flag"], 1)
        self.seed = e.alloc(16)
        self.ctx = e.alloc(0x20)
        self.lst = e.alloc(0x40)
        e.wq(self.lst, e.alloc(0x4000))
        e.wi(self.lst + 8, 1)
        self.mark = e.heap

    def _reset(self):
        e, o, pg = self.e, self.owner, self.pg
        e.heap = self.mark
        e.mu.mem_write(o, bytes(0x3000))
        e.mu.mem_write(o + 0x520000, bytes(0x10000))
        for i in range(32):                        # stand-in sky/weather lists the system generator indexes
            e.wq(self.gen + 0x6C0 + 8 * i, self.lst)
        e.wq(pg + 0x50, self.weather)              # planet generator tables
        e.wq(pg + 0x70, self.biome_files)
        e.wq(pg + 0x80, self.biome_list)
        for b in range(18):
            e.wq(pg + (b + 9) * 16, self.biome_arr)
            e.wi(pg + (b + 9) * 16 + 8, 64)

    def info(self, ua: int) -> dict:
        self._reset()
        e, info = self.e, self.owner + self.a["info_off"]
        e.call(self.a["info"], info, ua)
        seeds = []
        for i in range(8):
            s, valid = e.rq(info + 0x4B0 + 16 * i), e.mu.mem_read(info + 0x4B8 + 16 * i, 1)[0]
            if valid:
                seeds.append(s)
        race = e.ri(info + 0x74C)
        return {"region_valid": e.ri(info) != -1, "planets": e.ri(info + 0x740), "moons": e.ri(info + 0x744),
                "planet_seeds": seeds, "race": RACES.get(race, f"race {race}"),
                "inhabited": race != 7, "flag_754": e.mu.mem_read(info + 0x754, 1)[0]}

    def system(self, ua: int, planets: bool = False) -> dict:
        """Everything ship-related about one system (planets=True adds planets and dissonance).
        Raises RuntimeError if the emulation fails."""
        inf = self.info(ua)
        if not inf["region_valid"]:
            return {**inf, "ua": ua, "interceptor": None, "ships": [], "planet_list": [], "dissonant": False}
        e, o = self.e, self.owner
        e.wq(self.seed, ua)
        e.mu.mem_write(self.seed + 8, b"\x01")
        e.wq(self.ctx, o)
        e.wq(self.ctx + 8, o)
        e.wq(self.ctx + 0x10, o + 0x25E0)
        r = e.call(self.a["gen"], self.gen, self.seed, o + self.a["info_off"], self.ctx, until=self.a["stop"])
        if not r["ok"]:
            raise RuntimeError(f"system generator failed for UA 0x{ua:X}: {r}")
        ptr, cnt = e.rq(o + 0x24A0), e.ri(o + 0x24A8)
        ships = []
        for i in range(max(0, min(cnt, 256))):
            b = bytes(e.mu.mem_read(ptr + 0x40 * i, 0x40))
            role, sub, cls, ai = struct.unpack_from("<4i", b, 0x30)
            seed = struct.unpack_from("<Q", b, 0x20)[0]
            rec = aiships.pick(role, ai, cls, sub, seed)
            model = rec["id"] if rec else ""
            station = role == 1 and ai == 0 and i < 21
            kind = ("space station" if station else "freighter fleet" if model.startswith("FREIGHTER") and role == 1
                    else "frigate" if model.startswith("FRIGATE") and role == 1
                    else {2: "pirates", 3: "sentinels", 5: "swarm"}.get(role, "special"))
            ships.append({"seed": seed, "name": b[:0x20].split(b"\0")[0].decode(errors="replace"),
                          "role": role, "subtype": sub, "class": cls, "ai": ai, "station": station, "kind": kind,
                          "model": model, "filename": rec["filename"] if rec else "",
                          "type": MODEL_LABELS.get(model) or (model[8:].lower().replace("_", " ") + " frigate"
                                                              if model.startswith("FRIGATE_") else CLASS_NAMES.get(cls, f"class {cls}")),
                          "alias": rec["alias"] if rec else CLASS_TO_ALIAS.get(cls)})
        out = {**inf, "ua": ua, "interceptor": e.rq(o + 0x2490), "ships": ships}
        if planets:
            out["planet_list"] = self._planets(ua)
            # the game's own check: a corrupted planet counts only in an inhabited, charted system
            out["dissonant"] = (inf["inhabited"] and not inf["flag_754"]
                                and any(p["levels"][NORMAL] == 3 for p in out["planet_list"]))
        return out

    def _planets(self, ua: int) -> list[dict]:
        e, o = self.e, self.owner
        rows = []
        for i in range(e.ri(o + 0x2544) + e.ri(o + 0x2548)):
            base = o + 0x21A0 + 0x58 * i
            seed, biome, flag = e.rq(base), e.ri(base + 0x10), e.ri(base + 0x18)
            inp = e.alloc(0x100)
            e.wq(inp, ua | (i + 1) << 52)
            e.wq(inp + 8, seed)
            e.wq(inp + 0x10, biome | flag << 16)
            e.wi(inp + 0x30, 2)
            out = e.alloc(0x4000, 0x100)
            r = e.call(self.a["planet_info"], self.pg, out, inp, until=self.a["stop_planet"])
            levels = [e.ri(out + 0x34CC + 24 * k) for k in range(4)] if r["ok"] else [0, 0, 0, 0]
            lvl = levels[NORMAL]
            rows.append({"index": i + 1, "seed": f"0x{seed:016X}", "biome": biome,
                         "biome_name": BIOMES[biome] if 0 <= biome < len(BIOMES) else f"biome {biome}",
                         "levels": levels, "ok": r["ok"],
                         "sentinels": SENTINEL_LEVELS[lvl] if 0 <= lvl < len(SENTINEL_LEVELS) else "?"})
        return rows


SCAN_TYPES = ("sentinel", "fighter", "hauler", "explorer", "shuttle", "exotic", "solar", "freighter", "capital_freighter")
FLEET_TYPES = ("freighter", "capital_freighter")  # the freighter fleet that warps into the system
SYSTEM_INDICES = range(1, 0x300)  # 000 is a shadow star; 001-2FF are a region's star systems


def regions_around(center_ua: int, radius: int):
    """Regions (x, y, z) within `radius` of the centre's region, nearest first."""
    u = unpack_ua(center_ua)
    r = range(-radius, radius + 1)
    for dx, dy, dz in sorted(((a, b, c) for a in r for b in r for c in r),
                             key=lambda d: (max(map(abs, d)), sum(map(abs, d)))):
        x, y, z = u["x"] + dx, u["y"] + dy, u["z"] + dz
        if -2048 <= x < 2048 and -128 <= y < 128 and -2048 <= z < 2048:
            yield x, y, z


def default_workers() -> int:
    """Worker processes for scans: all cores but one, at most 6 (each holds its own ~150 MB emulator)."""
    return max(1, min((os.cpu_count() or 2) - 1, 6))


_W: dict = {}  # per-process state of scan workers


def _result(seed, ua, where, ship, score, total, missing, away):
    return {**describe(ua), "seed": f"0x{seed:016X}", "ship": ship, "where": where, "score": score,
            "total": total, "missing": missing, "regions_away": away,
            "dissonant": True if ship == "sentinel" else None}


CHUNK = 128  # systems per scan task, so even a one-region scan uses every worker


def _chunk_path(sg, galaxy, x, y, z, start):
    from .emu import CACHE
    folder = os.path.join(CACHE, "scan", "%d-%d" % sg.e.build)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{galaxy}_{x}_{y}_{z}_{start}.json")


def _chunk(sg, galaxy, x, y, z, start):
    """Every scannable ship of systems start..start+CHUNK-1 of a region, cached on disk (the game
    build is part of the path): {"n": systems tested, "c": [[seed, ua, where, alias]], "d": {ua: dissonant}}."""
    path = _chunk_path(sg, galaxy, x, y, z, start)
    try:
        with open(path) as f:
            return path, json.load(f)
    except (OSError, ValueError):
        pass
    cands, n = [], 0
    for s in range(start, min(start + CHUNK, SYSTEM_INDICES.stop)):
        ua = pack_ua(x, y, z, s, galaxy)
        try:
            info = sg.system(ua)
        except RuntimeError:
            continue
        n += 1
        if not info["region_valid"]:
            break  # an empty region has no systems at all
        cands.append([info["interceptor"], ua, "crash site", "sentinel"])
        if info["inhabited"]:  # uninhabited systems get (almost) no traders or freighter fleets
            cands += [[sh["seed"], ua, "space station" if sh["station"] else "freighter fleet", sh["alias"]]
                      for sh in info["ships"] if sh["station"] or sh["kind"] == "freighter fleet"]
    data = {"n": n, "c": cands, "d": {}}
    _save_chunk(path, data)
    return path, data


def _save_chunk(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


def _region_task(task, floor=None):
    """Scan one chunk of a region; returns (systems scanned, best results of this chunk).
    floor: the score the scan's current results already beat (nothing at or below it is kept)."""
    x, y, z, start, galaxy, ship, want, avoid, closest, keep, away = task
    if "sg" not in _W:
        _warm()
    sg = _W["sg"]
    path, data = _chunk(sg, galaxy, x, y, z, start)
    if ship == "sentinel":
        cands = [(seed, ua, where) for seed, ua, where, alias in data["c"] if where == "crash site"]
    else:
        where_ok = "freighter fleet" if ship in FLEET_TYPES else "space station"
        cands = [(seed, ua, where) for seed, ua, where, alias in data["c"] if where == where_ok and alias == ship]
    total = len(want)
    if closest:
        from .generator import part_ids, stored_id
        want_ids = [stored_id(w) for w in want]
        avoid_ids = {stored_id(a) for a in avoid}
        ranked = []
        for seed, ua, where in cands:
            parts = set(part_ids(seed, ship))
            if parts & avoid_ids:
                continue
            missing = [w for w, sid in zip(want, want_ids) if sid not in parts]
            ranked.append((total - len(missing), seed, ua, where, missing))
        ranked.sort(key=lambda r: -r[0])
    else:
        from .fastsearch import make_filter
        key = ("filter", ship, want, avoid)
        check = _W.get(key) or _W.setdefault(key, make_filter(ship, want, avoid))
        hits = set(check([c[0] for c in cands]))
        ranked = [(total, seed, ua, where, []) for seed, ua, where in cands if seed in hits]
    if ship == "sentinel":  # crash sites only exist in dissonant systems: check the best candidates
        kept, known = [], data["d"]
        for item in ranked:
            if floor is not None and item[0] <= floor:
                break  # ranked is best-first, and nearer results already hold this score
            k = str(item[2])
            if k not in known:
                inf = sg.info(item[2])
                try:  # cheap test first: dissonance needs an inhabited, uncharted system
                    known[k] = (inf["inhabited"] and not inf["flag_754"]
                                and sg.system(item[2], planets=True)["dissonant"])
                except RuntimeError:
                    known[k] = False
                _save_chunk(path, data)
            if known[k]:
                kept.append(item)
                if len(kept) >= keep:
                    break
        ranked = kept
    return data["n"], [_result(seed, ua, where, ship, sc, total, missing, away) for sc, seed, ua, where, missing in ranked[:keep]]


def _warm():
    from nms_save import gameversion
    gameversion.check()  # a game update makes cached scan results wrong
    _W.setdefault("sg", SystemGen())


_POOL: dict = {}  # worker processes stay alive between scans (each needs ~4 s to load the game code)


_POOL_LOCK = threading.Lock()


def _pool(workers):
    with _POOL_LOCK:  # the warm-up thread and a scan may ask at the same time
        if _POOL.get("n") != workers:
            if _POOL.get("pool"):
                _POOL["pool"].terminate()
            import multiprocessing as mp
            _POOL.update(n=workers, pool=mp.get_context("spawn").Pool(workers, initializer=_warm))
        return _POOL["pool"]


def warm_up(workers: int | None = None):
    """Start the scan workers ahead of the first scan."""
    _pool(default_workers() if workers is None else workers)


def scan(center_ua: int, radius: int, ship: str, want=(), avoid=(), limit: int = 20, closest: bool = False,
         workers: int | None = None, stats: dict | None = None, should_stop=None):
    """Scan the regions around a system for a design; yields the best results so far as chunks finish.

    closest=False: only systems whose ship has every wanted part (stops once `limit` are found).
    closest=True:  the `limit` ships sharing the most wanted parts, exact matches first.
    Station ships are scanned for fighter/hauler/explorer/shuttle/exotic/solar, the crash-site
    interceptor (dissonant systems only) for sentinel. Every region's ships are cached on disk,
    so scanning the same area again is almost instant. stats gets tested, regions,
    total_regions, seconds and workers.
    """
    if ship not in SCAN_TYPES:
        raise ValueError(f"{ship!r} ships are not sold at space stations or found at crash sites")
    from .fastsearch import make_filter
    make_filter(ship, want, avoid)  # rejects part ids that do not belong to this ship type
    galaxy, c = center_ua >> 32 & 0xFF, unpack_ua(center_ua)
    regions = list(regions_around(center_ua, radius))
    starts = range(SYSTEM_INDICES.start, SYSTEM_INDICES.stop, CHUNK)
    tasks = [(x, y, z, st, galaxy, ship, tuple(want), tuple(avoid), closest, limit,
              max(abs(x - c["x"]), abs(y - c["y"]), abs(z - c["z"]))) for x, y, z in regions for st in starts]
    workers = min(default_workers() if workers is None else max(1, workers), len(tasks))
    stats = {} if stats is None else stats
    stats.update(tested=0, regions=0, total_regions=len(regions), seconds=0.0, workers=workers)
    best, t0, done = [], time.time(), 0

    def floor():
        return best[-1]["score"] if len(best) >= limit else None

    def results():
        if workers <= 1:
            for t in tasks:
                yield _region_task(t, floor())
            return
        pool, pending = _pool(workers), []
        for t in tasks:  # keep only a few tasks queued, so a stopped scan frees the workers quickly
            pending.append(pool.apply_async(_region_task, (t, floor())))
            if len(pending) >= 2 * workers:
                yield pending.pop(0).get()
        while pending:
            yield pending.pop(0).get()

    for n, found in results():
        done += 1
        stats["tested"] += n
        stats["regions"] = done // len(starts)
        stats["seconds"] = time.time() - t0
        best = sorted(best + found, key=lambda r: (-r["score"], r["regions_away"]))[:limit]
        yield best
        if (should_stop and should_stop()) or (not closest and len(best) >= limit):
            return
