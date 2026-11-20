"""Finding a matching ship in real star systems."""
from __future__ import annotations

import threading
import uuid

from flask import Blueprint, jsonify, request

from nms_procgen import fastsearch, locate, systemgen
from nms_save import ships

from webapp.common import JOBS, NO_SEED_LOOK, SHIP_LABELS, body, open_save, parse_look, write

bp = Blueprint("find", __name__)


@bp.route("/api/location")
def api_location():
    opened = open_save(request.args.get("path"))
    known = sorted(locate.save_known_systems(opened.readable))
    return jsonify({"current": locate.describe(locate.save_location(opened.readable)),
                    "visited": [locate.describe(u) for u in known]})


@bp.route("/api/system")
def api_system():
    ua = locate.parse_address(request.args.get("addr", ""), int(request.args.get("galaxy", 0)))
    with systemgen.borrow() as sg:
        s = sg.system(ua, planets=True)
    ships = [{**sh, "seed": f"0x{sh['seed']:016X}"}
             for sh in s["ships"]]
    return jsonify({**locate.describe(ua), "region_valid": s["region_valid"], "planets": s["planets"],
                    "moons": s["moons"], "ships": ships, "dissonant": s["dissonant"], "planet_list": s["planet_list"],
                    "race": s["race"], "inhabited": s["inhabited"],
                    "interceptor": None if s["interceptor"] is None else f"0x{s['interceptor']:016X}"})


def _freighter(readable):
    """What the save says about the freighter, plus the system its crew come from.

    Nothing about the aliens aboard is written into the save -- there is no race on the
    freighter and no model for anyone standing on it -- so the game works them out at load, and
    the home system is the only thing it has to go on. Which race holds that system is something
    this tool can already work out for any address, so it says so here.
    """
    f = dict(ships.get_freighter(readable))
    f["home_race"] = f["home_place"] = None
    try:
        ua = int(f["home"], 16)
    except (TypeError, ValueError):
        return f
    f["home_place"] = locate.describe(ua)
    try:
        with systemgen.borrow() as sg:
            f["home_race"] = sg.system(ua, planets=False)["race"]
    except Exception:       # a system that will not generate just leaves the race unknown
        pass
    return f


@bp.route("/api/freighter", methods=["GET", "POST"])
def api_freighter():
    if request.method == "GET":
        return jsonify(_freighter(open_save(request.args.get("path")).readable))
    b = body()
    opened = open_save(b.get("path"))
    home = locate.parse_address(b["home"]) if b.get("home") else None
    ships.set_freighter(opened.readable, b.get("ship", "capital_freighter"), b.get("seed", ""), home)
    backup = write(opened)
    return jsonify({"ok": True, "backup": backup, **_freighter(opened.readable)})


@bp.route("/api/freighter/home", methods=["POST"])
def api_freighter_home():
    """Move the freighter's home system and leave its look alone."""
    b = body()
    opened = open_save(b.get("path"))
    home = locate.parse_address(b.get("home", ""), int(b.get("galaxy", 0)))
    ships.set_freighter_home(opened.readable, home)
    backup = write(opened)
    return jsonify({"ok": True, "backup": backup, **_freighter(opened.readable)})


# How far to look for a system of each race before giving up. A voxel holds up to
# locate.MAX_SYSTEM_INDEX systems and one takes about five milliseconds, so this is well under a
# second in practice: the races are mixed together and the first few dozen usually cover them.
HOME_SEARCH = 240


@bp.route("/api/freighter/races")
def api_freighter_races():
    """The nearest system of each race to an address, for choosing a home."""
    ua = locate.parse_address(request.args.get("addr", ""), int(request.args.get("galaxy", 0)))
    here = locate.unpack_ua(ua)
    found = {}
    with systemgen.borrow() as sg:
        # out from the system it is now, so "the Gek system next door" really is next door
        order = sorted(range(locate.MAX_SYSTEM_INDEX), key=lambda i: abs(i - here["system"]))
        for index in order[:HOME_SEARCH]:
            at = locate.pack_ua(here["x"], here["y"], here["z"], index, here["galaxy"])
            try:
                race = sg.system(at, planets=False)["race"]
            except Exception:
                continue
            if race not in found:
                found[race] = {**locate.describe(at), "race": race}
    return jsonify({"searched": min(HOME_SEARCH, locate.MAX_SYSTEM_INDEX), "races": found})


def run_find(job, center, radius, ship, want, limit, closest, look):
    try:
        for best in systemgen.scan(center, radius, ship, want, (), limit=limit, closest=closest, stats=job["stats"],
                                   should_stop=lambda: job["cancel"], look=look):
            job["results"] = best
        job["status"] = "cancelled" if job["cancel"] else "done"
    except Exception as e:  # reported to the UI
        job["status"], job["error"] = "error", str(e)


@bp.route("/api/find/warm", methods=["POST"])
def api_find_warm():
    """Start the scan and seed-search workers while the user is still designing. Both take a
    few seconds to load, and whichever they press first would otherwise wait for them."""
    threading.Thread(target=systemgen.warm_up, daemon=True).start()
    threading.Thread(target=fastsearch.warm_up, daemon=True).start()
    return jsonify({"ok": True})


@bp.route("/api/find/scan", methods=["POST"])
def api_find_scan():
    b = body()
    ship = b.get("ship", "sentinel")
    if ship not in systemgen.SCAN_TYPES:
        raise ValueError(f"{SHIP_LABELS.get(ship, ship)} ships are not sold at stations or found at crash sites")
    if any(j["status"] == "running" and j.get("kind") == "find" for j in JOBS.values()):
        raise ValueError("a scan is already running")
    center = locate.parse_address(b.get("addr", ""), int(b.get("galaxy", 0)))
    look = parse_look(b.get("look")) if ship not in NO_SEED_LOOK else {}
    want = list(b.get("want", []))
    if not want and not look:
        raise ValueError("Pick at least one part or colour to search for.")
    # a pure-colour search has no part score to rank by, so stop as soon as `n` are found
    closest = bool(b.get("closest", True)) and bool(want)
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = job = {"status": "running", "results": [], "stats": {}, "cancel": False, "error": None,
                          "ship": ship, "kind": "find"}
    threading.Thread(target=run_find, args=(job, center, max(0, min(int(b.get("radius", 0)), 12)), ship,
                                            want, max(1, min(int(b.get("n", 10)), 50)),
                                            closest, look), daemon=True).start()
    return jsonify({"ok": True, "job": job_id})
