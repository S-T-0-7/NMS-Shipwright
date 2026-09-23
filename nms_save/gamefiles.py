"""Copies of game files (from the PCBANKS archives) and a small MBIN reader."""
from __future__ import annotations

import glob
import hashlib
import json
import threading
import os
import struct

from . import gamepath


def banks() -> str:
    """The game's PCBANKS folder on this PC."""
    return os.path.join(gamepath.require(), "GAMEDATA", "PCBANKS")


def __getattr__(name):  # BANKS stays as a name, but is looked up when used
    if name == "BANKS":
        return banks()
    raise AttributeError(name)


CACHE = os.environ.get("NMS_TOOL_CACHE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gamecache")


class GameFileError(RuntimeError):
    pass


STAMP_VERSION = 2  # 2: partial extractions are no longer recorded as complete
_VERIFIED: dict = {}  # (folder, patterns) -> stamp already checked in this process
_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(dest):
    """One lock per destination folder: two requests must not extract into it at once."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(os.path.abspath(dest), threading.Lock())


def extract(dest, patterns, first_pak, keep_dirs=False):
    """Copy files matching `patterns` out of the game archives into `dest`, once per game build.

    Each pattern set keeps its own stamp and list of files, so several callers can share a folder
    and a game update re-extracts only what that caller asked for.
    """
    patterns = list(patterns)
    stamp_file = os.path.join(dest, "_stamp_%s.json" % hashlib.sha1("|".join(patterns).encode()).hexdigest()[:12])
    pcbanks = banks()
    preferred = os.path.join(pcbanks, first_pak)
    paks = sorted(glob.glob(os.path.join(pcbanks, "*.pak")))
    if not paks:
        raise GameFileError(f"No Man's Sky archives not found in {pcbanks}. "
                            "Open Save > Game data to choose the game folder.")
    # STAMP_VERSION rises when a bug made older copies untrustworthy, so they are re-extracted.
    stamp = [len(paks), max(int(os.path.getmtime(p)) for p in paks), patterns, STAMP_VERSION]
    key = (os.path.abspath(dest), stamp_file)
    if _VERIFIED.get(key) == stamp:  # already checked once in this process
        return dest
    try:
        with open(stamp_file) as f:
            old = json.load(f)
        # The stamp is written only after every file is in place (each one renamed into position),
        # so one spot check is enough to catch a cache someone deleted files from.
        if old.get("stamp") == stamp and (not old.get("files") or os.path.exists(os.path.join(dest, old["files"][-1]))):
            _VERIFIED[key] = stamp
            return dest
        for f_ in old.get("files", []):  # this caller's old copies only
            try:
                os.remove(os.path.join(dest, f_))
            except OSError:
                pass
    except (OSError, ValueError, AttributeError):
        pass
    with _lock_for(dest):
        return _extract_locked(dest, patterns, preferred, paks, stamp, stamp_file, keep_dirs)


def _extract_locked(dest, patterns, preferred, paks, stamp, stamp_file, keep_dirs):  # noqa: C901
    from hgpaktool import HGPAKFile
    os.makedirs(dest, exist_ok=True)
    try:  # another thread may have finished the same extraction while we waited
        with open(stamp_file) as f:
            old = json.load(f)
        if old.get("stamp") == stamp and (not old.get("files") or os.path.exists(os.path.join(dest, old["files"][-1]))):
            _VERIFIED[(os.path.abspath(dest), stamp_file)] = stamp
            return dest
    except (OSError, ValueError, AttributeError):
        pass
    # A game update can move a file to another archive, so keep looking until every
    # pattern has produced something (the named archive is only a shortcut).
    todo, files, broke = list(patterns), [], []
    for pak in ([preferred] if os.path.exists(preferred) else []) + [p for p in paks if p != preferred]:
        if not todo:
            break
        got = set()
        try:
            with HGPAKFile(pak) as f:
                for name, blob in f.extract(filters=todo):
                    rel = os.path.join(*(name.split("/") if keep_dirs else [os.path.basename(name)]))
                    out = os.path.join(dest, rel)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    tmp = f"{out}.part"  # write then rename: a reader never sees half a file
                    with open(tmp, "wb") as fh:
                        fh.write(blob)
                    os.replace(tmp, out)
                    files.append(rel)
                    got.update(p for p in todo if _matches(p, name))
        except FileNotFoundError:
            continue  # an exact path this archive does not hold
        except Exception as e:
            # Reading stopped part way -- usually the game being updated underneath us. Keep what
            # the other archives give, but remember, so this half-done copy is not stamped as good.
            broke.append(f"{os.path.basename(pak)}: {type(e).__name__}")
            continue
        # A wildcard can match files spread over several archives (the sentinel ship's parts live
        # apart from the rest), so only an exact name is finished once it is found.
        todo = [p for p in todo if p not in got or "*" in p or "?" in p]
    if not files:
        raise GameFileError(f"{', '.join(patterns)} not found in the game archives. "
                            "If No Man's Sky was just updated, use 'Re-read game files'.")
    if broke:
        raise GameFileError("the game archives could not be read to the end (" + "; ".join(broke[:3]) + "). "
                            "If No Man's Sky is updating or running, wait for it to finish and try again.")
    tmp = stamp_file + ".part"
    with open(tmp, "w") as f:
        json.dump({"stamp": stamp, "files": files, "missing": todo}, f)
    os.replace(tmp, stamp_file)  # the stamp appears only once every file is in place
    _VERIFIED[(os.path.abspath(dest), stamp_file)] = stamp
    return dest


def _matches(pattern, name):
    import fnmatch
    return fnmatch.fnmatch(name.lower(), pattern.lower())


def read(path):
    with open(path, "rb") as f:
        return f.read()


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def cstr(b, o, n):
    return b[o:o + n].split(b"\0", 1)[0].decode("ascii", "replace")


def array(b, o):
    """MBIN list/string header at o -> (absolute data offset, count)."""
    off, n = struct.unpack_from("<qi", b, o)
    return o + off, n


def vstr(b, o, encoding="ascii"):
    start, n = array(b, o)
    return b[start:start + n].split(b"\0", 1)[0].decode(encoding, "replace") if n else ""
