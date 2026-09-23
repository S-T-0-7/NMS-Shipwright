"""Shared access to the real ship-seed catalog (data/real_ships.csv).

Used by tools/seed_finder.py, tools/add_seed.py, and webapp/app.py so all
three agree on the schema and file location.
"""
from __future__ import annotations

import csv
import os

from .ships import is_valid_seed

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "real_ships.csv")

FIELDNAMES = ["seed", "type", "colours", "nms_version", "description", "source", "image_url", "requires_mod"]


def load_rows() -> list[dict]:
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def filter_rows(
    rows: list[dict],
    *,
    type_substr: str | None = None,
    colour_substr: str | None = None,
    source_substr: str | None = None,
) -> list[dict]:
    if type_substr:
        needle = type_substr.lower()
        rows = [r for r in rows if needle in r.get("type", "").lower()]
    if colour_substr:
        needle = colour_substr.lower()
        rows = [r for r in rows if needle in r.get("colours", "").lower()]
    if source_substr:
        needle = source_substr.lower()
        rows = [r for r in rows if needle in r.get("source", "").lower()]
    return rows


def known_types(rows: list[dict] | None = None) -> list[tuple[str, int]]:
    rows = rows if rows is not None else load_rows()
    counts: dict[str, int] = {}
    for r in rows:
        t = r.get("type", "").strip()
        if t:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items())


def known_colours(rows: list[dict] | None = None) -> list[str]:
    rows = rows if rows is not None else load_rows()
    colours: set[str] = set()
    for r in rows:
        for c in r.get("colours", "").split(","):
            c = c.strip()
            if c:
                colours.add(c)
    return sorted(colours)


def add_row(
    seed: str,
    *,
    type: str = "",
    colours: str = "",
    nms_version: str = "",
    description: str = "",
    source: str = "manual",
    image_url: str = "",
    requires_mod: str = "",
) -> bool:
    """Append one row. Returns False (no-op) if the seed is already present.

    requires_mod: name of a third-party game mod this seed depends on
    (empty for vanilla-compatible seeds). E.g. "gShip - Gumsk's Custom
    Ships" -- these seeds only do anything if that mod's PAK is installed
    in the game's PCBANKS/MODS folder; without it, applying them to a
    fixed-model slot (like Golden Vector) does nothing, same as any other
    fixed-model seed.
    """
    if not is_valid_seed(seed):
        raise ValueError(f"Seed must be '0x' + hex digits (a 64-bit value); got {seed!r}")

    existing = {r["seed"].lower() for r in load_rows()}
    if seed.lower() in existing:
        return False

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    file_exists = os.path.exists(DATA_PATH)
    with open(DATA_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "seed": seed,
                "type": type,
                "colours": colours,
                "nms_version": nms_version,
                "description": description,
                "source": source,
                "image_url": image_url,
                "requires_mod": requires_mod,
            }
        )
    return True
