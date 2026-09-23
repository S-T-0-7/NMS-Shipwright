"""NMS Seed Editor -- local backend for the desktop app (nms_editor.py).

Binds to 127.0.0.1 only. Every write goes through save.OpenSave.write(), which
backs the file up first, and is refused while No Man's Sky is running (the game
would overwrite the change on its next save).

    python nms_editor.py          # desktop window
    python webapp/app.py          # same UI in your browser at http://127.0.0.1:5000
"""
from __future__ import annotations

import functools
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import uuid
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, Response, jsonify, request, send_from_directory  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from nms_procgen import model3d, ROOTS, explain, load_descriptor, locate, ref_to_descriptor, render, systemgen, textures  # noqa: E402
from nms_procgen.fastsearch import fast_search  # noqa: E402
from nms_save import extras, gamefiles, gamepath, gameversion, items, catalog, locator, player, quests, save, ships  # noqa: E402

app = Flask(__name__, static_folder=None)
STATIC = os.path.join(os.path.dirname(__file__), "static")

SHIP_LABELS = {"fighter": "Fighter", "hauler": "Hauler", "explorer": "Explorer", "shuttle": "Shuttle",
               "exotic": "Exotic", "living": "Living Ship", "solar": "Solar", "sentinel": "Sentinel",
               "freighter": "Freighter", "capital_freighter": "Capital Freighter"}
SHIP_MODELS = {k: "MODELS/" + v[len("models/"):].upper().replace(".DESCRIPTOR.MBIN", ".SCENE.MBIN")
               for k, v in ROOTS.items() if k not in ("freighter", "capital_freighter")}
PALETTES = {k: v["colours"] for k, v in json.load(open(ROOT / "data" / "palettes" / "customisation.json"))["palettes"].items()
            if v["num_colours_enum"] == 5}


@functools.lru_cache(maxsize=None)
def part_names(ship):
    path = ROOT / "nms_procgen" / "names" / f"{ship}.json"
    names = {}
    if path.exists():
        for row in json.load(open(path)):
            names.setdefault(row["id"], row["name"])
    return names


def ship_alias(filename):
    base = os.path.basename(filename or "").lower().replace(".scene.mbin", ".descriptor.mbin")
    return next((alias for alias, rel in ROOTS.items() if rel.split("/")[-1] == base), None)


class GameRunning(RuntimeError):
    pass


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NMS.exe"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except OSError:
        return False
    return "NMS.exe" in out


def open_save(path):
    if not path or not os.path.exists(path):
        raise ValueError("Missing or invalid save path")
    return save.open_save(path)


def write(opened):
    if game_running():
        raise GameRunning("No Man's Sky is running -- quit the game first, or it will overwrite this change.")
    return opened.write()


def body():
    return request.get_json(force=True) or {}


def limit_seconds(b, default=120):
    """Seconds a search may run; None (or 0) means "keep going until I press Stop"."""
    v = b.get("seconds", default)
    if v in (None, 0, "", "0"):
        return None
    return max(5.0, min(float(v), 86400.0))


# Anything that means "the game files are not what this version of the tool expects" -- usually
# a game update. These are reported with a hint instead of a raw error.
GAME_DATA_ERRORS = (gameversion.GameDataError, gamefiles.GameFileError, gamepath.GamePathError,
                    items.ItemError, quests.QuestDataError)
UPDATE_HINT = ("No Man's Sky looks different than expected -- it was probably updated. "
               "Open Save > Game data and press 'Re-read game files'. If that does not help, this part of "
               "the tool needs updating for the new game version.")


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):  # 404s etc. keep their own status
        return e
    from nms_save.gamemeta import MetaError
    from nms_procgen.exeaddr import AddressError
    if isinstance(e, (MetaError, AddressError) + GAME_DATA_ERRORS):
        return jsonify({"ok": False, "error": str(e), "hint": UPDATE_HINT, "game_data": True}), 503
    code = 409 if isinstance(e, GameRunning) else 400 if isinstance(e, (ValueError, ships.ShipLookupError)) else 500
    return jsonify({"ok": False, "error": str(e)}), code


def _check(name, need, fn):
    """Run one health check; never raises."""
    try:
        return {"name": name, "needed_for": need, "ok": True, "detail": fn()}
    except Exception as e:
        return {"name": name, "needed_for": need, "ok": False, "detail": f"{type(e).__name__}: {e}"}


def _save_format():
    """Read the newest save and confirm the fields the tool relies on are still there."""
    saves = locator.find_saves()
    if not saves:
        return "no saves to check"
    r = open_save(saves[0].path).readable
    ps = r["BaseContext"]["PlayerStateData"]
    need = ("ShipOwnership", "Inventory", "Multitools", "KnownProducts", "MissionProgress", "Units")
    missing = [k for k in need if k not in ps]
    if missing:
        raise gameversion.GameDataError(f"the save no longer has {', '.join(missing)} -- "
                                        "No Man's Sky changed its save format")
    odd = [k for k in ps if len(k) <= 3 and not k.isalpha()]
    return f"{len(ps)} fields, all known" if not odd else f"{len(ps)} fields, {len(odd)} unknown to this version"


def health(deep=False):
    from nms_procgen import model3d
    from nms_procgen.exeaddr import resolve
    from nms_save.gamemeta import exe_meta
    state = _check("Game install", "everything", lambda: f"{gamepath.require()} -- build "
                                                         f"{gameversion.build_id()['exe'][0]} bytes, "
                                                         f"{gameversion.build_id()['paks']} archives")
    checks = [state,
              _check("Game code layouts", "quests, items, 3D models",
                     lambda: f"{len(exe_meta().layout('cGcProductData').fields)} fields read from NMS.exe"),
              _check("Item tables", "inventory, unlocks", lambda: f"{len(items.catalogue())} items"),
              _check("Language text", "quest and item names", lambda: f"{len(quests.strings())} lines"),
              _check("Quest tables", "quest skipping", lambda: f"{len(quests.missions())} quests"),
              _check("Recipes and rewards", "unlocks", lambda: f"{len(extras.recipes())} recipes, "
                                                               f"{len(extras.shop_specials())} shop items"),
              _check("Ship generator addresses", "Find in game, system lookup",
                     lambda: "build %s, %d addresses" % (resolve()["build"][0], len(resolve()))),
              _check("Save files", "everything", lambda: f"{len(locator.find_saves())} saves found"),
              _check("Save format", "everything", _save_format)]
    if deep:
        checks += [_check("Ship generator", "Find in game, system lookup",
                          lambda: "system 0xBE0008220992 -> %d ships" % len(system_gen().system(0xBE0008220992)["ships"])),
                   _check("Ship colours", "colours and finish",
                          lambda: textures.ship_look("0x8BA812880CFAAA1C", "fighter")["colours"]["primary"]["index"] and "ok"),
                   _check("3D models", "ship viewer",
                          lambda: "%d triangles" % (sum(len(g[1]) for g in model3d.ship_model("0x1", "fighter")["groups"].values()) // 3))]
    try:
        build = gameversion.check()
    except Exception:  # no game found yet: the page still needs to load, to offer the folder picker
        build = {"build": {"exe": [0, 0], "paks": 0}, "changed": False, "first_run": True}
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "build": build["build"],
            "nms_dir": gamepath.find(),
            "updated": build["changed"], "first_run": build["first_run"], "deep": deep}


try:  # at start-up, drop anything cached from an older game build
    gameversion.check()
except Exception as _e:  # reported by /api/health instead
    pass


@app.route("/api/health")
def api_health():
    return jsonify(health(request.args.get("deep") == "1"))


@app.route("/api/gamedir", methods=["POST"])
def api_gamedir():
    """Point the tool at the player's No Man's Sky folder (when it was not found on its own)."""
    folder = gamepath.save_dir(body().get("path", ""))
    gameversion.refresh(everything=True)  # anything read from the old guess is wrong
    SYSGEN["sg"] = None
    return jsonify({"ok": True, "nms_dir": folder, "health": health(False)})


@app.route("/api/health/refresh", methods=["POST"])
def api_health_refresh():
    """Throw away the copies of game files and read them again (after a game update)."""
    gameversion.refresh(everything=bool(body().get("everything", True)))
    SYSGEN["sg"] = None  # the emulator holds the old game code
    return jsonify(health(False))


@app.route("/favicon.ico")
def favicon():
    return Response(status=204)


# ------------------------------------------------------------------ pages --

@app.route("/")
def index():
    return send_from_directory(STATIC, "editor.html")


@app.route("/static/<path:name>")
def static_file(name):
    return send_from_directory(STATIC, name)


# ----------------------------------------------------------- saves/ships --

@app.route("/api/status")
def api_status():
    return jsonify({"game_running": game_running()})


SAVE_INFO = {}  # (path, mtime) -> summary shown in the save picker


def save_info(s):
    key = (s.path, s.mtime)
    if key not in SAVE_INFO:
        try:
            r = open_save(s.path).readable
            ps, common = r["BaseContext"]["PlayerStateData"], r.get("CommonStateData", {})
            SAVE_INFO[key] = {"name": common.get("SaveName") or "", "summary": ps.get("SaveSummary") or "",
                              "playtime": common.get("TotalPlayTime") or ps.get("TotalPlayTime") or 0,
                              "difficulty": ps.get("DifficultyState", {}).get("Preset", {}).get("DifficultyPresetType", ""),
                              "units": ps.get("Units", 0)}
        except Exception:  # unreadable / half-written save: still list it
            SAVE_INFO[key] = {}
    return SAVE_INFO[key]


@app.route("/api/saves")
def api_saves():
    return jsonify([{"path": s.path, "profile": s.profile, "slot_name": s.slot_name, "mtime": s.mtime, "size": s.size,
                     "slot": s.slot, "kind": s.kind, **save_info(s)}
                    for s in locator.find_saves()])


@app.route("/api/ships")
def api_ships():
    opened = open_save(request.args.get("path"))
    primary = player.primary_ship(opened.readable)
    known, galaxy = locate.save_known_systems(opened.readable), locate.save_galaxy(opened.readable)
    out = []
    for s in ships.list_ships(opened.readable):
        alias = ship_alias(s.filename) if s.is_procedural else None
        origin = locate.locate(s.seed, known_systems=known, galaxy=galaxy) if alias and s.seed else []
        out.append({"index": s.index, "name": s.name, "filename": s.filename, "seed": s.seed, "ship": alias,
                    "category": SHIP_LABELS.get(alias, s.category_guess), "is_procedural": s.is_procedural,
                    "is_golden_vector": s.is_golden_vector, "primary": s.index == primary,
                    "has_render": bool(alias and render.available(alias)),
                    "paint": ships.get_ship_paint(opened.readable, s.index),
                    "wrong_tech": ships.wrong_core_tech(s.raw),
                    "origin": origin[:3]})
    entries = opened.readable["BaseContext"]["PlayerStateData"]["ShipOwnership"]
    empty = [i for i, e in enumerate(entries) if not e.get("Resource", {}).get("Filename")]
    return jsonify({"ships": out, "empty": empty})


@app.route("/api/models")
def api_models():
    return jsonify([{"ship": k, "label": SHIP_LABELS.get(k, k), "filename": f} for k, f in SHIP_MODELS.items()])


def model_filename(ship):
    if ship not in SHIP_MODELS:
        raise ValueError(f"unknown ship type {ship!r}")
    return SHIP_MODELS[ship]


@app.route("/api/ship/create", methods=["POST"])
def api_ship_create():
    b = body()
    opened = open_save(b.get("path"))
    slot = int(b["slot"])
    ships.create_ship(opened.readable, slot, model_filename(b.get("ship")), (b.get("seed") or "").strip(),
                      str(b.get("name", ""))[:64], int(b["clone_from"]))
    return jsonify({"ok": True, "slot": slot, "backup": write(opened)})


@app.route("/api/ship/model", methods=["POST"])
def api_ship_model():
    b = body()
    opened = open_save(b.get("path"))
    seed = (b.get("seed") or "").strip() or None
    ships.set_ship_model(opened.readable, int(b["slot"]), model_filename(b.get("ship")), seed)
    return jsonify({"ok": True, "backup": write(opened)})


def apply_seed(path, slot, seed):
    opened = open_save(path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        updated = ships.set_ship_seed(opened.readable, int(slot), seed)
    backup = write(opened)
    return jsonify({"ok": True, "seed": updated.seed, "backup": backup,
                    "warning": str(caught[0].message) if caught else None})


@app.route("/api/ship/seed", methods=["POST"])
def api_ship_seed():
    b = body()
    return apply_seed(b.get("path"), b.get("slot"), (b.get("seed") or "").strip())


@app.route("/api/ship/reroll", methods=["POST"])
def api_ship_reroll():
    b = body()
    return apply_seed(b.get("path"), b.get("slot"), f"0x{random.getrandbits(64):016X}")


@app.route("/api/ship/name", methods=["POST"])
def api_ship_name():
    b = body()
    opened = open_save(b.get("path"))
    ships.set_ship_name(opened.readable, int(b["slot"]), str(b.get("name", ""))[:64])
    return jsonify({"ok": True, "backup": write(opened)})


@app.route("/api/ship/paint", methods=["POST"])
def api_ship_paint():
    b = body()
    opened = open_save(b.get("path"))
    ships.set_ship_paint(opened.readable, int(b["slot"]), b.get("primary", [0, 0, 0]), b.get("accent"),
                         b.get("palette", "FREIGHTER"))
    return jsonify({"ok": True, "backup": write(opened)})


@app.route("/api/ship/refit", methods=["POST"])
def api_ship_refit():
    """Swap a ship's built-in parts for the ones its own type comes with."""
    b = body()
    opened = open_save(b.get("path"))
    slot = int(b["slot"])
    entry = ships._populated_entry(opened.readable, slot)
    swaps = ships.set_core_tech(opened.readable, slot, ships.is_sentinel(entry["Resource"]["Filename"]))
    if not swaps:
        raise ValueError("this ship already has the right parts")
    names = items.catalogue()

    def label(i):
        return i if i.startswith("(") else names.get(i, {}).get("name", i)

    return jsonify({"ok": True, "backup": write(opened),
                    "swaps": [{"from": label(a), "to": label(c)} for a, c in swaps]})


@app.route("/api/ship/paint/clear", methods=["POST"])
def api_ship_paint_clear():
    b = body()
    opened = open_save(b.get("path"))
    ships.clear_ship_paint(opened.readable, int(b["slot"]))
    return jsonify({"ok": True, "backup": write(opened)})


@app.route("/api/palettes")
def api_palettes():
    return jsonify(PALETTES)


# ----------------------------------------------------------- generation --

@app.route("/api/parts")
def api_parts():
    ship, seed = request.args.get("ship", "fighter"), request.args.get("seed", "0x0")
    names = part_names(ship if ship in ROOTS else ship_alias(ship) or "")
    return jsonify({"parts": [{"depth": d, "group": g, "id": pid, "name": names.get(pid, ""), "label": label,
                               "choices": len(alts) + 1} for d, g, pid, alts, label in explain(seed, ship)]})


def png(data):
    if not data:
        return jsonify({"ok": False, "error": "no preview renders for this ship type"}), 404
    return Response(data, mimetype="image/png", headers={"Cache-Control": "max-age=86400"})


@app.route("/api/render.png")
def api_render_seed():
    a = request.args
    return png(render.seed_png(a.get("seed", "0x0"), a.get("ship", "sentinel"), int(a.get("size", 512)),
                               a.get("mirror", "1") == "1"))


@app.route("/api/model")
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


@app.route("/api/render/parts", methods=["POST"])
def api_render_parts():
    b = body()
    ship = b.get("ship", "sentinel")
    img = render.render_parts(b.get("parts", []), ship, int(b.get("size", 640)), bool(b.get("mirror", 1)))
    if img is None and render.available(ship):
        return Response(status=204)  # renders exist, the selected parts just have none of their own
    return png(render.to_png(img) if img else None)


@app.route("/api/design/types")
def api_design_types():
    return jsonify([{"ship": k, "label": SHIP_LABELS.get(k, k), "has_render": render.available(k)} for k in ROOTS])


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


@app.route("/api/design/tree")
def api_design_tree():
    return jsonify(design_tree(request.args.get("ship", "sentinel")))


NO_SEED_LOOK = {"sentinel"}  # sentinel colour comes from its parts and the player's paint, not the seed
HEX = lambda rgb: "#" + "".join(f"{round(float(v) * 255):02x}" for v in rgb[:3])


@app.route("/api/look")
def api_look():
    ship, seed = request.args.get("ship", ""), request.args.get("seed", "")
    if ship not in ROOTS:
        raise ValueError(f"unknown ship type {ship!r}")
    if ship in NO_SEED_LOOK:
        return jsonify({"seed_driven": False})
    look = textures.ship_look(seed, ship)
    return jsonify({"seed_driven": True, **look, "keys": textures.look_keys(seed)})


@app.route("/api/look/options")
def api_look_options():
    pals = textures.palettes()
    return jsonify({"modes": textures.mode_names(), "no_seed_look": sorted(NO_SEED_LOOK),
                    "paint": [HEX(c) for c in pals[textures.PAINT][0]],
                    "undercoat": [HEX(c) for c in pals[textures.UNDERCOAT][0]]})


def parse_look(raw):
    look = {}
    for k in ("primary", "secondary", "undercoat"):
        v = [int(x) for x in (raw or {}).get(k) or []]
        if any(not 0 <= x < 64 for x in v):
            raise ValueError(f"{k} colour index must be 0-63")
        if v:
            look[k] = set(v)
    modes = [str(m).upper() for m in (raw or {}).get("mode") or []]
    if set(modes) - set(textures.mode_names()):
        raise ValueError(f"unknown hull finish; choose from {', '.join(textures.mode_names())}")
    if modes:
        look["mode"] = set(modes)
    return look


JOBS: dict[str, dict] = {}


def run_job(job, ship, want, n, seconds, look=None):
    try:
        for seed, parts in fast_search(ship, want, (), n, time_limit=seconds, stats=job["stats"],
                                       should_stop=lambda: job["cancel"], look=look):
            job["results"].append({"seed": f"0x{seed:016X}", "parts": [p for _, p in parts],
                                   "look": textures.look_keys(seed) if ship not in NO_SEED_LOOK else None})
        job["status"] = "cancelled" if job["cancel"] else "done"
    except Exception as e:  # reported to the UI
        job["status"], job["error"] = "error", str(e)


DESIGN_DIRS = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nms_procgen", "designs"),
               os.path.join(gamefiles.CACHE, "designs")]  # shipped designs, then your own


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


@app.route("/api/designs", methods=["GET", "POST"])
def api_designs():
    if request.method == "GET":
        return jsonify(read_designs())
    b = body()
    name = (b.get("name") or "").strip()
    if not name:
        raise ValueError("give the design a name")
    if b.get("ship") not in ROOTS:
        raise ValueError("pick a ship type first")
    key = _save_design(_clean_design({"name": name, "ship": b["ship"], "notes": b.get("notes", ""),
                                      "want": b.get("want", []), "avoid": b.get("avoid", []),
                                      "found_seeds": b.get("seeds", [])}))
    return jsonify({"ok": True, "id": key, "designs": read_designs()})


def _find_design(key):
    d = next((x for x in read_designs() if x["id"] == key), None)
    if not d:
        raise ValueError(f"no saved design called {key!r}")
    return d


def _clean_design(data):
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


def _save_design(d):
    key = re.sub(r"[^a-z0-9]+", "_", d["name"].lower()).strip("_") or "design"
    os.makedirs(DESIGN_DIRS[1], exist_ok=True)
    with open(os.path.join(DESIGN_DIRS[1], key + ".json"), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    return key


@app.route("/api/designs/<key>/file")
def api_design_file(key):
    """The design as a file you can keep or share."""
    d = _find_design(key)
    data = {"name": d["name"], "ship": d["ship"], "notes": d["notes"], "want": d["want"], "avoid": d["avoid"],
            "found_seeds": d["seeds"], "made_with": "NMS Ship Studio"}
    return jsonify({"ok": True, "filename": f"{key}.nmsdesign.json", "text": json.dumps(data, indent=1)})


@app.route("/api/designs/import", methods=["POST"])
def api_design_import():
    b = body()
    try:
        data = json.loads(b.get("text", ""))
    except ValueError:
        raise ValueError("that file is not a design (not JSON)") from None
    d = _clean_design(data)
    return jsonify({"ok": True, "id": _save_design(d), "name": d["name"], "designs": read_designs()})


def _matching_seed(ship, want, seeds):
    """First saved seed that really builds the design in this game version."""
    from nms_procgen.generator import part_ids
    for seed in seeds:
        if set(want) <= set(part_ids(int(seed, 16), ship)):
            return seed
    return None


def _put_design(path, ship, want, seed, slot, name):
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
        seed = _matching_seed(ship, want, design.get("seeds") or design.get("found_seeds") or [])
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
        job["result"] = _put_design(path, ship, want, seed, slot, design.get("name", ""))
        job["status"] = "done"
    except Exception as e:  # shown in the page
        job["status"], job["error"] = "error", str(e)


@app.route("/api/ship/put", methods=["POST"])
def api_ship_put():
    """Put one exact seed into the save: a new ship slot, or replace a slot (changing its ship type if needed)."""
    b = body()
    ship = b.get("ship")
    if ship not in ROOTS:
        raise ValueError(f"unknown ship type {ship!r}")
    if game_running():
        raise GameRunning("No Man's Sky is running -- quit the game first, or it will overwrite this change.")
    seed = f"0x{int(str(b['seed']), 16) & (1 << 64) - 1:016X}"
    return jsonify({"ok": True, **_put_design(b.get("path"), ship, None, seed, b.get("slot", "new"),
                                              b.get("name") or SHIP_LABELS.get(ship, ship))})


@app.route("/api/designs/install", methods=["POST"])
def api_design_install():
    """Put a design into the save: a saved seed if one still matches, otherwise a quick search first."""
    b = body()
    if game_running():
        raise GameRunning("No Man's Sky is running -- quit the game first, or it will overwrite this change.")
    design = _find_design(b["id"]) if b.get("id") else dict(_clean_design(b.get("design") or {}))
    if "seeds" not in design:
        design["seeds"] = design.get("found_seeds", [])
    open_save(b.get("path"))  # fail early on a bad path
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = job = {"status": "running", "phase": "checking", "results": [], "stats": {}, "cancel": False,
                          "error": None, "kind": "install", "result": None, "ship": design["ship"]}
    threading.Thread(target=run_install, args=(job, b.get("path"), design, b.get("slot", "new"),
                                               limit_seconds(b)), daemon=True).start()
    return jsonify({"ok": True, "job": job_id})


@app.route("/api/designs/<key>", methods=["DELETE"])
def api_design_delete(key):
    path = os.path.join(DESIGN_DIRS[1], os.path.basename(key) + ".json")
    if not os.path.exists(path):
        raise ValueError("that design is built in and cannot be deleted")
    os.remove(path)
    return jsonify({"ok": True, "designs": read_designs()})


@app.route("/api/design/search", methods=["POST"])
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


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        raise ValueError("unknown job")
    return jsonify({"status": job["status"], "results": job["results"], "error": job["error"],
                    "tested": job["stats"].get("tested", 0), "seconds": job["stats"].get("seconds", 0),
                    "regions": job["stats"].get("regions", 0), "total_regions": job["stats"].get("total_regions", 0),
                    "has_render": render.available(job["ship"]) if job.get("ship") else False,
                    "phase": job.get("phase"), "result": job.get("result")})


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def api_job_cancel(job_id):
    if job_id in JOBS:
        JOBS[job_id]["cancel"] = True
    return jsonify({"ok": True})


# ------------------------------------------------------- find in game --

SYSGEN = {"sg": None}
SYSGEN_LOCK = threading.Lock()


def system_gen():
    if SYSGEN["sg"] is None:
        SYSGEN["sg"] = systemgen.SystemGen()
    return SYSGEN["sg"]


@app.route("/api/location")
def api_location():
    opened = open_save(request.args.get("path"))
    known = sorted(locate.save_known_systems(opened.readable))
    return jsonify({"current": locate.describe(locate.save_location(opened.readable)),
                    "visited": [locate.describe(u) for u in known]})


@app.route("/api/system")
def api_system():
    ua = locate.parse_address(request.args.get("addr", ""), int(request.args.get("galaxy", 0)))
    with SYSGEN_LOCK:
        s = system_gen().system(ua, planets=True)
    ships = [{**sh, "seed": f"0x{sh['seed']:016X}", "has_render": bool(sh["alias"] and render.available(sh["alias"]))}
             for sh in s["ships"]]
    return jsonify({**locate.describe(ua), "region_valid": s["region_valid"], "planets": s["planets"],
                    "moons": s["moons"], "ships": ships, "dissonant": s["dissonant"], "planet_list": s["planet_list"],
                    "interceptor": None if s["interceptor"] is None else f"0x{s['interceptor']:016X}"})


@app.route("/api/freighter", methods=["GET", "POST"])
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


@app.route("/api/find/warm", methods=["POST"])
def api_find_warm():
    """Start the scan workers while the user is still designing (they take a few seconds to load)."""
    threading.Thread(target=systemgen.warm_up, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/find/scan", methods=["POST"])
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


# ------------------------------------------------ inventories & extras --

@app.route("/api/inventories")
def api_inventories():
    return jsonify(items.list_inventories(open_save(request.args.get("path")).readable))


@app.route("/api/inventory", methods=["GET", "POST"])
def api_inventory():
    if request.method == "GET":
        return jsonify(items.get_inventory(open_save(request.args.get("path")).readable, request.args["inv"]))
    b = body()
    opened = open_save(b.get("path"))
    kw = {k: b[k] for k in ("x", "y", "id", "amount") if b.get(k) is not None}
    inv = items.edit_inventory(opened.readable, b["inv"], b["op"], **kw)
    return jsonify({**inv, "backup": write(opened)})


@app.route("/api/items")
def api_items():
    return jsonify(items.search_items(request.args.get("q", ""), request.args.get("type", "")))


@app.route("/api/extras", methods=["GET", "POST"])
def api_extras():
    if request.method == "GET":
        r = open_save(request.args.get("path")).readable
        return jsonify({"knowledge": extras.knowledge(r), "multitools": extras.multitools(r),
                        "frigates": extras.frigates(r), "companions": extras.companions(r),
                        "frigate_stats": extras.FRIGATE_STATS})
    b = body()
    opened, act, r = open_save(b.get("path")), b.get("action"), None
    if act == "words":
        r = extras.learn_words(opened.readable, b.get("races"))
    elif act in extras.UNLOCKS:
        r = extras.learn_all(opened.readable, act)
    elif act == "multitool":
        extras.edit_multitool(opened.readable, int(b["index"]), b.get("name"), b.get("seed") or None, b.get("class"))
    elif act == "frigate":
        extras.edit_frigate(opened.readable, int(b["index"]), b.get("name"), b.get("class"), b.get("stats"),
                            bool(b.get("repair")), bool(b.get("reroll")))
    elif act == "companion":
        extras.edit_companion(opened.readable, int(b["index"]), b.get("name"), b.get("scale"))
    else:
        raise ValueError(f"unknown action {act!r}")
    return jsonify({"ok": True, "result": r, "backup": write(opened)})


@app.route("/api/rewards", methods=["GET", "POST"])
def api_rewards():
    if request.method == "GET":
        a = request.args
        return jsonify(extras.rewards(open_save(a.get("path")).readable, a.get("group", ""), a.get("q", "")))
    b = body()
    opened = open_save(b.get("path"))
    r = extras.set_rewards(opened.readable, b["group"], b.get("ids"), b.get("unlock"), b.get("redeemed"))
    return jsonify({"ok": True, **r, "backup": write(opened)})


@app.route("/api/raw", methods=["GET", "POST"])
def api_raw():
    if request.method == "GET":
        return jsonify(extras.browse(open_save(request.args.get("path")).readable, request.args.get("at", "")))
    b = body()
    opened = open_save(b.get("path"))
    extras.set_path(opened.readable, b["at"], b["value"])
    return jsonify({"ok": True, "backup": write(opened)})


@app.route("/api/save/export")
def api_save_export():
    opened = open_save(request.args.get("path"))
    name = os.path.basename(opened.path).replace(".hg", ".json")
    return Response(json.dumps(opened.readable, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.route("/api/save/import", methods=["POST"])
def api_save_import():
    b = body()
    opened = open_save(b.get("path"))
    data = json.loads(b["json"]) if isinstance(b.get("json"), str) else b.get("json")
    if not isinstance(data, dict) or "BaseContext" not in data:
        raise ValueError("that file is not an exported save (no BaseContext)")
    opened.readable = data
    return jsonify({"ok": True, "backup": write(opened)})


# ------------------------------------------------------ player / backups --

@app.route("/api/player", methods=["GET", "POST"])
def api_player():
    if request.method == "GET":
        return jsonify(player.get_currencies(open_save(request.args.get("path")).readable))
    b = body()
    opened = open_save(b.get("path"))
    values = player.set_currencies(opened.readable, **{k: b[k] for k in player.CURRENCIES if k in b})
    return jsonify({"ok": True, "values": values, "backup": write(opened)})


@app.route("/api/quests")
def api_quests():
    return jsonify(quests.list_quests(open_save(request.args.get("path")).readable))


@app.route("/api/quests/skip", methods=["POST"])
def api_quests_skip():
    b = body()
    opened = open_save(b.get("path"))
    changed = quests.skip_quests(opened.readable, list(b.get("keys", [])))
    if not changed:
        return jsonify({"ok": True, "changed": [], "backup": None})
    return jsonify({"ok": True, "changed": changed, "backup": write(opened)})


BACKUP_TIME = re.compile(r"\.(\d{8})-(\d{6})-\d+\.bak$")


@app.route("/api/backups")
def api_backups():
    path = request.args.get("path")
    open_save(path)  # validates the path
    out = []
    for f in glob.glob(f"{path}.*.bak"):
        m = BACKUP_TIME.search(f)
        made = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}" if m else ""
        out.append({"file": f, "made": made, "size": os.path.getsize(f)})
    return jsonify(sorted(out, key=lambda x: x["made"], reverse=True))


@app.route("/api/backups/restore", methods=["POST"])
def api_backups_restore():
    b = body()
    path, src = b.get("path"), b.get("file")
    open_save(path)
    if not src or not os.path.exists(src) or not src.startswith(path + "."):
        raise ValueError("Unknown backup file")
    if game_running():
        raise GameRunning("No Man's Sky is running -- quit the game first.")
    safety = save.backup_path_for(path)
    shutil.copy2(path, safety)
    with open(src, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data)
    return jsonify({"ok": True, "safety_copy": safety})


# ----------------------------------------------------------------- catalog --

@app.route("/api/catalog")
def api_catalog():
    rows = catalog.filter_rows(catalog.load_rows(), type_substr=request.args.get("type") or None,
                               colour_substr=request.args.get("colour") or None,
                               source_substr=request.args.get("source") or None)
    return jsonify(rows)


@app.route("/api/catalog/facets")
def api_catalog_facets():
    rows = catalog.load_rows()
    return jsonify({"types": catalog.known_types(rows), "colours": catalog.known_colours(rows), "total": len(rows)})


@app.route("/api/catalog/add", methods=["POST"])
def api_catalog_add():
    b = body()
    added = catalog.add_row((b.get("seed") or "").strip(), type=b.get("type", ""), colours=b.get("colours", ""),
                            nms_version=b.get("nms_version", ""), description=b.get("description", ""),
                            source=b.get("source", "manual"), image_url=b.get("image_url", ""))
    if not added:
        return jsonify({"ok": False, "error": "already in the catalog"}), 409
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
