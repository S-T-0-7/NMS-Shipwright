"""NMS Shipwright -- the local backend behind the desktop window (nms_editor.py).

Binds to 127.0.0.1 only. Every write goes through save.OpenSave.write(), which backs the file
up first, and is refused while No Man's Sky is running (the game would overwrite the change on
its next save).

    python nms_editor.py          # desktop window
    python webapp/app.py          # the same UI in a browser at http://127.0.0.1:5000

The routes live in webapp/routes/, one module per part of the UI.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from nms_save import ships  # noqa: E402
from webapp.common import GAME_DATA_ERRORS, GameRunning, UPDATE_HINT  # noqa: E402
from webapp.routes import designer, find, health, inventory, pages, player, ships as ship_routes  # noqa: E402

app = Flask(__name__, static_folder=None)
for module in (pages, health, ship_routes, designer, find, inventory, player):
    app.register_blueprint(module.bp)


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):  # 404s etc. keep their own status
        return e
    from nms_procgen.exeaddr import AddressError
    from nms_save.gamemeta import MetaError
    if isinstance(e, (MetaError, AddressError) + GAME_DATA_ERRORS):
        return jsonify({"ok": False, "error": str(e), "hint": UPDATE_HINT, "game_data": True}), 503
    code = 409 if isinstance(e, GameRunning) else 400 if isinstance(e, (ValueError, ships.ShipLookupError)) else 500
    return jsonify({"ok": False, "error": str(e)}), code


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
