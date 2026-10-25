"""Saves and the ships in them."""
from __future__ import annotations

import random
import warnings

from flask import Blueprint, jsonify, request

from nms_procgen import locate, systemgen, textures
from nms_save import items, locator, player, ships

from webapp.common import (PALETTES, SHIP_LABELS, SHIP_MODELS, SPECIAL_SHIPS, body, game_running, model_filename,
                           open_save, ship_alias, write)
from webapp.version import VERSION

bp = Blueprint("ships", __name__)


@bp.route("/api/status")
def api_status():
    return jsonify({"game_running": game_running(), "version": VERSION})


SAVE_INFO = {}  # (path, mtime) -> summary shown in the save picker


def save_info(s):
    key = (s.path, s.mtime)
    if key not in SAVE_INFO:
        try:
            r = open_save(s.path).readable
            ps, common = r["BaseContext"]["PlayerStateData"], r.get("CommonStateData", {})
            SAVE_INFO[key] = {"name": common.get("SaveName") or "", "summary": ps.get("SaveSummary") or "",
                              "playtime": common.get("TotalPlayTime") or ps.get("TotalPlayTime") or 0,
                              "difficulty": ps.get("DifficultyState", {}).get("Preset", {})
                                                .get("DifficultyPresetType", ""),
                              "units": ps.get("Units", 0)}
        except Exception:  # unreadable / half-written save: still list it
            SAVE_INFO[key] = {}
    return SAVE_INFO[key]


@bp.route("/api/saves")
def api_saves():
    return jsonify([{"path": s.path, "profile": s.profile, "slot_name": s.slot_name, "mtime": s.mtime, "size": s.size,
                     "slot": s.slot, "kind": s.kind, **save_info(s)}
                    for s in locator.find_saves()])


@bp.route("/api/ships")
def api_ships():
    opened = open_save(request.args.get("path"))
    primary = player.primary_ship(opened.readable)
    known, galaxy = locate.save_known_systems(opened.readable), locate.save_galaxy(opened.readable)
    out = []
    for s in ships.list_ships(opened.readable):
        alias = ship_alias(s.filename) if s.is_procedural else None
        origin = (systemgen.confirm(s.seed, locate.locate(s.seed, known_systems=known, galaxy=galaxy))
                  if alias and s.seed else [])
        out.append({"index": s.index, "name": s.name, "filename": s.filename, "seed": s.seed, "ship": alias,
                    "category": SHIP_LABELS.get(alias, s.category_guess), "is_procedural": s.is_procedural,
                    "is_golden_vector": s.is_golden_vector, "primary": s.index == primary,
                    "paint": ships.get_ship_paint(opened.readable, s.index),
                    "wrong_tech": ships.wrong_core_tech(s.raw),
                    "origin": origin[:3]})
    entries = opened.readable["BaseContext"]["PlayerStateData"]["ShipOwnership"]
    empty = [i for i, e in enumerate(entries) if not e.get("Resource", {}).get("Filename")]
    return jsonify({"ships": out, "empty": empty})


@bp.route("/api/models")
def api_models():
    return jsonify([{"ship": k, "label": SHIP_LABELS.get(k, k), "filename": f} for k, f in SHIP_MODELS.items()]
                   + [{"ship": k, "label": v["label"], "special": True} for k, v in SPECIAL_SHIPS.items()])


@bp.route("/api/ship/create", methods=["POST"])
def api_ship_create():
    """Create a ship in a slot. An empty slot is filled (cloning a chosen ship's inventory & tech,
    or a standard empty one when none is picked); a slot that already holds a ship is replaced,
    keeping that slot's existing inventory & tech."""
    b = body()
    opened = open_save(b.get("path"))
    r = opened.readable
    slot = int(b["slot"])
    owned = r["BaseContext"]["PlayerStateData"]["ShipOwnership"]
    if not (0 <= slot < len(owned)):
        raise ValueError(f"no ship slot {slot}")
    ship = b.get("ship")
    seed, name = (b.get("seed") or "").strip(), str(b.get("name", ""))[:64]
    filled = bool(owned[slot].get("Resource", {}).get("Filename"))
    if ship in SPECIAL_SHIPS:
        ships.install_special_ship(r, slot, SPECIAL_SHIPS[ship]["entry"], name or None)
        action = "replaced" if filled else "created"
    elif filled:
        ships.set_ship_model(r, slot, model_filename(ship), seed or None)
        ships.set_ship_name(r, slot, name)
        action = "replaced"
    else:
        clone = b.get("clone_from")
        standard = clone in (None, "", "standard")
        donor = player.primary_ship(r) if standard else int(clone)
        ships.create_ship(r, slot, model_filename(ship), seed, name, donor, standard=standard)
        action = "created"
    return jsonify({"ok": True, "slot": slot, "action": action, "backup": write(opened)})


@bp.route("/api/ship/remove", methods=["POST"])
def api_ship_remove():
    """Empty a ship slot (remove the ship in it)."""
    b = body()
    opened = open_save(b.get("path"))
    slot = int(b["slot"])
    ships.remove_ship(opened.readable, slot)
    return jsonify({"ok": True, "slot": slot, "backup": write(opened)})


@bp.route("/api/ship/model", methods=["POST"])
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


@bp.route("/api/ship/seed", methods=["POST"])
def api_ship_seed():
    b = body()
    return apply_seed(b.get("path"), b.get("slot"), (b.get("seed") or "").strip())


@bp.route("/api/ship/reroll", methods=["POST"])
def api_ship_reroll():
    b = body()
    return apply_seed(b.get("path"), b.get("slot"), f"0x{random.getrandbits(64):016X}")


@bp.route("/api/ship/name", methods=["POST"])
def api_ship_name():
    b = body()
    opened = open_save(b.get("path"))
    ships.set_ship_name(opened.readable, int(b["slot"]), str(b.get("name", ""))[:64])
    return jsonify({"ok": True, "backup": write(opened)})


@bp.route("/api/ship/paint", methods=["POST"])
def api_ship_paint():
    b = body()
    opened = open_save(b.get("path"))
    out = ships.set_ship_paint(opened.readable, int(b["slot"]), b.get("primary", [0, 0, 0]), b.get("accent"),
                               b.get("palette", "FREIGHTER"), b.get("primary_index"), b.get("accent_index"),
                               b.get("channels"))
    return jsonify({"ok": True, **out, "backup": write(opened)})


@bp.route("/api/ship/stats", methods=["GET", "POST"])
def api_ship_stats():
    """A ship's stat bonuses: what it has, what the game rolls for its type and class, and edits."""
    if request.method == "GET":
        a = request.args
        return jsonify(ships.ship_stats(open_save(a.get("path")).readable, int(a["slot"])))
    b = body()
    opened = open_save(b.get("path"))
    out = ships.set_ship_stats(opened.readable, int(b["slot"]), b.get("values"), b.get("class"), bool(b.get("best")))
    return jsonify({"ok": True, **out, "backup": write(opened)})


@bp.route("/api/ship/refit", methods=["POST"])
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


# What each paint slot is called on screen. The names come from the layers a ship draws with
# that slot (see textures.paint_channels); an interceptor is named apart because its slots sit
# on different layers, not because they mean anything different.
# Nearly every slot paints some BASE layer, so BASE says nothing about which slot this is. Only
# the telling layer names are here; a slot with none of them falls back to what that slot is
# usually for.
_LAYER_NAMES = {"MARKINGS": "Markings", "NUMBER": "Markings", "SIGNAGE": "Signage",
                "LETTERING": "Signage", "LOGO": "Signage", "SMALLSIGN": "Small signs",
                "TERTIARY": "Trim"}
_SLOT_NAMES = {"Primary": "Body", "Alternative1": "Markings", "Alternative2": "Signage",
               "Alternative3": "Small signs", "Alternative4": "Trim"}


@bp.route("/api/ship/channels")
def api_ship_channels():
    """The paint slots this ship really draws, named for what each one paints."""
    a = request.args
    ship, seed = a.get("ship"), a.get("seed")
    if not ship or not seed:
        raise ValueError("ship and seed are required")
    found = textures.paint_channels(int(seed, 16), ship)
    # On an interceptor Primary is the base coat under everything, as on any other ship, and
    # Alternative1 is the trim -- the overlay that reads it inks a few compact bands of the
    # texture sheet and nothing between them. Where there is no trim slot and no seed layer in
    # the way, Primary is simply the whole ship; where a seed layer covers it, `fixed` says so.
    hull_paints = textures.hull_takes_paint(int(seed, 16), ship)
    two_tone = ship == "sentinel" and any(c["alt"] == "Alternative1" for c in found)
    out = []
    for c in found:
        alt, layers = c["alt"], c["layers"]
        if ship == "sentinel" and alt == "Primary":
            # Primary is the base coat: the whole ship where nothing covers it, the body where
            # there is a separate trim, and the pincers alone where the seed draws the body.
            name = "Body" if two_tone else ("Whole ship" if hull_paints else "Pincers")
        elif two_tone and alt == "Alternative1":
            name = "Trim"
        else:
            named = [_LAYER_NAMES[x] for x in layers if x in _LAYER_NAMES]
            name = named[0] if named else _SLOT_NAMES.get(alt, alt)
        out.append({"alt": alt, "name": name, "layers": layers})
    seen = {}
    for c in out:  # two slots can paint the same kind of thing; number them rather than repeat
        seen[c["name"]] = seen.get(c["name"], 0) + 1
    count = {}
    for c in out:
        if seen[c["name"]] > 1:
            count[c["name"]] = count.get(c["name"], 0) + 1
            c["name"] = f'{c["name"]} {count[c["name"]]}'
    # Where the seed draws the body itself, say which colour it is stuck with: overlay 1 is
    # orange-brown and overlay 3 near black, and knowing which turns a warning into a reason.
    # The pincers still take the paint either way, so this is the body alone.
    body_colour = {"1": "orange", "3": "black"}.get(textures.overlay_of(seed) if ship == "sentinel" else "")
    fixed = [] if hull_paints else [{"name": "Body", "colour": body_colour or "its own colour"}]
    return jsonify({"ship": ship, "seed": seed, "channels": out, "fixed": fixed})


@bp.route("/api/ship/paint/clear", methods=["POST"])
def api_ship_paint_clear():
    b = body()
    opened = open_save(b.get("path"))
    ships.clear_ship_paint(opened.readable, int(b["slot"]))
    return jsonify({"ok": True, "backup": write(opened)})


@bp.route("/api/palettes")
def api_palettes():
    return jsonify(PALETTES)
