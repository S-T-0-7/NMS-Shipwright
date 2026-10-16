"""Where No Man's Sky is installed on this machine.

Works on Windows and on Linux (where the game runs through Steam Play / Proton -- the files are the
same Windows build either way). Looked for in this order: the NMS_DIR environment variable, the
folder the user picked in the app (kept in settings.json next to the cache), then Steam (including
extra library drives), and on Windows also GOG and the Microsoft Store. Nothing here is specific to
one machine or one copy of the game.
"""
from __future__ import annotations

import functools
import glob
import json
import os
import re

WINDOWS = os.name == "nt"
SETTINGS_DIR = os.environ.get("NMS_TOOL_CACHE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gamecache")
SETTINGS = os.path.join(SETTINGS_DIR, "settings.json")
DEFAULT_STEAM = r"C:\Program Files (x86)\Steam"
APP_ID = "275850"  # No Man's Sky on Steam


class GamePathError(RuntimeError):
    pass


def _child(folder: str, name: str) -> str:
    """A child path, matched case-insensitively -- a Linux install's folders may differ in case."""
    direct = os.path.join(folder, name)
    if os.path.exists(direct):
        return direct
    try:
        low = name.lower()
        for entry in os.listdir(folder):
            if entry.lower() == low:
                return os.path.join(folder, entry)
    except OSError:
        pass
    return direct


def looks_like_game(folder: str) -> bool:
    """True if `folder` is a No Man's Sky install (has the program and the archives)."""
    if not folder:
        return False
    nms = _child(_child(folder, "Binaries"), "NMS.exe")
    banks = _child(_child(folder, "GAMEDATA"), "PCBANKS")
    return os.path.exists(nms) and os.path.isdir(banks)


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
        raise GamePathError(f"{folder} is not a No Man's Sky folder: it has no Binaries/NMS.exe "
                            "and GAMEDATA/PCBANKS. Pick the folder the game itself is in.")
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


def _steam_roots() -> list:
    """Base Steam install folders to look in (one on Windows, the usual spots on Linux)."""
    if WINDOWS:
        import winreg
        steam = _reg(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath") \
            or _reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath") or DEFAULT_STEAM
        return [steam.replace("/", "\\")]
    home = os.path.expanduser("~")
    cands = [os.path.join(home, ".steam", "steam"), os.path.join(home, ".steam", "root"),
             os.path.join(home, ".local", "share", "Steam"),
             os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")]
    return [c for c in cands if os.path.isdir(c)]


def steam_libraries() -> list:
    """Every Steam library folder, including ones on other drives."""
    libs = []
    for steam in _steam_roots():
        libs.append(steam)
        for vdf in (os.path.join(steam, "steamapps", "libraryfolders.vdf"),
                    os.path.join(steam, "config", "libraryfolders.vdf")):
            try:  # the vdf lists the other library drives; a plain text scan is enough
                with open(vdf, encoding="utf-8", errors="replace") as f:
                    libs += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s*"([^"]+)"', f.read())]
            except OSError:
                pass
    seen, out = set(), []
    for lib in libs:
        if lib and lib not in seen:
            seen.add(lib)
            out.append(lib)
    return out


def _candidates():
    yield os.environ.get("NMS_DIR", "")
    yield saved_dir()
    for lib in steam_libraries():
        yield os.path.join(lib, "steamapps", "common", "No Man's Sky")
    if not WINDOWS:
        return
    import winreg
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
        where = "Binaries/NMS.exe" if not WINDOWS else "Binaries\\NMS.exe"
        raise GamePathError("No Man's Sky was not found on this PC. Open Save > Game data and "
                            f"choose the folder the game is installed in (the one with {where}).")
    return folder
