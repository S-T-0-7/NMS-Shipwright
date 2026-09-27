"""Inventories, items and the unlock lists."""
from __future__ import annotations

import json
import os

from flask import Blueprint, Response, jsonify, request

from nms_save import extras, items

from webapp.common import body, open_save, write

bp = Blueprint("inventory", __name__)


@bp.route("/api/inventories")
def api_inventories():
    return jsonify(items.list_inventories(open_save(request.args.get("path")).readable))


@bp.route("/api/inventory", methods=["GET", "POST"])
def api_inventory():
    if request.method == "GET":
        return jsonify(items.get_inventory(open_save(request.args.get("path")).readable, request.args["inv"]))
    b = body()
    opened = open_save(b.get("path"))
    kw = {k: b[k] for k in ("x", "y", "id", "amount", "count") if b.get(k) is not None}
    inv = items.edit_inventory(opened.readable, b["inv"], b["op"], **kw)
    return jsonify({**inv, "backup": write(opened)})


@bp.route("/api/items")
def api_items():
    return jsonify(items.search_items(request.args.get("q", ""), request.args.get("type", "")))


@bp.route("/api/extras", methods=["GET", "POST"])
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


@bp.route("/api/rewards", methods=["GET", "POST"])
def api_rewards():
    if request.method == "GET":
        a = request.args
        return jsonify(extras.rewards(open_save(a.get("path")).readable, a.get("group", ""), a.get("q", "")))
    b = body()
    opened = open_save(b.get("path"))
    r = extras.set_rewards(opened.readable, b["group"], b.get("ids"), b.get("unlock"), b.get("redeemed"))
    return jsonify({"ok": True, **r, "backup": write(opened)})


@bp.route("/api/raw", methods=["GET", "POST"])
def api_raw():
    if request.method == "GET":
        return jsonify(extras.browse(open_save(request.args.get("path")).readable, request.args.get("at", "")))
    b = body()
    opened = open_save(b.get("path"))
    extras.set_path(opened.readable, b["at"], b["value"])
    return jsonify({"ok": True, "backup": write(opened)})


@bp.route("/api/save/export")
def api_save_export():
    opened = open_save(request.args.get("path"))
    name = os.path.basename(opened.path).replace(".hg", ".json")
    return Response(json.dumps(opened.readable, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.route("/api/save/import", methods=["POST"])
def api_save_import():
    b = body()
    opened = open_save(b.get("path"))
    data = json.loads(b["json"]) if isinstance(b.get("json"), str) else b.get("json")
    if not isinstance(data, dict) or "BaseContext" not in data:
        raise ValueError("that file is not an exported save (no BaseContext)")
    opened.readable = data
    return jsonify({"ok": True, "backup": write(opened)})
