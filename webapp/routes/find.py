"""Finding a matching ship in real star systems."""
from __future__ import annotations

import threading
import uuid

from flask import Blueprint, jsonify, request

from nms_procgen import locate, systemgen
from nms_save import ships

from webapp.common import JOBS, SHIP_LABELS, body, open_save, write

bp = Blueprint("find", __name__)


SYSGEN = {"sg": None}


SYSGEN_LOCK = threading.Lock()


def system_gen():
    if SYSGEN["sg"] is None:
        SYSGEN["sg"] = systemgen.SystemGen()
    return SYSGEN["sg"]


@bp.route("/api/location")
def api_location():
    opened = open_save(request.args.get("path"))
    known = sorted(locate.save_known_systems(opened.readable))
    return jsonify({"current": locate.describe(locate.save_location(opened.readable)),
                    "visited": [locate.describe(u) for u in known]})


@bp.route("/api/system")
def api_system():
    ua = locate.parse_address(request.args.get("addr", ""), int(request.args.get("galaxy", 0)))
    with SYSGEN_LOCK:
        s = system_gen().system(ua, planets=True)
    ships = [{**sh, "seed": f"0x{sh['seed']:016X}"}
             for sh in s["ships"]]
    return jsonify({**locate.describe(ua), "region_valid": s["region_valid"], "planets": s["planets"],
                    "moons": s["moons"], "ships": ships, "dissonant": s["dissonant"], "planet_list": s["planet_list"],
                    "interceptor": None if s["interceptor"] is None else f"0x{s['interceptor']:016X}"})


@bp.route("/api/freighter", methods=["GET", "POST"])
def api_freighter():
    if request.method == "GET":
        return jsonify(ships.get_freighter(open_save(request.args.get("path")).readable))
    b = body()
    opened = open_save(b.get("path"))
    home = locate.parse_address(b["home"]) if b.get("home") else None
    ships.set_freighter(opened.readable, b.get("ship", "capital_freighter"), b.get("seed", ""), home)
    backup = write(opened)
    return jsonify({"ok": True, "backup": backup, **ships.get_freighter(opened.readable)})


def run_find(job, center, radius, ship, want, limit, closest):
    try:
        for best in systemgen.scan(center, radius, ship, want, (), limit=limit, closest=closest, stats=job["stats"],
                                   should_stop=lambda: job["cancel"]):
            job["results"] = best
        job["status"] = "cancelled" if job["cancel"] else "done"
    except Exception as e:  # reported to the UI
        job["status"], job["error"] = "error", str(e)


@bp.route("/api/find/warm", methods=["POST"])
def api_find_warm():
    """Start the scan workers while the user is still designing (they take a few seconds to load)."""
    threading.Thread(target=systemgen.warm_up, daemon=True).start()
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
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = job = {"status": "running", "results": [], "stats": {}, "cancel": False, "error": None,
                          "ship": ship, "kind": "find"}
    threading.Thread(target=run_find, args=(job, center, max(0, min(int(b.get("radius", 0)), 6)), ship,
                                            list(b.get("want", [])), max(1, min(int(b.get("n", 10)), 50)),
                                            bool(b.get("closest", True))), daemon=True).start()
    return jsonify({"ok": True, "job": job_id})
