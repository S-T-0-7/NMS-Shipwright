"""Build data/real_ships.csv: a small but genuine, real-seed ship catalog,
merged from two community sources:

  1. nmseeds.club -- richest fields (type, colours, description), but the
     site's pagination broke when it was archived to static hosting, so
     only its first page (~25 ships) is reachable. Produced separately by
     scripts/scrape_nmseeds.py.
  2. davoodinator/NMS_Seeds on GitHub -- a folder of
     Ships/<Category>/<seed>.jpg screenshots. No colour/description, but
     gives category + a verifiable image per seed.

Run scripts/scrape_nmseeds.py first (writes data/real_ships.csv itself),
then this script folds the GitHub source in on top of it.

This is a *starter* catalog (a few dozen entries), not a comprehensive
one -- see README.md for why, and tools/add_seed.py for growing it by
hand as you find more.
"""
from __future__ import annotations

import csv
import json
import os
import re
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "real_ships.csv")

GITHUB_TREE_URL = "https://api.github.com/repos/davoodinator/NMS_Seeds/git/trees/master?recursive=1"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/davoodinator/NMS_Seeds/master/"

FIELDNAMES = ["seed", "type", "colours", "nms_version", "description", "source", "image_url"]

# nmseeds.club categories -> our normalized vocabulary
TYPE_NORMALIZE = {
    "dropship/hauler": "Hauler",
    "scientific/explorer": "Explorer",
    "fighter": "Fighter",
    "exotic": "Exotic",
    "shuttle": "Shuttle",
    "organic": "Living Ship",
}

SEED_FILENAME_RE = re.compile(r"^(0x[0-9A-Fa-f]+)\.(jpg|jpeg|png)$")


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "nms-seed-tool/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def load_existing() -> list[dict]:
    if not os.path.exists(OUT_PATH):
        return []
    with open(OUT_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalize_nmseeds_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if "colours" not in r:
            continue  # not an nmseeds-shaped row (already normalized / from another source)
        out.append(
            {
                "seed": r["seed"],
                "type": TYPE_NORMALIZE.get(r.get("type", "").strip().lower(), r.get("type", "")),
                "colours": r.get("colours", ""),
                "nms_version": r.get("nms_version", ""),
                "description": r.get("description", ""),
                "source": "nmseeds.club",
                "image_url": r.get("thumb_url", ""),
            }
        )
    return out


def fetch_davoodinator_rows() -> list[dict]:
    tree = fetch_json(GITHUB_TREE_URL)
    rows = []
    for entry in tree.get("tree", []):
        path = entry["path"]
        if not path.startswith("Ships/") or "thumbnails" in path:
            continue
        parts = path.split("/")
        if len(parts) != 3:
            continue
        _, category, filename = parts
        m = SEED_FILENAME_RE.match(filename)
        if not m:
            continue
        seed = m.group(1)
        rows.append(
            {
                "seed": seed,
                "type": category,
                "colours": "",
                "nms_version": "",
                "description": "",
                "source": "davoodinator/NMS_Seeds",
                "image_url": GITHUB_RAW_BASE + path,
            }
        )
    return rows


def main():
    existing = normalize_nmseeds_rows(load_existing())
    print(f"[INFO] {len(existing)} rows from nmseeds.club (existing data/real_ships.csv)")

    try:
        github_rows = fetch_davoodinator_rows()
        print(f"[INFO] {len(github_rows)} rows from davoodinator/NMS_Seeds")
    except Exception as e:
        print(f"[WARN] Could not fetch davoodinator/NMS_Seeds: {e}")
        github_rows = []

    merged: dict[str, dict] = {}
    for row in existing + github_rows:
        merged.setdefault(row["seed"], row)  # first source wins (nmseeds has richer fields)

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in merged.values():
            writer.writerow(row)

    print(f"\n[DONE] Wrote {len(merged)} unique real ship seeds to {OUT_PATH}")


if __name__ == "__main__":
    main()
