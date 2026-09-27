"""Health checks and pointing the tool at the installed game."""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from nms_procgen import model3d, textures
from nms_save import extras, gamepath, gameversion, items, locator, quests

from webapp.common import body, open_save

bp = Blueprint("health", __name__)


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
        def one_system():
            return "%d ships in one system" % len(system_gen().system(0xBE0008220992)["ships"])

        def colours():
            return textures.ship_look("0x8BA812880CFAAA1C", "fighter")["colours"]["primary"]["index"] and "ok"

        def triangles():
            groups = model3d.ship_model("0x1", "fighter")["groups"].values()
            return "%d triangles" % (sum(len(g[1]) for g in groups) // 3)

        checks += [_check("Ship generator", "Find in game, system lookup", one_system),
                   _check("Ship colours", "colours and finish", colours),
                   _check("3D models", "ship viewer", triangles)]
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


@bp.route("/api/health")
def api_health():
    return jsonify(health(request.args.get("deep") == "1"))


@bp.route("/api/gamedir", methods=["POST"])
def api_gamedir():
    """Point the tool at the player's No Man's Sky folder (when it was not found on its own)."""
    folder = gamepath.save_dir(body().get("path", ""))
    gameversion.refresh(everything=True)  # anything read from the old guess is wrong
    SYSGEN["sg"] = None
    return jsonify({"ok": True, "nms_dir": folder, "health": health(False)})


@bp.route("/api/health/refresh", methods=["POST"])
def api_health_refresh():
    """Throw away the copies of game files and read them again (after a game update)."""
    gameversion.refresh(everything=bool(body().get("everything", True)))
    SYSGEN["sg"] = None  # the emulator holds the old game code
    return jsonify(health(False))


@bp.route("/favicon.ico")
def favicon():
    return Response(status=204)
