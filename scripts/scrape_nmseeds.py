"""Scrape the (now-static, archived) nmseeds.club ship seed catalog into a
local CSV: data/real_ships.csv.

The site's own "Final Update" banner says it's frozen (no new seeds, no
further updates) and explicitly invites reuse ("If anyone wants to take
over the database... get in touch"), so this is a one-time, polite,
rate-limited crawl of publicly-listed, sharing-oriented data -- not
hammering a live service.

Usage:
    python scripts/scrape_nmseeds.py                # resume/continue
    python scripts/scrape_nmseeds.py --max-pages 5   # smoke test
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import urllib.request
from html import unescape

BASE = "https://www.nmseeds.club"
START_PATH = "/Seeds/Search/ship.html"
SEARCH_PREFIX = "/Seeds/Search/"

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OUT_PATH = os.path.join(BASE_DIR, "data", "real_ships.csv")
CHECKPOINT_PATH = os.path.join(BASE_DIR, "data", ".nmseeds_checkpoint")

FIELDNAMES = ["seed", "category", "type", "colours", "nms_version", "description", "thumb_url"]

ENTRY_RE = re.compile(
    r'<li class="seed">\s*'
    r'<img src="(?P<thumb>[^"]*)"[^>]*/>\s*'
    r'<div class="seed-data">\s*<table>\s*'
    r'<tr><th>Category:\s*</th><td>(?P<category>[^<]*)</td></tr>\s*'
    r'<tr><th>Type:\s*</th><td>(?P<type>[^<]*)</td></tr>\s*'
    r'<tr><th>Seed:\s*</th><td>(?P<seed>[^<]*)</td></tr>\s*'
    r'<tr><th>Colours:\s*</th><td>(?P<colours>[^<]*)</td></tr>\s*'
    r'<tr><th>NMS Version:\s*</th><td>(?P<version>[^<]*)</td></tr>\s*'
    r'<tr><th>Description:\s*</th><td>(?P<description>[^<]*)</td></tr>',
    re.MULTILINE,
)

NEXT_RE = re.compile(r'<a href="([^"]+)"><input type="button" value="Next Page"')


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "nms-seed-tool/1.0 (local research script)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_entries(html: str):
    for m in ENTRY_RE.finditer(html):
        d = m.groupdict()
        yield {
            "seed": unescape(d["seed"]).strip(),
            "category": unescape(d["category"]).strip(),
            "type": unescape(d["type"]).strip(),
            "colours": unescape(d["colours"]).strip(),
            "nms_version": unescape(d["version"]).strip(),
            "description": unescape(d["description"]).strip(),
            "thumb_url": BASE + d["thumb"] if d["thumb"].startswith("/") else d["thumb"],
        }


def parse_next(html: str) -> str | None:
    m = NEXT_RE.search(html)
    if not m:
        return None
    href = unescape(m.group(1))
    if href.startswith("http"):
        return href
    return BASE + SEARCH_PREFIX + href


def load_seen_seeds() -> set[str]:
    if not os.path.exists(OUT_PATH):
        return set()
    with open(OUT_PATH, newline="", encoding="utf-8") as f:
        return {row["seed"] for row in csv.DictReader(f)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=None, help="Stop after N pages (for testing)")
    parser.add_argument("--delay", type=float, default=0.6, help="Seconds between requests")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    # Resume point: either a saved checkpoint URL, or the start page.
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            url = f.read().strip() or (BASE + START_PATH)
    else:
        url = BASE + START_PATH

    file_exists = os.path.exists(OUT_PATH)
    seen = load_seen_seeds()
    print(f"[INFO] Resuming from: {url}")
    print(f"[INFO] Already have {len(seen)} seeds in {OUT_PATH}")

    out_f = open(OUT_PATH, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=FIELDNAMES)
    if not file_exists:
        writer.writeheader()

    page = 0
    new_count = 0
    try:
        while url:
            page += 1
            if args.max_pages and page > args.max_pages:
                print(f"[INFO] Hit --max-pages {args.max_pages}, stopping.")
                break

            try:
                html = fetch(url)
            except Exception as e:
                print(f"[WARN] Fetch failed for {url}: {e} -- stopping, checkpoint preserved for resume.")
                break

            entries = list(parse_entries(html))
            added_this_page = 0
            for e in entries:
                if e["seed"] and e["seed"] not in seen:
                    writer.writerow(e)
                    seen.add(e["seed"])
                    new_count += 1
                    added_this_page += 1
            out_f.flush()

            next_url = parse_next(html)
            print(f"[INFO] page {page}: {len(entries)} entries ({added_this_page} new). "
                  f"next={'yes' if next_url else 'NONE (done)'}")

            # Save checkpoint *before* moving on, so a crash resumes at the
            # right place.
            with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
                f.write(next_url or "")

            if not next_url or next_url == url:
                break
            url = next_url
            time.sleep(args.delay)
    finally:
        out_f.close()

    print(f"\n[DONE] Added {new_count} new seeds this run. Total in {OUT_PATH}: {len(seen)}")


if __name__ == "__main__":
    sys.exit(main())
