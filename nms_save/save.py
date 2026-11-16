"""High-level open/save for a single .hg file: decode + deobfuscate in,
obfuscate + encode out, with a mandatory timestamped backup on every write.

The backups are pruned as they are made -- see prune_backups().
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime

from . import codec, mapping

#  How many backups of one save file to keep. Every write leaves one behind and an evening of
#  editing leaves dozens, each the size of the save; left alone they quietly fill the save folder
#  with copies nobody will ever open. The newest are the ones worth having, so the oldest go.
#  The player can set their own number in the app (Save > Backups), which is remembered in
#  settings.json; 0 there means keep every one and never delete.
KEEP_BACKUPS = 20

#  What this tool's own backups are called: <save>.<YYYYmmdd-HHMMSS-micros>.bak, with a -N on the
#  end in the vanishingly rare case that two landed in the same microsecond. Nothing is ever
#  deleted unless its name matches this exactly -- a .bak somebody else put in the save folder,
#  or renamed to keep, is not ours to remove.
_BACKUP_NAME = re.compile(r"\d{8}-\d{6}-\d+(?:-\d+)?\.bak\Z")


def backup_path_for(path: str) -> str:
    """Where write() (or anyone else) should put a timestamped backup of `path`.

    Includes microseconds: two backups of the same file within the same
    wall-clock second must never collide on a filename -- a collision
    would silently overwrite one backup with another (or, in an undo
    flow, with the very state being undone).
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    base = os.path.basename(path)
    candidate = os.path.join(os.path.dirname(path), f"{base}.{stamp}.bak")
    # Belt-and-suspenders: if it *still* somehow exists, disambiguate further.
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(os.path.dirname(path), f"{base}.{stamp}-{n}.bak")
        n += 1
    return candidate


@dataclass
class OpenSave:
    path: str
    readable: dict  # deobfuscated JSON tree -- mutate this
    _chunked: bool
    _trailing_nul: int

    def backup_path(self) -> str:
        return backup_path_for(self.path)

    def write(self, *, backup: bool = True) -> str | None:
        """Write self.readable back to self.path.

        Returns the backup file path (or None if backup=False). Always
        backs up by default -- pass backup=False only if you already made
        one yourself.
        """
        backup_path = None
        if backup:
            backup_path = self.backup_path()
            shutil.copy2(self.path, backup_path)

        obfuscated = mapping.obfuscate(self.readable)
        text = json.dumps(obfuscated, separators=(",", ":"))
        raw = codec.encode(text, self._chunked, self._trailing_nul)

        with open(self.path, "wb") as f:
            f.write(raw)

        if backup:
            # Only once the new save is safely down. Until then the old backups are all there is.
            prune_backups(self.path)
        return backup_path


def backups_of(path: str) -> list:
    """Every backup this tool has made of `path`, oldest first.

    Ordered by the stamp in the name and not by modified time, because shutil.copy2 hands a
    backup the save's own mtime: two copies taken ten minutes apart can carry the same one.
    """
    folder = os.path.dirname(path) or "."
    head = os.path.basename(path) + "."
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    mine = sorted(n for n in names if n.startswith(head) and _BACKUP_NAME.fullmatch(n[len(head):]))
    return [os.path.join(folder, n) for n in mine]


def keep_count() -> int:
    """How many backups to keep: the player's own number, or KEEP_BACKUPS if they never set one."""
    try:
        from . import gamepath
        return max(0, int(gamepath.setting("keep_backups", KEEP_BACKUPS)))
    except Exception:    # unreadable settings are not a reason to start deleting more or less
        return KEEP_BACKUPS


def prune_backups(path: str, keep: int = None, protect=()) -> list:
    """Delete the oldest backups of `path`, leaving the newest `keep` in place.

    `keep` defaults to the player's setting. **0 keeps every one and deletes nothing** -- a save
    is always backed up before it is written, so "keep none" is not a thing to offer. Anything
    named in `protect` stays whatever its age: a restore passes the file it restored from, which
    should not disappear from under the player at the moment they reach for it.

    Returns the files that were removed. One that will not delete -- open in another program, or
    read-only -- is left where it is: tidying up is not worth failing a save over.
    """
    keep = keep_count() if keep is None else max(0, int(keep))
    if keep == 0:
        return []
    safe = {os.path.normcase(os.path.abspath(p)) for p in protect}
    gone = []
    for f in backups_of(path)[:-keep]:
        if os.path.normcase(os.path.abspath(f)) in safe:
            continue
        try:
            os.remove(f)
            gone.append(f)
        except OSError:
            pass
    return gone


def open_save(path: str) -> OpenSave:
    with open(path, "rb") as f:
        raw = f.read()

    text, chunked, trailing_nul = codec.decode(raw)
    data = json.loads(text)
    readable = mapping.deobfuscate(data)

    return OpenSave(
        path=path,
        readable=readable,
        _chunked=chunked,
        _trailing_nul=trailing_nul,
    )


def read_branch(path: str, *names: str):
    """One branch of a save, read without converting the rest of it.

    Renaming every key of a save costs a tenth of a second and there are 650,000 of them. A
    caller that wants one list -- checking a write landed, say -- can walk down to it by the
    obfuscated names and rename only what it finds there.

    Returns None if the branch is not in this save.
    """
    with open(path, "rb") as f:
        raw = f.read()
    text, _chunked, _nul = codec.decode(raw)
    node = json.loads(text)
    for name in names:
        if not isinstance(node, dict):
            return None
        key = mapping.key_for(name)
        if key in node:
            node = node[key]
        elif name in node:      # a name short enough never to have been obfuscated
            node = node[name]
        else:
            return None
    return mapping.deobfuscate(node)
