"""Predict and search NMS procedural ship parts using the game's exact algorithm.

  python tools/ship_gen.py gen 0x5EEDC0DE70FAE007 [--ship fighter]
  python tools/ship_gen.py tree [--ship fighter]
  python tools/ship_gen.py search --ship fighter --want _WINGS_J _COCKPIT_F [--avoid ...] [-n 3]
  python tools/ship_gen.py save <save.hg> [--slot N]
  python tools/ship_gen.py verify
  python tools/ship_gen.py locate 0xDDF3D6A0A9E0EB78 [--save <save.hg>]   # which star system a seed came from
  python tools/ship_gen.py locate --save <save.hg>                          # every ship in a save
  python tools/ship_gen.py system 10BE08220992                               # ships a star system has
  python tools/ship_gen.py find --design dark_unicorn --save <save.hg> --radius 1   # where a design exists

--ship takes an alias (fighter, hauler, explorer, shuttle, exotic, living, solar,
sentinel, freighter, capital_freighter) or a scene filename from a save.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nms_procgen import ROOTS, describe_tree, explain, generate, parse_seed, part_ids, search  # noqa: E402

VECTORS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "nms_procgen", "test_vectors.json")


def _print_parts(parts):
    for gtype, pid in parts:
        print(f"  {gtype:<16} {pid}")


def cmd_gen(a):
    if not a.explain:
        _print_parts(generate(a.seed, a.ship))
        return
    for depth, _gtype, pid, alts, label in explain(a.seed, a.ship):
        print("  " * depth + f"{pid}  [nms.center: {label}]  (1 of {len(alts) + 1}"
              + (f"; not: {' '.join(alts)})" if alts else ")"))


def cmd_tree(a):
    print("\n".join(describe_tree(a.ship)))


def cmd_search(a):
    if a.nmscenter:
        from nms_procgen import decode_nmscenter_command
        a.ship, ids, extra = decode_nmscenter_command(a.nmscenter)
        a.want = list(dict.fromkeys(a.want + ids))
        print(f"nms.center command -> {a.ship}: {' '.join(ids)}", file=sys.stderr)
        if extra:
            print(f"  colour/texture selections not applied yet: {','.join(extra)}", file=sys.stderr)
    t = time.time()
    n = 0
    look = {k: v for k, v in (("primary", a.primary), ("secondary", a.secondary), ("undercoat", a.undercoat),
                              ("mode", [m.upper() for m in a.mode or []])) if v}
    if a.fast or look:
        from nms_procgen.fastsearch import fast_search
        results = fast_search(a.ship, a.want, a.avoid, a.n, time_limit=a.seconds, look=look)
    else:
        results = search(a.ship, a.want, a.avoid, a.n, a.tries)
    for seed, parts in results:
        n += 1
        print(f"0x{seed:016X}")
        if a.verbose:
            _print_parts(parts)
    print(f"{n} match(es) in {time.time() - t:.1f}s", file=sys.stderr)


def cmd_look(a):
    from nms_procgen.textures import ship_look
    r = ship_look(a.seed, a.ship)
    hexc = lambda rgb: "#" + "".join(f"{round(v * 255):02X}" for v in rgb) if rgb else "-"
    print(f"{r['ship']} {r['seed']}")
    for k, c in r["colours"].items():
        print(f"  {k:<10} colour {c['index']:>2}  {hexc(c['rgb'])}")
    for t in r["textures"]:
        print(f"  {t['list']:<18} {t['layer']:<10} {t['option'] or '(plain)':<12} {t['palette']} {t['alt']} {hexc(t['rgb'])}")


def cmd_save(a):
    from nms_save.save import open_save
    from nms_save.ships import list_ships
    for ship in list_ships(open_save(a.path).readable):
        if a.slot is not None and ship.index != a.slot:
            continue
        print(f"[{ship.index}] {ship.name or '(unnamed)'}  {ship.seed}  {ship.filename}")
        if not ship.seed or not ship.is_procedural:
            print("  (fixed model - seed has no visual effect)")
            continue
        try:
            _print_parts(generate(ship.seed, ship.filename))
        except (ValueError, FileNotFoundError) as e:
            print(f"  {e}")


def cmd_verify(a):
    bad = 0
    from nms_procgen.generator import stored_id
    for v in json.load(open(VECTORS)):
        got = part_ids(v["seed"], v["ship"])
        want = []
        for p in v["parts"]:  # reference lists use raw ids; game stores them stripped, once
            p = stored_id(v.get("aliases", {}).get(p, p))
            if p not in want:
                want.append(p)
        ok = got == want
        v["parts"] = want
        bad += not ok
        print(("OK  " if ok else "FAIL"), v["seed"], v["ship"])
        if not ok:
            print("  want", v["parts"], "\n  got ", got)
    from nms_procgen.textures import look_keys
    for seed, primary in COLOUR_VECTORS:
        ok = look_keys(seed)["primary"] == primary
        bad += not ok
        print(("OK  " if ok else "FAIL"), f"colour 0x{seed:016X} Paint Primary {primary}")
    from nms_procgen.locate import origins
    for seed, ua, k in ORIGIN_VECTORS:
        ok = (ua, k) in origins(seed)
        bad += not ok
        print(("OK  " if ok else "FAIL"), f"origin 0x{seed:016X} -> UA 0x{ua:X} after {k} steps")
    try:
        from nms_procgen.systemgen import SystemGen
        sg = SystemGen()
    except (OSError, RuntimeError, ImportError) as e:  # NMS.exe missing, or its code changed too much
        print("SKIP system checks:", e)
        sys.exit(1 if bad else 0)
    for ua, what, expect in SYSTEM_VECTORS:
        s = sg.system(ua, planets=what == "dissonant")
        if what == "interceptor":
            ok = s["interceptor"] == expect
        elif what == "dissonant":
            ok = s["dissonant"] == expect
        else:  # (seed, model id) of a ship in the system's list
            ok = any(sh["seed"] == expect[0] and sh["model"] == expect[1] for sh in s["ships"])
        bad += not ok
        shown = (f"0x{expect[0]:016X} {expect[1]}" if isinstance(expect, tuple)
                 else expect if isinstance(expect, bool) else f"0x{expect:016X}")
        print(("OK  " if ok else "FAIL"), f"system 0x{ua:X} {what} {shown}")
    sys.exit(1 if bad else 0)


# forward checks of the star-system generator against the player's save (2026-09-15)
# nms.center API "colors" (Paint Primary palette index) for the fighter test vectors
COLOUR_VECTORS = [(0x8BA812880CFAAA1C, 35), (0x7927714A9B78E44B, 42), (0x5EEDC0DECB68DBBD, 0),
                  (0xF1766BCDCF6D73FE, 3), (0x7627472FE96555AB, 6)]
SYSTEM_VECTORS = [(0xBE0008220992, "interceptor", 0xE86088649BD1C54B),
                  (0x8B0008220992, "interceptor", 0xDDF3D6A0A9E0EB78),
                  (0x5506F85DDC9A, "ship", (0x6541AB09D9EB1A25, "DROPSHIP")),                  # bought hauler
                  (0x670008220991, "ship", (0x89A75BCB4F9D3491, "SCIENTIFIC")),                # bought explorer
                  (0x8B0008220992, "ship", (0x902962A6264EDD02, "FREIGHTER_CAPITAL_PIRATE")),  # freighter
                  (0xBE0008220992, "dissonant", True), (0x8B0008220992, "dissonant", True),
                  (0x670008220991, "dissonant", False)]


# user's own ships, traced to systems in their save's VisitedSystems (2026-09-14)
ORIGIN_VECTORS = [(0xDDF3D6A0A9E0EB78, 0x8B0008220992, 646),   # crashed interceptor, sys 139
                  (0xE86088649BD1C54B, 0xBE0008220992, 326),   # crashed interceptor, sys 190
                  (0x89A75BCB4F9D3491, 0x670008220991, 1301),  # explorer, start system 103
                  (0x6541AB09D9EB1A25, 0x5506F85DDC9A, 792),   # hauler, sys 85 (galaxy byte 6)
                  (0x902962A6264EDD02, 0x8B0008220992, 650)]   # pirate freighter, sys 139


def cmd_system(a):
    from nms_procgen.locate import describe, parse_address
    from nms_procgen.systemgen import SystemGen
    ua = parse_address(a.address, a.galaxy)
    d, s = describe(ua), SystemGen().system(ua, planets=True)
    print(f"{d['galaxy_name']}, system {d['system']:#05x} of region ({d['x']}, {d['y']}, {d['z']})"
          f"  coords {d['coords']}  glyphs {d['glyphs']}")
    if not s["region_valid"]:
        print("  empty region: no star systems here")
        return
    print(f"  {s['planets']} planets, {s['moons']} moons; {'DISSONANT' if s['dissonant'] else 'not dissonant'}")
    for p in s["planet_list"]:
        print(f"    body {p['index']}: {p['biome_name']:<11} sentinels {p['sentinels']}")
    print(f"  crash-site interceptor 0x{s['interceptor']:016X}" +
          ("" if s["dissonant"] else "  (no crash sites: the system is not dissonant)"))
    print("  space station ships:")
    for sh in s["ships"]:
        if sh["station"]:
            print(f"    {sh['type']:<9} 0x{sh['seed']:016X}")


def cmd_find(a):
    from nms_procgen.locate import parse_address, save_location
    from nms_procgen.systemgen import scan
    want, ship = list(a.want), a.ship
    if a.design:
        path = a.design if a.design.endswith(".json") else os.path.join(
            os.path.dirname(VECTORS), "designs", a.design + ".json")
        d = json.load(open(path))
        want, ship = want + d.get("want", []), d.get("ship", "sentinel")
    if a.around:
        center = parse_address(a.around, a.galaxy)
    elif a.save:
        from nms_save.save import open_save
        center = save_location(open_save(a.save).readable)
    else:
        sys.exit("give --around <glyphs|coords> or --save <save.hg>")
    stats, t, best = {}, time.time(), []
    for best in scan(center, a.radius, ship, want, a.avoid, limit=a.n, closest=a.closest, workers=a.workers, stats=stats):
        print(f"\r  {stats['regions']}/{stats['total_regions']} regions, {stats['tested']} systems", end="", file=sys.stderr)
    print(file=sys.stderr)
    for r in best:
        print(f"{r['glyphs']}  {r['coords']}  {r['galaxy_name']} system {r['system']:#05x}  {r['where']:<13} {r['seed']}"
              f"  {r['score']}/{r['total']} parts" + (f"  missing {' '.join(r['missing'])}" if r["missing"] else ""))
    print(f"scanned {stats['tested']} systems in {stats['regions']}/{stats['total_regions']} regions"
          f" in {time.time() - t:.0f}s with {stats['workers']} worker(s)", file=sys.stderr)


def cmd_locate(a):
    from nms_procgen.locate import locate, save_galaxy, save_known_systems
    known, galaxy, seeds = set(), 0, [(s, s) for s in a.seeds]
    if a.save:
        from nms_save.save import open_save
        from nms_save.ships import list_ships
        readable = open_save(a.save).readable
        known, galaxy = save_known_systems(readable), save_galaxy(readable)
        if not seeds:
            seeds = [(f"[{s.index}] {s.name or s.filename.split('/')[-1]}", s.seed)
                     for s in list_ships(readable) if s.seed and s.is_procedural]
    for label, seed in seeds:
        rows = locate(seed, a.steps, known, galaxy)
        print(f"{label}  {seed}")
        if not rows:
            print(f"  no in-game origin (not generated by the game, or more than {a.steps} steps)")
        for r in rows[:3]:
            print(f"  {r['galaxy_name']}, system {r['system']:#05x} of region ({r['x']}, {r['y']}, {r['z']})"
                  f"  coords {r['coords']}  glyphs {r['glyphs']}  [{r['steps']} steps"
                  f"{', you visited it' if r['visited'] else ''}]")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen"); g.add_argument("seed", type=lambda s: parse_seed(s))
    g.add_argument("--ship", default="fighter")
    g.add_argument("--explain", action="store_true", help="show nesting and the alternatives of each pick")
    g.set_defaults(f=cmd_gen)
    t = sub.add_parser("tree"); t.add_argument("--ship", default="fighter"); t.set_defaults(f=cmd_tree)
    s = sub.add_parser("search"); s.add_argument("--ship", default="fighter")
    s.add_argument("--want", nargs="*", default=[]); s.add_argument("--avoid", nargs="*", default=[])
    s.add_argument("-n", type=int, default=5); s.add_argument("--tries", type=int, default=2_000_000)
    s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--nmscenter", help='nms.center bot search command, e.g. "custom:N,1,28,65"')
    s.add_argument("--fast", action="store_true",
                   help="vectorised search for many pinned parts; wanted options of one group are alternatives")
    s.add_argument("--seconds", type=float, default=600, help="time limit for --fast")
    s.add_argument("--primary", type=int, nargs="*", help="Paint Primary colour index (0-63), implies --fast")
    s.add_argument("--secondary", type=int, nargs="*", help="Paint Secondary colour index")
    s.add_argument("--undercoat", type=int, nargs="*", help="Undercoat colour index")
    s.add_argument("--mode", nargs="*", help="hull texture mode: COATING, PANELS or PAINTED")
    lk = sub.add_parser("look", help="colours, texture modes and decals of a seed")
    lk.add_argument("seed", type=lambda v: parse_seed(v)); lk.add_argument("--ship", default="fighter")
    lk.set_defaults(f=cmd_look)
    s.set_defaults(f=cmd_search)
    sv = sub.add_parser("save"); sv.add_argument("path"); sv.add_argument("--slot", type=int)
    sv.set_defaults(f=cmd_save)
    sub.add_parser("verify").set_defaults(f=cmd_verify)
    lc = sub.add_parser("locate", help="find the star system a ship seed came from")
    lc.add_argument("seeds", nargs="*"); lc.add_argument("--save", help="mark systems you visited; no seeds = all ships")
    lc.add_argument("--steps", type=int, default=3000)
    lc.set_defaults(f=cmd_locate)
    sy = sub.add_parser("system", help="ships a star system has (station pool + crash-site interceptor)")
    sy.add_argument("address", help="portal glyphs, XXXX:YYYY:ZZZZ:SSSS or 0x<UA>")
    sy.add_argument("--galaxy", type=int, default=0)
    sy.set_defaults(f=cmd_system)
    fd = sub.add_parser("find", help="scan star systems for a ship design")
    fd.add_argument("--ship", default="sentinel")
    fd.add_argument("--want", nargs="*", default=[]); fd.add_argument("--avoid", nargs="*", default=[])
    fd.add_argument("--design", help="a design in nms_procgen/designs, e.g. dark_unicorn")
    fd.add_argument("--around", help="start system (glyphs or coords)"); fd.add_argument("--save")
    fd.add_argument("--galaxy", type=int, default=0)
    fd.add_argument("--radius", type=int, default=0, help="regions around the start region (0 = that region only)")
    fd.add_argument("-n", type=int, default=10)
    fd.add_argument("--closest", action="store_true", help="rank by how many wanted parts match instead of requiring all")
    fd.add_argument("--workers", type=int, help="processes to use (default: all cores but one, max 6)")
    fd.set_defaults(f=cmd_find)
    a = p.parse_args()
    if getattr(a, "ship", None) and a.ship.lower() not in ROOTS and not a.ship.lower().endswith(".mbin"):
        p.error(f"unknown ship {a.ship!r}; choose from {', '.join(ROOTS)}")
    try:
        a.f(a)
    except ValueError as e:
        p.exit(2, f"error: {e}\n")


if __name__ == "__main__":
    main()
