"""Part tree, seed search and saved designs."""
from __future__ import annotations

import functools
import glob
import json
import os
import re
import threading
import uuid

from flask import Blueprint, Response, jsonify, request

from nms_procgen import model3d, ROOTS, explain, load_descriptor, ref_to_descriptor, textures
from nms_procgen.fastsearch import fast_search
from nms_save import gamefiles, player, ships

from webapp.common import (GameRunning, JOBS, NO_SEED_LOOK, ROOT, SHIP_LABELS, body, game_running,
                           limit_seconds, model_filename, open_save, parse_look, part_names,
                           ship_alias, write)

bp = Blueprint("designer", __name__)


@bp.route("/api/parts")
def api_parts():
    ship, seed = request.args.get("ship", "fighter"), request.args.get("seed", "0x0")
    names = part_names(ship if ship in ROOTS else ship_alias(ship) or "")
    return jsonify({"parts": [{"depth": d, "group": g, "id": pid, "name": names.get(pid, ""), "label": label,
                               "choices": len(alts) + 1} for d, g, pid, alts, label in explain(seed, ship)]})


@bp.route("/api/model")
def api_model():
    """3D model (model3d.pack binary) of a seed, or of ?parts=id,id,... from the Designer."""
    a = request.args
    ship = a.get("ship", "fighter")
    if ship not in ROOTS:
        raise ValueError(f"unknown ship type {ship!r}")
    parts = [p for p in a.get("parts", "").split(",") if p] if "parts" in a else None
    seed = a.get("seed") or "0x0"
    colours = {}
    if parts is None and ship not in NO_SEED_LOOK:
        try:
            cols = textures.ship_look(seed, ship)["colours"]
            colours = {"paint": cols["primary"]["rgb"], "secondary": cols["secondary"]["rgb"],
                       "dark": cols["undercoat"]["rgb"]}
        except Exception:  # colours are a bonus; the shape still shows
            pass
    for k in ("paint", "secondary", "dark"):
        if a.get(k):
            h = a[k].lstrip("#")
            colours[k] = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    data = model3d.pack(model3d.ship_model(seed, ship, parts, a.get("fill") == "1"), colours)
    return Response(data, mimetype="application/octet-stream", headers={"Cache-Control": "no-store"})


@bp.route("/api/design/types")
def api_design_types():
    return jsonify([{"ship": k, "label": SHIP_LABELS.get(k, k)} for k in ROOTS])

@functools.lru_cache(maxsize=None)
def design_tree(ship):
    """The part tree for the Designer. Each option carries the weight the game gives it when
    picking, so the page can work out how rare a design is (a "xRARE" option weighs 1, not 20)."""
    from nms_procgen.generator import option_weight
    names = part_names(ship)

    def groups(gs):
        out = []
        for g in gs:
            opts = []
            for o in g["opts"]:
                kids = [grp for k in o["kids"] for grp in groups(k)]
                for r in o["refs"]:
                    p = ref_to_descriptor(r)
                    if p:
                        kids += groups(load_descriptor(p))
                opts.append({"id": o["id"], "name": names.get(o["id"], ""), "children": kids,
                             "weight": option_weight(o)})
            out.append({"type": g["type"], "options": opts})
        return out

    return groups(load_descriptor(ROOTS[ship]))  # relative to wherever the part data lives


@bp.route("/api/design/tree")
def api_design_tree():
    return jsonify(design_tree(request.args.get("ship", "sentinel")))


HEX = lambda rgb: "#" + "".join(f"{round(float(v) * 255):02x}" for v in rgb[:3])


@bp.route("/api/look")
def api_look():
    ship, seed = request.args.get("ship", ""), request.args.get("seed", "")
    if ship not in ROOTS:
        raise ValueError(f"unknown ship type {ship!r}")
    if ship in NO_SEED_LOOK:
        return jsonify({"seed_driven": False})
    look = textures.ship_look(seed, ship)
    return jsonify({"seed_driven": True, **look, "keys": textures.look_keys(seed)})


@bp.route("/api/look/options")
def api_look_options():
    pals = textures.palettes()
    return jsonify({"modes": textures.mode_names(), "no_seed_look": sorted(NO_SEED_LOOK),
                    "paint": [HEX(c) for c in pals[textures.PAINT][0]],
                    "undercoat": [HEX(c) for c in pals[textures.UNDERCOAT][0]]})


def run_job(job, ship, want, n, seconds, look=None):
    try:
        for seed, parts in fast_search(ship, want, (), n, time_limit=seconds, stats=job["stats"],
                                       should_stop=lambda: job["cancel"], look=look):
            job["results"].append({"seed": f"0x{seed:016X}", "parts": [p for _, p in parts],
                                   "look": textures.look_keys(seed) if ship not in NO_SEED_LOOK else None})
        job["status"] = "cancelled" if job["cancel"] else "done"
    except Exception as e:  # reported to the UI
        job["status"], job["error"] = "error", str(e)


DESIGN_DIRS = [str(ROOT / "nms_procgen" / "designs"),
               os.path.join(gamefiles.CACHE, "designs")]  # the ones that ship with the app, then your own


def read_designs():
    """Saved part lists, e.g. the Dark Unicorn: [{id, name, ship, notes, want, avoid, seeds, mine}]."""
    out = {}
    for i, folder in enumerate(DESIGN_DIRS):
        for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            key = os.path.splitext(os.path.basename(path))[0]
            out[key] = {"id": key, "name": d.get("name") or key.replace("_", " ").title(),
                        "ship": d.get("ship", "sentinel"), "notes": d.get("notes", ""),
                        "want": d.get("want", []), "avoid": d.get("avoid", []),
                        "seeds": d.get("found_seeds", d.get("seeds", [])), "mine": i == 1}
    return sorted(out.values(), key=lambda d: (d["mine"], d["name"].lower()))


@bp.route("/api/designs", methods=["GET", "POST"])
def api_designs():
    if request.method == "GET":
        return jsonify(read_designs())
    b = body()
    name = (b.get("name") or "").strip()
    if not name:
        raise ValueError("give the design a name")
    if b.get("ship") not in ROOTS:
        raise ValueError("pick a ship type first")
    key = save_design(clean_design({"name": name, "ship": b["ship"], "notes": b.get("notes", ""),
                                      "want": b.get("want", []), "avoid": b.get("avoid", []),
                                      "found_seeds": b.get("seeds", [])}))
    return jsonify({"ok": True, "id": key, "designs": read_designs()})


def find_design(key):
    d = next((x for x in read_designs() if x["id"] == key), None)
    if not d:
        raise ValueError(f"no saved design called {key!r}")
    return d


def clean_design(data):
    """Check a design (from a file or the page) before it is saved or used."""
    if not isinstance(data, dict):
        raise ValueError("that is not a design file")
    ship = data.get("ship")
    if ship not in ROOTS:
        raise ValueError(f"the design is for an unknown ship type ({ship!r})")
    from nms_procgen.generator import all_parts
    known = {p for ps in all_parts(ship).values() for p in ps}
    want = [str(p).upper() for p in data.get("want", [])]
    unknown = [p for p in want if p not in known]
    if unknown:
        raise ValueError(f"these parts do not exist for a {ship} in this game version: {', '.join(unknown[:6])}")
    if not want:
        raise ValueError("the design has no parts")
    seeds = []
    for x in data.get("found_seeds", data.get("seeds", [])) or []:
        try:
            seeds.append(f"0x{int(str(x), 0) & (1 << 64) - 1:016X}")
        except ValueError:
            pass
    name = str(data.get("name") or "Imported design").strip()[:60]
    return {"name": name, "ship": ship, "notes": str(data.get("notes", ""))[:2000], "want": want,
            "avoid": [str(p).upper() for p in data.get("avoid", [])], "found_seeds": seeds}


def save_design(d):
    key = re.sub(r"[^a-z0-9]+", "_", d["name"].lower()).strip("_") or "design"
    os.makedirs(DESIGN_DIRS[1], exist_ok=True)
    with open(os.path.join(DESIGN_DIRS[1], key + ".json"), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    return key


@bp.route("/api/designs/<key>/file")
def api_design_file(key):
    """The design as a file you can keep or share."""
    d = find_design(key)
    data = {"name": d["name"], "ship": d["ship"], "notes": d["notes"], "want": d["want"], "avoid": d["avoid"],
            "found_seeds": d["seeds"], "made_with": "NMS Ship Studio"}
    return jsonify({"ok": True, "filename": f"{key}.nmsdesign.json", "text": json.dumps(data, indent=1)})


@bp.route("/api/designs/import", methods=["POST"])
def api_design_import():
    b = body()
    try:
        data = json.loads(b.get("text", ""))
    except ValueError:
        raise ValueError("that file is not a design (not JSON)") from None
    d = clean_design(data)
    return jsonify({"ok": True, "id": save_design(d), "name": d["name"], "designs": read_designs()})


def matching_seed(ship, want, seeds):
    """First saved seed that really builds the design in this game version."""
    from nms_procgen.generator import part_ids
    for seed in seeds:
        if set(want) <= set(part_ids(int(seed, 16), ship)):
            return seed
    return None


def put_design(path, ship, want, seed, slot, name):
    """Write one design's seed into a ship slot ("new" = the first empty slot)."""
    opened = open_save(path)
    r = opened.readable
    owned = r["BaseContext"]["PlayerStateData"]["ShipOwnership"]
    filename = model_filename(ship)
    if slot == "new":
        empty = [i for i, e in enumerate(owned) if not e.get("Resource", {}).get("Filename")]
        if not empty:
            raise ValueError("no empty ship slot in this save -- pick one of your ships to replace instead")
        slot = empty[0]
        ships.create_ship(r, slot, filename, seed, name[:64], player.primary_ship(r))
        what = f"new ship in slot {slot}"
    else:
        slot = int(slot)
        if not owned[slot].get("Resource", {}).get("Filename"):
            raise ValueError(f"slot {slot} is empty")
        current = ship_alias(owned[slot]["Resource"]["Filename"])
        if current == ship:
            ships.set_ship_seed(r, slot, seed)
        else:
            ships.set_ship_model(r, slot, filename, seed)
        what = f"slot {slot}"
    backup = write(opened)
    # Read the file back: the change must really be in the save the game will load.
    check = next((x for x in ships.list_ships(open_save(path).readable) if x.index == slot), None)
    if not check or ship_alias(check.filename) != ship or int(str(check.seed), 16) != int(seed, 16):
        raise RuntimeError(f"the save was written but slot {slot} does not read back as this ship -- "
                           f"restore the backup {os.path.basename(backup or '')} and report this")
    return {"slot": slot, "seed": seed, "what": what, "backup": backup, "file": os.path.basename(path)}


def run_install(job, path, design, slot, seconds):
    try:
        ship, want = design["ship"], design["want"]
        seed = matching_seed(ship, want, design.get("seeds") or design.get("found_seeds") or [])
        if not seed:
            job["phase"] = "searching"
            for s, _parts in fast_search(ship, want, design.get("avoid", ()), 1, time_limit=seconds,
                                         stats=job["stats"], should_stop=lambda: job["cancel"]):
                seed = f"0x{s:016X}"
                break
        if job["cancel"]:
            job["status"] = "cancelled"
            return
        if not seed:
            raise ValueError(f"no seed with all {len(want)} parts turned up in {seconds} s. This design is rare: "
                             "give it more time, or set a few details back to Any and save it again.")
        job["phase"] = "writing"
        job["result"] = put_design(path, ship, want, seed, slot, design.get("name", ""))
        job["status"] = "done"
    except Exception as e:  # shown in the page
        job["status"], job["error"] = "error", str(e)


@bp.route("/api/ship/put", methods=["POST"])
def api_ship_put():
    """Put one exact seed into the save: a new ship slot, or replace a slot (changing its ship type if needed)."""
    b = body()
    ship = b.get("ship")
    if ship not in ROOTS:
        raise ValueError(f"unknown ship type {ship!r}")
    if game_running():
        raise GameRunning("No Man's Sky is running -- quit the game first, or it will overwrite this change.")
    seed = f"0x{int(str(b['seed']), 16) & (1 << 64) - 1:016X}"
    return jsonify({"ok": True, **put_design(b.get("path"), ship, None, seed, b.get("slot", "new"),
                                              b.get("name") or SHIP_LABELS.get(ship, ship))})


@bp.route("/api/designs/install", methods=["POST"])
def api_design_install():
    """Put a design into the save: a saved seed if one still matches, otherwise a quick search first."""
    b = body()
    if game_running():
        raise GameRunning("No Man's Sky is running -- quit the game first, or it will overwrite this change.")
    design = find_design(b["id"]) if b.get("id") else dict(clean_design(b.get("design") or {}))
    if "seeds" not in design:
        design["seeds"] = design.get("found_seeds", [])
    open_save(b.get("path"))  # fail early on a bad path
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = job = {"status": "running", "phase": "checking", "results": [], "stats": {}, "cancel": False,
                          "error": None, "kind": "install", "result": None, "ship": design["ship"]}
    threading.Thread(target=run_install, args=(job, b.get("path"), design, b.get("slot", "new"),
                                               limit_seconds(b)), daemon=True).start()
    return jsonify({"ok": True, "job": job_id})


@bp.route("/api/designs/<key>", methods=["DELETE"])
def api_design_delete(key):
    path = os.path.join(DESIGN_DIRS[1], os.path.basename(key) + ".json")
    if not os.path.exists(path):
        raise ValueError("that design is built in and cannot be deleted")
    os.remove(path)
    return jsonify({"ok": True, "designs": read_designs()})


@bp.route("/api/design/search", methods=["POST"])
def api_design_search():
    b = body()
    ship = b.get("ship", "sentinel")
    if ship not in ROOTS:
        raise ValueError(f"unknown ship type {ship!r}")
    look = parse_look(b.get("look")) if ship not in NO_SEED_LOOK else {}
    want = list(b.get("want", []))
    if not want and not look:
        raise ValueError("Pick at least one part or colour first.")
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = job = {"status": "running", "results": [], "stats": {}, "cancel": False, "error": None,
                          "ship": ship}
    threading.Thread(target=run_job, args=(job, ship, want, max(1, min(int(b.get("n", 5)), 50)),
                                           limit_seconds(b), look), daemon=True).start()
    return jsonify({"ok": True, "job": job_id})


@bp.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        raise ValueError("unknown job")
    return jsonify({"status": job["status"], "results": job["results"], "error": job["error"],
                    "tested": job["stats"].get("tested", 0), "seconds": job["stats"].get("seconds", 0),
                    "regions": job["stats"].get("regions", 0), "total_regions": job["stats"].get("total_regions", 0),
                    "phase": job.get("phase"), "result": job.get("result")})


@bp.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def api_job_cancel(job_id):
    if job_id in JOBS:
        JOBS[job_id]["cancel"] = True
    return jsonify({"ok": True})
