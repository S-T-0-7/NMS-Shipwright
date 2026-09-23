"""Which build of No Man's Sky the copied game data came from.

Everything the tool reads out of the game (code addresses, item tables, meshes, scan results)
is cached. A game update makes some of that stale, so each cache is tied to the build it came
from: extracted files carry the archive's size and date, and the caches derived from them are
thrown away when the game's exe changes. Call check() before using cached game data.
"""
from __future__ import annotations

import functools
import json
import os
import shutil

from .gamemeta import exe_path
from . import gamefiles
from .gamefiles import CACHE, banks

BUILD_FILE = os.path.join(CACHE, "build.json")
DERIVED = ("models", "scan")  # rebuilt from game files, with no stamp of their own


class GameDataError(RuntimeError):
    """The game files could not be read the way this version of the tool expects."""


def build_id() -> dict:
    """Identity of the installed game: the exe's size and date, plus the archive folder's."""
    exe = exe_path()
    try:
        st = os.stat(exe)
    except OSError as e:
        raise GameDataError("No Man's Sky was not found on this PC. Open Save > Game data and choose "
                           "the folder the game is installed in.") from e
    paks = 0
    try:
        paks = sum(1 for f in os.scandir(banks()) if f.name.lower().endswith(".pak"))
    except OSError:
        pass
    return {"exe": [st.st_size, int(st.st_mtime)], "paks": paks}


def stored_id():
    try:
        with open(BUILD_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@functools.lru_cache(maxsize=1)
def check() -> dict:
    """Note the installed build and drop caches left over from an older one.

    Returns {"build", "changed", "first_run"}. Cached per process: call refresh() to force it.
    """
    now, old = build_id(), stored_id()
    changed = old is not None and old != now
    if changed:
        for name in DERIVED:
            shutil.rmtree(os.path.join(CACHE, name), ignore_errors=True)
    if old != now:
        os.makedirs(CACHE, exist_ok=True)
        tmp = BUILD_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(now, f)
        os.replace(tmp, BUILD_FILE)
    return {"build": now, "changed": changed, "first_run": old is None}


def refresh(everything: bool = False) -> dict:
    """Re-check the build; with everything=True also drop the extracted copies of game files,
    so the next use reads them from the game again (slower, but fixes a half-updated cache)."""
    check.cache_clear()
    if everything:
        for name in os.listdir(CACHE) if os.path.isdir(CACHE) else []:
            path = os.path.join(CACHE, name)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif name != "build.json":
                os.remove(path)
        gamefiles._VERIFIED.clear()
        _clear_memory()
    return check()


def _clear_memory():
    """Forget anything this process parsed from the old game files."""
    from . import gamemeta, items, quests
    for mod, names in ((gamemeta, ("exe_meta",)), (items, ("catalogue",)),
                       (quests, ("strings", "missions", "_layouts"))):
        for n in names:
            fn = getattr(mod, n, None)
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()
    try:
        from . import extras
        for n in ("word_groups", "recipes", "shop_specials"):
            getattr(extras, n).cache_clear()
    except Exception:  # extras is optional for the core save features
        pass
    try:
        from nms_procgen import model3d, textures
        for mod in (model3d, textures):
            for n in dir(mod):
                fn = getattr(mod, n)
                if hasattr(fn, "cache_clear"):
                    fn.cache_clear()
    except Exception:
        pass
