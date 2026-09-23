"""Find No Man's Sky save files on this machine (Windows)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from glob import glob

DEFAULT_ROOT = os.path.expandvars(r"%APPDATA%\HelloGames\NMS")


@dataclass
class SaveFile:
    path: str
    profile: str  # e.g. "st_76561199044409184"
    slot_name: str  # "save.hg", "save2.hg", ...
    mtime: float
    size: int

    @property
    def index(self) -> int:
        """0 for save.hg, 1 for save2.hg, ... (-1 if the name is unusual)."""
        num = self.slot_name[4:-3]
        return 0 if num == "" else int(num) - 1 if num.isdigit() else -1

    @property
    def slot(self) -> int:
        """In-game save slot (1-based): save.hg + save2.hg are slot 1, save3 + save4 slot 2, ..."""
        return self.index // 2 + 1 if self.index >= 0 else 0

    @property
    def kind(self) -> str:
        """Each slot keeps an autosave (odd file) and a manual save (even file)."""
        return "Autosave" if self.index % 2 == 0 else "Manual save"


def find_saves(root: str = DEFAULT_ROOT) -> list[SaveFile]:
    """List every save*.hg (not accountdata/manifest) file, newest first."""
    results = []
    for path in glob(os.path.join(root, "*", "save*.hg")):
        slot_name = os.path.basename(path)
        if slot_name.startswith("mf_"):
            continue  # manifest sidecar, not a save
        profile = os.path.basename(os.path.dirname(path))
        stat = os.stat(path)
        results.append(
            SaveFile(
                path=path,
                profile=profile,
                slot_name=slot_name,
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
        )

    results.sort(key=lambda s: s.mtime, reverse=True)
    return results
