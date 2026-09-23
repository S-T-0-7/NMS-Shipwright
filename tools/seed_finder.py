#!/usr/bin/env python
"""Search the real ship-seed catalog (data/real_ships.csv).

This catalog is a small, *verified* starter set (currently ~60 ships)
pulled from two community sources -- see README.md and
scripts/build_real_ships.py for where it comes from and its limits.

    python tools/seed_finder.py list
    python tools/seed_finder.py list --type fighter
    python tools/seed_finder.py list --colour gold
    python tools/seed_finder.py list --type hauler --colour red
    python tools/seed_finder.py show 0xf1766bcdcf6d73fe

Once you've found a seed you like:
    python tools/save_editor.py set-seed "<path>" --slot N --seed <seed> --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nms_save import catalog  # noqa: E402


def describe(row: dict) -> str:
    bits = [f"[{row['type'] or '?'}] {row['seed']}"]
    if row.get("colours"):
        bits.append(f"colours: {row['colours']}")
    if row.get("description"):
        bits.append(f'"{row["description"]}"')
    bits.append(f"(source: {row.get('source', '?')})")
    return "  ".join(bits)


def cmd_list(args):
    rows = catalog.load_rows()
    if not rows:
        print(f"No catalog at {catalog.DATA_PATH}.")
        print("Build it with: python scripts/scrape_nmseeds.py && python scripts/build_real_ships.py")
        return 1

    rows = catalog.filter_rows(rows, type_substr=args.type, colour_substr=args.colour, source_substr=args.source)

    if not rows:
        print("No matches.")
        return

    print(f"{len(rows)} match(es):\n")
    for r in rows:
        print(describe(r))


def cmd_show(args):
    rows = catalog.load_rows()
    matches = [r for r in rows if r["seed"].lower() == args.seed.lower()]
    if not matches:
        print(f"No entry for seed {args.seed}")
        return 1

    for r in matches:
        for k, v in r.items():
            print(f"  {k}: {v}")
    return 0


def cmd_types(args):
    for t, count in catalog.known_types():
        print(f"  {t}  ({count})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List/filter ships in the catalog")
    p_list.add_argument("--type", help="Substring match on ship type (e.g. Fighter, Hauler, Exotic)")
    p_list.add_argument("--colour", "--color", dest="colour", help="Substring match on colours")
    p_list.add_argument("--source", help="Substring match on data source")

    p_show = sub.add_parser("show", help="Show full details for one seed")
    p_show.add_argument("seed", help="e.g. 0xf1766bcdcf6d73fe")

    sub.add_parser("types", help="List available ship types and counts")

    args = parser.parse_args()

    if args.command == "list":
        return cmd_list(args)
    if args.command == "show":
        return cmd_show(args)
    if args.command == "types":
        return cmd_types(args)


if __name__ == "__main__":
    sys.exit(main())
