"""Where No Man's Sky is installed on this PC.

Looked for in this order: the NMS_DIR environment variable, the folder the user picked in the
app (kept in settings.json next to the cache), then Steam (including extra library drives),
GOG and the Microsoft Store. Nothing here is specific to one machine or one copy of the game.
"""
from __future__ import annotations

import functools
import glob
import json
import os
import re

SETTINGS_DIR = os.environ.get("NMS_TOOL_CACHE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gamecache")
SETTINGS = os.path.join(SETTINGS_DIR, "settings.json")
DEFAULT_STEAM = r"C:\Program Files (x86)\Steam"
APP_ID = "275850"  # No Man's Sky on Steam


class GamePathError(RuntimeError):
    pass


def looks_like_game(folder: str) -> bool:
    """True if `folder` is a No Man's Sky install (has the program and the archives)."""
    return bool(folder) and os.path.exists(os.path.join(folder, "Binaries", "NMS.exe")) \
        and os.path.isdir(os.path.join(folder, "GAMEDATA", "PCBANKS"))


def _settings() -> dict:
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def saved_dir() -> str:
    return _settings().get("nms_dir", "")


def save_dir(folder: str) -> str:
    """Remember the folder the user picked. Raises if it is not a game install."""
    folder = os.path.abspath(os.path.expandvars(os.path.expanduser(folder or "")))
    if not looks_like_game(folder):
        raise GamePathError(f"{folder} is not a No Man's Sky folder: it has no Binaries\\NMS.exe "
                            "and GAMEDATA\\PCBANKS. Pick the folder the game itself is in.")
    data = _settings()
    data["nms_dir"] = folder
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    tmp = SETTINGS + ".part"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, SETTINGS)
    find.cache_clear()
    return folder


def _reg(root, key, value):
    try:
        import winreg
        with winreg.OpenKey(root, key) as k:
            return winreg.QueryValueEx(k, value)[0]
    except OSError:
        return None


def _steam_libraries() -> list:
    """Every Steam library folder, including ones on other drives."""
    import winreg
    steam = _reg(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath") \
        or _reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath") or DEFAULT_STEAM
    steam = steam.replace("/", "\\")
    libraries = [steam]
    try:  # libraryfolders.vdf lists the other drives; a plain text scan is enough
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
            libraries += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s*"([^"]+)"', f.read())]
    except OSError:
        pass
    return libraries


def _candidates():
    import winreg
    yield os.environ.get("NMS_DIR", "")
    yield saved_dir()
    for lib in _steam_libraries():
        yield os.path.join(lib, "steamapps", "common", "No Man's Sky")
    # GOG keeps one registry key per game
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games")):
        try:
            with winreg.OpenKey(root, key) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    sub = winreg.EnumKey(k, i)
                    name = _reg(root, f"{key}\\{sub}", "gameName") or ""
                    if "no man" in name.lower():
                        yield _reg(root, f"{key}\\{sub}", "path") or ""
        except OSError:
            pass
    yield _reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Hello Games\No Man's Sky", "InstallDir")
    # Microsoft Store / Game Pass, and the usual manual spots
    for pattern in (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "WindowsApps",
                                 "HelloGames.NoMansSky_*", "*"),
                    r"C:\XboxGames\No Man's Sky\Content", r"C:\Games\No Man's Sky", r"D:\Games\No Man's Sky"):
        for hit in glob.glob(pattern):
            yield hit


@functools.lru_cache(maxsize=1)
def find() -> str:
    """The game folder, or "" if this PC does not seem to have it."""
    for folder in _candidates():
        if looks_like_game(folder):
            return os.path.abspath(folder)
    return ""


def require() -> str:
    folder = find()
    if not folder:
        raise GamePathError("No Man's Sky was not found on this PC. Open Save > Game data and "
                            "choose the folder the game is installed in (the one with Binaries\\NMS.exe).")
    return folder
