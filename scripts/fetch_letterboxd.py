#!/usr/bin/env python3
"""
Fetch the latest diary entries from a public Letterboxd RSS feed and
write them to films.json. Run by a scheduled GitHub Action.

Stdlib only — no pip install needed.
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

USERNAME = "jaiminbabaria"          # ← your Letterboxd username (lowercase)
RSS_URL = f"https://letterboxd.com/{USERNAME}/rss/"
MAX_FILMS = 12                      # store a buffer; the page shows 6
OUTPUT = "films.json"


def local_text(item, name):
    """Return text of the first child whose local tag name matches `name`."""
    for child in item.iter():
        if child.tag.split("}")[-1] == name:
            return (child.text or "").strip()
    return ""


def fetch_rss(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (portfolio-letterboxd-bot; +github-actions)"
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def format_date(iso):
    if not iso:
        return ""
    try:
        # %-d (no leading zero) works on the Linux runners GitHub Actions uses.
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%b %-d, %Y")
    except ValueError:
        return iso


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    films = []
    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue

        title = local_text(item, "filmTitle")
        if not title:
            continue  # skip list entries / non-film items

        rating_raw = local_text(item, "memberRating")
        try:
            rating = float(rating_raw) if rating_raw else None
        except ValueError:
            rating = None

        films.append(
            {
                "title": title,
                "year": local_text(item, "filmYear"),
                "rating": rating,
                "date": format_date(local_text(item, "watchedDate")),
                "url": local_text(item, "link"),
                "rewatch": local_text(item, "rewatch").lower() == "yes",
            }
        )
        if len(films) >= MAX_FILMS:
            break
    return films


def main():
    try:
        xml_bytes = fetch_rss(RSS_URL)
        films = parse(xml_bytes)
    except Exception as exc:  # noqa: BLE001 - never fail the build hard
        print(f"ERROR fetching/parsing Letterboxd feed: {exc}", file=sys.stderr)
        # Exit 0 so a transient feed hiccup doesn't mark the Action red and
        # the previously committed films.json simply stays in place.
        sys.exit(0)

    if not films:
        print("No films parsed; leaving existing films.json untouched.", file=sys.stderr)
        sys.exit(0)

    payload = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "username": USERNAME,
        "films": films,
    }

    with open(OUTPUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Wrote {len(films)} films to {OUTPUT}.")


if __name__ == "__main__":
    main()
