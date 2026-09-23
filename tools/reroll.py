#!/usr/bin/env python
"""Manual reroll loop for a ship slot: drop in a fresh random seed (or a
specific one), then quit No Man's Sky to the main menu and reload your
save to see it. Repeat until you like the result.

No reverse engineering, no live game hook -- just the same safe
save-editing pipeline as `save_editor.py`, made convenient for repeated
tries: every roll is logged (data/reroll_log.csv) and backed up, and you
can jump back to any previous roll with --undo.

    python tools/reroll.py --slot 4                       # random seed, most-recently-modified save
    python tools/reroll.py --slot 4 --path "<save path>"  # explicit save file
    python tools/reroll.py --slot 4 --seed 0xDEADBEEF...  # a specific seed instead of random
    python tools/reroll.py --slot 4 --undo                # restore the most recent backup for this file
    python tools/reroll.py --slot 4 --log                 # show this slot's reroll history

Close No Man's Sky before each run -- if it's running it can overwrite
your change on its next autosave/exit. After running, (re)launch NMS and
either "Continue" (if you fully quit) or load your save from the menu.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nms_save import locator, save, ships  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LOG_PATH = os.path.join(BASE_DIR, "data", "reroll_log.csv")
LOG_FIELDS = ["timestamp", "save_path", "slot", "old_seed", "new_seed", "backup_path"]


def random_seed() -> str:
    return f"0x{random.getrandbits(64):016x}"


def resolve_path(args) -> str:
    if args.path:
        return args.path
    found = locator.find_saves()
    if not found:
        print(f"No save*.hg found under {locator.DEFAULT_ROOT}, and no --path given.")
        sys.exit(1)
    print(f"No --path given -- using most recently modified save: {found[0].path}")
    return found[0].path


def log_roll(save_path: str, slot: int, old_seed: str, new_seed: str, backup_path: str) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    file_exists = os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "save_path": save_path,
                "slot": slot,
                "old_seed": old_seed,
                "new_seed": new_seed,
                "backup_path": backup_path,
            }
        )


def cmd_log(args, save_path: str):
    if not os.path.exists(LOG_PATH):
        print("No rerolls logged yet.")
        return
    with open(LOG_PATH, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["save_path"] == save_path and int(r["slot"]) == args.slot]

    if not rows:
        print(f"No rerolls logged yet for slot {args.slot} of {save_path}")
        return

    print(f"Reroll history for slot {args.slot} of {save_path}:\n")
    for r in rows:
        print(f"  {r['timestamp']}  {r['old_seed']} -> {r['new_seed']}")
    print(f"\nLiked one? Add it to the catalog:\n  python tools/add_seed.py <seed> --type <type> --colour \"...\"")
    print(f"Want to go back to one? \n  python tools/save_editor.py set-seed \"{save_path}\" --slot {args.slot} --seed <seed> --apply")


def cmd_undo(args, save_path: str):
    backups = sorted(glob.glob(f"{save_path}.*.bak"))
    if not backups:
        print(f"No backups found next to {save_path}")
        return 1

    latest = backups[-1]
    print(f"Restoring: {latest}\n       -> {save_path}")

    import shutil

    # Read the backup into memory *before* touching anything on disk, so
    # there's no window where a path collision or interrupted copy could
    # lose data (see backup_path_for's docstring for why this mattered).
    with open(latest, "rb") as f:
        restore_bytes = f.read()

    # Safety net for the undo itself.
    safety_copy = save.backup_path_for(save_path)
    shutil.copy2(save_path, safety_copy)

    with open(save_path, "wb") as f:
        f.write(restore_bytes)

    print(f"Done. (Pre-undo state also saved to: {safety_copy})")
    return 0


def cmd_roll(args, save_path: str):
    opened = save.open_save(save_path)
    ship_list = ships.list_ships(opened.readable)
    current = next((s for s in ship_list if s.index == args.slot), None)

    if current is None:
        print(f"No populated ship at slot {args.slot}. Available slots:")
        for s in ship_list:
            print(" ", s.describe())
        return 1

    new_seed = args.seed or random_seed()
    old_seed = current.seed

    print("Current:")
    print(" ", current.describe())

    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        updated = ships.set_ship_seed(opened.readable, args.slot, new_seed)
        for w in caught:
            print(f"\n  WARNING: {w.message}\n")

    print("New:")
    print(" ", updated.describe())

    backup_path = opened.write()
    log_roll(save_path, args.slot, old_seed, new_seed, backup_path)

    print(f"\nBackup saved to: {backup_path}")
    print(f"Written: {save_path}")
    print("Now quit No Man's Sky fully (if running), relaunch, and load this save to see it.")
    print(f"\nDidn't like it? Reroll again: python tools/reroll.py --slot {args.slot} --path \"{save_path}\"")
    print(f"Want the previous look back? python tools/reroll.py --slot {args.slot} --path \"{save_path}\" --undo")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slot", type=int, required=True, help="Ship slot index (see save_editor.py list)")
    parser.add_argument("--path", help="Save file path (default: most recently modified save found)")
    parser.add_argument("--seed", help="Use this exact seed instead of a random one")
    parser.add_argument("--undo", action="store_true", help="Restore the most recent backup for this save file")
    parser.add_argument("--log", action="store_true", help="Show reroll history for this slot")
    args = parser.parse_args()

    save_path = resolve_path(args)

    if args.log:
        return cmd_log(args, save_path)
    if args.undo:
        return cmd_undo(args, save_path)
    return cmd_roll(args, save_path)


if __name__ == "__main__":
    sys.exit(main())
