"""The player's corvette: the modules bolted to it and a 3D view of the result."""
from __future__ import annotations

import functools

from flask import Blueprint, Response, jsonify, request

from nms_procgen import corvette_parts, model3d
from nms_save import corvette, items

from webapp.common import STATIC, body, game_running, GameRunning, open_save

bp = Blueprint("corvette", __name__)


def _layouts(path):
    return corvette.layouts(open_save(path).readable)


def _turned(obj):
    """Whether a module sits at an angle no build-menu rotation would reach.

    Only the angle is judged. Whether a position is on the grid cannot be told from the save
    alone: a module is stored by its centre, so a part two cells long sits on a half step and
    looks off-grid while being perfectly ordinary.
    """
    return not all(abs(c - round(c)) < 0.01 for c in list(obj["Up"]) + list(obj["At"]))


def _placed(entry):
    """(scene, position, up, at, turn) per scene to draw, which is what corvette_model wants."""
    return [(scene, o["Position"], o["Up"], o["At"], turn) for o in corvette.modules(entry)
            for scene, turn in corvette_parts.draw_for(o["ObjectID"])]


@bp.route("/api/corvettes")
def api_corvettes():
    """Every corvette in the save, each with its modules in the order the save holds them."""
    cat, named = corvette_parts.catalogue(), items.catalogue()
    out = []
    for i, entry in enumerate(_layouts(request.args.get("path"))):
        mods = []
        for n, o in enumerate(corvette.modules(entry)):
            part = o["ObjectID"].lstrip("^")
            row = cat.get(part) or {}
            hull = o["ObjectID"] == corvette.HULL
            label = (named.get(part) or {}).get("name") or ("Hull" if hull else part)
            mods.append({"n": n, "id": part, "name": label, "hull": hull,
                         "ts": o.get("Timestamp"),
                         # full precision: the builder writes these back, and rounding here
                         # would nudge every module the user never touched
                         "position": list(o["Position"]), "up": list(o["Up"]), "at": list(o["At"]),
                         "scenes": [s.rsplit("/", 1)[-1].replace(".SCENE.MBIN", "")
                                    for s in corvette_parts.scenes_for(part)],
                         "turned": _turned(o),
                         "rotatable": bool(row.get("rotatable")), "in_menu": bool(row.get("in_menu"))})
        out.append({"index": i, "name": entry.get("Name") or "", "modules": mods})
    return jsonify(out)


@bp.route("/api/corvette/model")
def api_corvette_model():
    """3D model (model3d.pack binary) of one corvette as the save has it placed."""
    entries = _layouts(request.args.get("path"))
    index = int(request.args.get("index") or 0)
    if not 0 <= index < len(entries):
        raise ValueError("this save has no corvette %d" % index)
    data = model3d.pack(model3d.corvette_model(_placed(entries[index])))
    return Response(data, mimetype="application/octet-stream", headers={"Cache-Control": "no-store"})


# What to call each family in the palette. The lettered series (structural pieces, decorations,
# wings) run to dozens of families between them and belong under one heading each.
FAMILY_LABELS = {"ALK": "Airlocks", "COK": "Cockpits", "CON": "Connectors", "CON_L": "Connectors, angled",
                 "CON2": "Connectors, long", "GEN": "Generators", "HAB": "Habs", "HAB1": "Habs, small",
                 "HOP": "Hoppers", "LND": "Landing gear", "MAG": "Mag blocks", "SHL": "Shield generators",
                 "TRU": "Thrusters", "TUR": "Turrets"}
FAMILY_PREFIX = (("STR", "Structural"), ("DECO", "Decoration"), ("WNG", "Wings"))


def _group(family):
    if family in FAMILY_LABELS:
        return FAMILY_LABELS[family]
    for prefix, label in FAMILY_PREFIX:
        if family.startswith(prefix):
            return label
    return "Other"


@bp.route("/api/corvette/palette")
def api_corvette_palette():
    """The modules a build can use, under one heading per kind, as the build menu groups them."""
    named = items.catalogue()
    groups = {}
    for part, row in corvette_parts.catalogue().items():
        if not row["in_menu"] or not corvette_parts.drawable(part):
            continue
        label = (named.get(part) or {}).get("name") or part
        groups.setdefault(_group(corvette_parts._split(part)[0] or part), []).append(
            {"id": part, "name": label, "rotatable": row["rotatable"]})
    order = list(FAMILY_LABELS.values()) + [l for _, l in FAMILY_PREFIX] + ["Other"]
    return jsonify([{"label": g, "parts": sorted(groups[g], key=lambda p: (p["name"], p["id"]))}
                    for g in order if g in groups])


@functools.lru_cache(maxsize=64)
def _part_model(part):
    """One module drawn at the origin, for the builder to place copies of."""
    drawn = corvette_parts.draw_for(part)
    if not drawn:
        raise ValueError("nothing draws %s" % part)
    return model3d.pack(model3d.corvette_model(
        [(s, (0, 0, 0), (0, 1, 0), (0, 0, 1), turn) for s, turn in drawn]))


@bp.route("/api/corvette/mirror")
def api_corvette_mirror():
    """{module id: the module that is its mirror image}, for the builder's Mirror."""
    return jsonify(corvette_parts.handed())


@bp.route("/api/corvette/part")
def api_corvette_part():
    """3D model of a single module, in its own space, so the builder can move it about freely."""
    data = _part_model(request.args.get("id", "").lstrip("^"))
    # Revalidate rather than hold it: what a part looks like changes when the game updates or
    # when the mesh converter does, and a day-old copy in the browser would hide both.
    return Response(data, mimetype="application/octet-stream",
                    headers={"Cache-Control": "no-cache"})


@bp.route("/api/corvette/snaps")
def api_corvette_snaps():
    """The sockets each of the named modules offers, for the builder to snap parts together by."""
    ids = [i for i in (request.args.get("ids") or "").split(",") if i]
    return jsonify({i: [{"kind": k, "io": io, "m": mat} for k, io, mat in corvette_parts.snaps_for(i)]
                    for i in ids})


@bp.route("/api/corvette/save", methods=["POST"])
def api_corvette_save():
    """Write a built layout back, into both halves of the slot."""
    b = body()
    if game_running(fresh=True):   # about to write: do not trust a cached answer
        raise GameRunning("No Man's Sky is running -- quit the game first, or it will overwrite this build.")
    index, path = int(b.get("index") or 0), b.get("path")
    wanted = [(m["id"], m["position"], m.get("up") or (0, 1, 0), m.get("at") or (0, 0, 1),
               m.get("ts"))
              for m in b.get("modules") or []]
    known = corvette_parts.catalogue()
    for part, *_ in wanted:
        if part.lstrip("^") not in known:
            raise ValueError("no such module %r" % part)

    def rewrite(readable):
        entries = corvette.layouts(readable)
        if not 0 <= index < len(entries):
            raise ValueError("this save has no corvette %d" % index)
        corvette.replace(entries[index], wanted)

    written = corvette.write_both(path, rewrite)
    return jsonify({"written": written, "modules": len(wanted)})
