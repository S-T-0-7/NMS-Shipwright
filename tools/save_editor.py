#!/usr/bin/env python
"""CLI for inspecting and reseeding ships in an NMS save file.

    python tools/save_editor.py locate
    python tools/save_editor.py list "<path to save.hg>"
    python tools/save_editor.py set-seed "<path>" --slot 1 --seed 0xDEADBEEF12345678
    python tools/save_editor.py set-seed "<path>" --slot 1 --seed 0x... --apply

Safety:
  - set-seed defaults to a DRY RUN: it shows you the before/after and does
    NOT touch the file unless you pass --apply.
  - Every --apply write makes a timestamped .bak copy of the original file
    first, next to it.
  - Close No Man's Sky before editing its save -- if the game is running
    it can overwrite your change on its next autosave/exit.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nms_save import locator, mapping, save, ships  # noqa: E402


def cmd_check(args):
    opened = save.open_save(args.path)
    unmapped = mapping.unmapped_keys(opened.readable)

    if not unmapped:
        print(f"OK -- data/mapping.json fully covers this save's keys ({args.path}).")
        return 0

    print(f"{len(unmapped)} unrecognized short key(s) found in {args.path}:")
    for k in sorted(unmapped):
        print(f"  {k!r}")
    print(
        "\nEither data/mapping.json is stale for this save's game version "
        "(re-download the latest from monkeyman192/MBINCompiler's GitHub "
        "releases and replace data/mapping.json), or these are new "
        "legitimate short field names -- add them to "
        "KNOWN_UNOBFUSCATED_SHORT_KEYS in nms_save/mapping.py once confirmed."
    )
    return 1


def cmd_locate(args):
    found = locator.find_saves()
    if not found:
        print(f"No save*.hg files found under {locator.DEFAULT_ROOT}")
        return

    print(f"Found {len(found)} save file(s) under {locator.DEFAULT_ROOT}:\n")
    for s in found:
        print(f"  {s.path}")
        modified = datetime.fromtimestamp(s.mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"      profile={s.profile}  size={s.size:,}B  modified={modified}")
    print(f"\nMost recently modified: {found[0].path}")


def cmd_list(args):
    opened = save.open_save(args.path)
    ship_list = ships.list_ships(opened.readable)

    if not ship_list:
        print("No ships found -- is this the right save file / path format still matching?")
        return

    print(f"{len(ship_list)} ship slot(s) in {args.path}:\n")
    for s in ship_list:
        print(" ", s.describe())
        if args.verbose:
            print(f"      filename: {s.filename}")


def cmd_set_seed(args):
    opened = save.open_save(args.path)
    ship_list = ships.list_ships(opened.readable)
    current = next((s for s in ship_list if s.index == args.slot), None)

    if current is None:
        print(f"No populated ship at slot {args.slot}. Available slots:")
        for s in ship_list:
            print(" ", s.describe())
        return 1

    print("Current:")
    print(" ", current.describe())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        updated = ships.set_ship_seed(opened.readable, args.slot, args.seed)
        for w in caught:
            print(f"\n  WARNING: {w.message}\n")

    print("Proposed:")
    print(" ", updated.describe())

    if not args.apply:
        print("\nDry run only -- no file was changed. Re-run with --apply to write it.")
        return 0

    backup_path = opened.write()
    print(f"\nBackup saved to: {backup_path}")
    print(f"Written: {args.path}")
    print("Restart No Man's Sky (fully quit first if it was running) to see the change.")
    return 0


def cmd_paint(args):
    import json

    opened = save.open_save(args.path)
    current = next((s for s in ships.list_ships(opened.readable) if s.index == args.slot), None)
    if current is None:
        print(f"No populated ship at slot {args.slot}.")
        return 1
    print("Ship:", current.describe())
    resource = current.raw["Resource"]
    before = json.dumps(resource.get("ProceduralTexture"))
    if args.clear:
        ships.clear_ship_paint(opened.readable, args.slot)
    else:
        colour = tuple(float(x) for x in args.colour.split(","))
        ships.set_sentinel_paint(opened.readable, args.slot, colour, args.overlay, args.fixed,
                                 customisation=args.method == "both", palette_id=args.palette)
        if args.method == "override":
            ships.clear_ship_paint(opened.readable, args.slot, texture=False)
        print(f"Scheme: overlay {args.overlay} ({ships.SENTINEL_OVERLAYS[args.overlay]}), colour {colour}")
    print("Before:", before)
    print("After: ", json.dumps(resource["ProceduralTexture"]))
    if not args.apply:
        print("\nDry run only -- no file was changed. Re-run with --apply to write it.")
        return 0
    backup_path = opened.write()
    print(f"\nBackup saved to: {backup_path}")
    print(f"Written: {args.path}")
    print("Start No Man's Sky (fully quit first if it was running) to see the change.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("locate", help="Find NMS save files under %APPDATA%\\HelloGames\\NMS")

    p_check = sub.add_parser("check", help="Check whether data/mapping.json is stale for this save")
    p_check.add_argument("path", help="Path to a save.hg / save2.hg file")

    p_list = sub.add_parser("list", help="List ship slots in a save file (read-only)")
    p_list.add_argument("path", help="Path to a save.hg / save2.hg file")
    p_list.add_argument("-v", "--verbose", action="store_true")

    p_set = sub.add_parser("set-seed", help="Change one ship's procedural seed")
    p_set.add_argument("path", help="Path to a save.hg / save2.hg file")
    p_set.add_argument("--slot", type=int, required=True, help="Ship slot index (see `list`)")
    p_set.add_argument("--seed", required=True, help="New seed, e.g. 0xDEADBEEF12345678")
    p_set.add_argument("--apply", action="store_true", help="Actually write the change (default is dry-run)")

    p_paint = sub.add_parser("paint", help="Paint a sentinel ship (experimental; dry-run unless --apply)")
    p_paint.add_argument("path", help="Path to a save.hg / save2.hg file")
    p_paint.add_argument("--slot", type=int, required=True, help="Ship slot index (see `list`)")
    p_paint.add_argument("--colour", default="0,0,0", help="R,G,B in 0..1 (default 0,0,0 = pure black)")
    p_paint.add_argument("--overlay", default="4", choices=["1", "2", "3", "4"],
                         help="1 Orange+White, 2 Painted+White, 3 Purple+Painted, 4 Painted+Painted (default)")
    p_paint.add_argument("--fixed", default="1", choices=["1", "2"], help="FIXED texture variant")
    p_paint.add_argument("--method", default="both", choices=["override", "both"],
                         help="both (default): palette paint, which the game applies; override: exact colour only (ignored in tests)")
    p_paint.add_argument("--palette", default="FREIGHTER",
                         help="palette the game snaps the colour to (default FREIGHTER: has true black; SHIP does not)")
    p_paint.add_argument("--clear", action="store_true", help="Remove the stored paint (back to default)")
    p_paint.add_argument("--apply", action="store_true", help="Actually write the change (default is dry-run)")

    args = parser.parse_args()

    if args.command == "paint":
        return cmd_paint(args)
    if args.command == "locate":
        return cmd_locate(args)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "set-seed":
        return cmd_set_seed(args)


if __name__ == "__main__":
    sys.exit(main())
