#!/usr/bin/env python
"""Manually add one ship to data/real_ships.csv -- the practical way to grow
the catalog, since nmseeds.club's pagination is broken (see README.md) and
there's no other bulk source of hull-appearance seeds.

    python tools/add_seed.py 0xDEADBEEF12345678 --type Fighter \
        --colour "Red, Black" --description "Found in a Korvax system"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nms_save import catalog  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("seed", help="e.g. 0xDEADBEEF12345678")
    parser.add_argument("--type", default="", help="Fighter / Hauler / Explorer / Sentinel / Exotic / Shuttle / Living Ship / Solar")
    parser.add_argument("--colour", "--color", dest="colour", default="", help='Comma-separated, e.g. "Red, Black"')
    parser.add_argument("--version", dest="nms_version", default="", help="Game version you saw it in, if known")
    parser.add_argument("--description", default="")
    parser.add_argument("--image-url", dest="image_url", default="")
    parser.add_argument("--source", default="manual")
    args = parser.parse_args()

    try:
        added = catalog.add_row(
            args.seed,
            type=args.type,
            colours=args.colour,
            nms_version=args.nms_version,
            description=args.description,
            source=args.source,
            image_url=args.image_url,
        )
    except ValueError as e:
        print(e)
        return 1

    if not added:
        print(f"{args.seed} is already in the catalog -- not adding a duplicate.")
        return 1

    print(f"Added {args.seed} ({args.type or 'unknown type'}) to {catalog.DATA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
