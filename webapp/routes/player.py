"""Currencies, quests, backups and whole-save export/import."""
from __future__ import annotations

import glob
import os
import re
import shutil

from flask import Blueprint, jsonify, request

from nms_save import gamepath, player, quests, save

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


def _listing(path):
    out = []
    for f in save.backups_of(path):
        m = BACKUP_TIME.search(f)
        day, clock = (m.group(1), m.group(2)) if m else ("", "")
        made = f"{day[:4]}-{day[4:6]}-{day[6:]} {clock[:2]}:{clock[2:4]}:{clock[4:]}" if m else ""
        try:
            size = os.path.getsize(f)
        except OSError:            # deleted from under us between the listing and the stat
            continue
        out.append({"file": f, "made": made, "size": size})
    out.reverse()                  # backups_of is oldest first; the page wants newest first
    return out


@bp.route("/api/backups")
def api_backups():
    path = request.args.get("path")
    open_save(path)  # validates the path
    return jsonify({"keep": save.keep_count(), "backups": _listing(path)})


@bp.route("/api/backups/keep", methods=["POST"])
def api_backups_keep():
    """Set how many backups to keep and clear out the rest straight away.

    The number is remembered for every save, not just this one; 0 means keep them all. Pruning
    only ever removes this tool's own <save>.<stamp>.bak copies, newest kept.
    """
    b = body()
    path = b.get("path")
    open_save(path)
    keep = b.get("keep")
    if keep is not None:
        try:
            keep = max(0, int(keep))
        except (TypeError, ValueError):
            raise ValueError("How many backups to keep has to be a whole number.")
        gamepath.remember("keep_backups", keep)
    removed = save.prune_backups(path)
    return jsonify({"ok": True, "keep": save.keep_count(), "removed": len(removed),
                    "backups": _listing(path)})


@bp.route("/api/backups/restore", methods=["POST"])
def api_backups_restore():
    b = body()
    path, src = b.get("path"), b.get("file")
    open_save(path)
    if not src or not os.path.exists(src) or not src.startswith(path + "."):
        raise ValueError("Unknown backup file")
    if game_running(fresh=True):   # about to write: do not trust a cached answer
        raise GameRunning("No Man's Sky is running -- quit the game first.")
    safety = save.backup_path_for(path)
    shutil.copy2(path, safety)
    with open(src, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data)
    # The safety copy is a backup like any other, so it counts against the limit -- but only
    # once the restore is down, and never the file it was restored from.
    save.prune_backups(path, protect=[src])
    return jsonify({"ok": True, "safety_copy": safety})
