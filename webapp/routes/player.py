"""Currencies, quests, backups and whole-save export/import."""
from __future__ import annotations

import glob
import os
import re
import shutil

from flask import Blueprint, jsonify, request

from nms_save import player, quests, save

from webapp.common import GameRunning, body, game_running, open_save, write

bp = Blueprint("player", __name__)


@bp.route("/api/player", methods=["GET", "POST"])
def api_player():
    if request.method == "GET":
        return jsonify(player.get_currencies(open_save(request.args.get("path")).readable))
    b = body()
    opened = open_save(b.get("path"))
    values = player.set_currencies(opened.readable, **{k: b[k] for k in player.CURRENCIES if k in b})
    return jsonify({"ok": True, "values": values, "backup": write(opened)})


@bp.route("/api/quests")
def api_quests():
    return jsonify(quests.list_quests(open_save(request.args.get("path")).readable))


@bp.route("/api/quests/skip", methods=["POST"])
def api_quests_skip():
    b = body()
    opened = open_save(b.get("path"))
    changed = quests.skip_quests(opened.readable, list(b.get("keys", [])))
    if not changed:
        return jsonify({"ok": True, "changed": [], "backup": None})
    return jsonify({"ok": True, "changed": changed, "backup": write(opened)})


BACKUP_TIME = re.compile(r"\.(\d{8})-(\d{6})-\d+\.bak$")


@bp.route("/api/backups")
def api_backups():
    path = request.args.get("path")
    open_save(path)  # validates the path
    out = []
    for f in glob.glob(f"{path}.*.bak"):
        m = BACKUP_TIME.search(f)
        day, clock = (m.group(1), m.group(2)) if m else ("", "")
        made = f"{day[:4]}-{day[4:6]}-{day[6:]} {clock[:2]}:{clock[2:4]}:{clock[4:]}" if m else ""
        out.append({"file": f, "made": made, "size": os.path.getsize(f)})
    return jsonify(sorted(out, key=lambda x: x["made"], reverse=True))


@bp.route("/api/backups/restore", methods=["POST"])
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
