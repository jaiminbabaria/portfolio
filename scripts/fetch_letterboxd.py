#!/usr/bin/env python3
"""
Fetch Letterboxd diary, favorites, and profile stats.
Writes everything to films.json. Stdlib only — no pip needed.
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

USERNAME   = "jaiminbabaria"
PROFILE_URL = f"https://letterboxd.com/{USERNAME}/"
RSS_URL     = f"https://letterboxd.com/{USERNAME}/rss/"
MAX_FILMS   = 12
OUTPUT      = "films.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# ── profile scraping ──────────────────────────────────────────────────────────

def scrape_profile(html):
    """Return (favorites_list, stats_dict) from the profile page HTML."""
    favorites = _parse_favorites(html)
    stats     = _parse_stats(html)
    return favorites, stats


def _parse_favorites(html):
    """
    Letterboxd profile favorites live in a <section id="favourites"> block.
    Each film poster has  data-film-name="…"  and  data-film-year="…".
    """
    # Narrow to the favourites section first so we don't pick up other posters.
    fav_section = re.search(
        r'id=["\']favourites["\'].*?</section>',
        html, re.S | re.I
    )
    chunk = fav_section.group(0) if fav_section else html

    pairs = re.findall(
        r'data-film-name=["\']([^"\']+)["\']'
        r'.*?data-film-year=["\']([^"\']*)["\']',
        chunk, re.S
    )
    if not pairs:
        # Try reversed attribute order
        pairs = re.findall(
            r'data-film-year=["\']([^"\']*)["\']'
            r'.*?data-film-name=["\']([^"\']+)["\']',
            chunk, re.S
        )
        pairs = [(b, a) for a, b in pairs]

    seen, favorites = set(), []
    for name, year in pairs:
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            favorites.append({"title": name, "year": year.strip()})
        if len(favorites) >= 4:
            break

    return favorites


def _parse_stats(html):
    """
    Pull total-films and this-year counts from the profile stats block.

    Letterboxd renders something like:
      <a href="/jaiminbabaria/films/">
        <span class="value">565</span>
        <span class="label">Films</span>
      </a>
    and similarly for the current year.
    """
    stats = {"total": None, "this_year": None}

    # Total films — link points to /username/films/
    m = re.search(
        r'href=["\']/' + re.escape(USERNAME) + r'/films/["\'][^>]*>'
        r'.*?<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>(\d[\d,]*)</span>',
        html, re.S | re.I
    )
    if m:
        stats["total"] = int(m.group(1).replace(",", ""))

    # Films this year — look for current-year count near a yearly link
    current_year = str(datetime.now(timezone.utc).year)
    m2 = re.search(
        r'href=["\']/' + re.escape(USERNAME) + r'/films/diary/for/' + current_year
        + r'/["\'][^>]*>.*?<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>(\d[\d,]*)</span>',
        html, re.S | re.I
    )
    if not m2:
        # fallback: look for a yearly section labelled with the current year
        m2 = re.search(
            r'>' + current_year + r'<.*?<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>(\d[\d,]*)</span>',
            html, re.S | re.I
        )
    if m2:
        stats["this_year"] = int(m2.group(1).replace(",", ""))

    return stats


# ── RSS parsing ───────────────────────────────────────────────────────────────

def local_text(item, name):
    for child in item.iter():
        if child.tag.split("}")[-1] == name:
            return (child.text or "").strip()
    return ""


def format_date(iso):
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%b %-d, %Y")
    except ValueError:
        return iso


def parse_rss(xml_bytes):
    root = ET.fromstring(xml_bytes)
    films = []
    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue
        title = local_text(item, "filmTitle")
        if not title:
            continue
        rating_raw = local_text(item, "memberRating")
        try:
            rating = float(rating_raw) if rating_raw else None
        except ValueError:
            rating = None
        films.append({
            "title":   title,
            "year":    local_text(item, "filmYear"),
            "rating":  rating,
            "date":    format_date(local_text(item, "watchedDate")),
            "url":     local_text(item, "link"),
            "rewatch": local_text(item, "rewatch").lower() == "yes",
        })
        if len(films) >= MAX_FILMS:
            break
    return films


# ── main ──────────────────────────────────────────────────────────────────────

def load_existing():
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    existing = load_existing()

    # ── profile (favorites + stats) ──────────────────────────────────────────
    favorites = existing.get("favorites", [])
    stats     = existing.get("stats", {"total": None, "this_year": None})
    try:
        profile_html = fetch(PROFILE_URL)
        fav, st = scrape_profile(profile_html)
        if fav:
            favorites = fav
            print(f"Favorites: {[f['title'] for f in favorites]}")
        else:
            print("WARNING: no favorites parsed; keeping previous.", file=sys.stderr)
        if st["total"] is not None:
            stats = st
            print(f"Stats: {stats}")
        else:
            print("WARNING: stats not parsed; keeping previous.", file=sys.stderr)
    except Exception as exc:
        print(f"WARNING: profile scrape failed ({exc}); keeping previous.", file=sys.stderr)

    # ── RSS (recent films) ───────────────────────────────────────────────────
    films = existing.get("films", [])
    try:
        rss_bytes = fetch(RSS_URL).encode("utf-8")
        parsed = parse_rss(rss_bytes)
        if parsed:
            films = parsed
            print(f"Films: {len(films)} entries parsed.")
        else:
            print("WARNING: RSS empty; keeping previous.", file=sys.stderr)
    except Exception as exc:
        print(f"WARNING: RSS fetch failed ({exc}); keeping previous.", file=sys.stderr)

    if not films:
        print("Nothing to write.", file=sys.stderr)
        sys.exit(0)

    payload = {
        "updated":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "username":  USERNAME,
        "stats":     stats,
        "favorites": favorites,
        "films":     films,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Written to {OUTPUT}.")


if __name__ == "__main__":
    main()
