#!/usr/bin/env python3
"""
Fetch Letterboxd diary, favorites, and profile stats.
Writes films.json. Stdlib only — no pip needed.
"""

import json, re, sys, urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

USERNAME    = "jaiminbabaria"
PROFILE_URL = f"https://letterboxd.com/{USERNAME}/"
RSS_URL     = f"https://letterboxd.com/{USERNAME}/rss/"
MAX_FILMS   = 12
OUTPUT      = "films.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# ── favorites ────────────────────────────────────────────────────────────────
# Letterboxd embeds favorites in the page's meta description as:
#   "... Favorites: Spider-Man 2 (2004), Rango (2011). Bio: ..."
# That's the cleanest source — title + year, always present, never lazy-loaded.

def parse_favorites(html):
    m = re.search(r'Favorites?:\s*([^.]+?)\.\s*(?:Bio:|"|$|<)', html, re.I)
    if not m:
        # broader fallback — just "Favorites: ... ."
        m = re.search(r'Favorites?:\s*([^.<"]+)', html, re.I)
        if not m:
            return []

    raw = m.group(1).strip()
    favorites = []
    # split on commas, then each entry is "Title (year)"
    for entry in re.split(r',\s*', raw):
        entry = entry.strip()
        if not entry:
            continue
        ym = re.search(r'^(.*?)\s*\((\d{4})\)\s*$', entry)
        if ym:
            favorites.append({"title": ym.group(1).strip(), "year": ym.group(2)})
        else:
            favorites.append({"title": entry, "year": ""})
        if len(favorites) >= 4:
            break
    return favorites


# ── stats ────────────────────────────────────────────────────────────────────
# Real Letterboxd profile-stats markup (from inspection):
#   <a href="/jaiminbabaria/films/"><span class="value">565</span>...Films</a>
#   <a href="/jaiminbabaria/diary/for/2026/"><span class="value">51</span>...This year</a>

def parse_stats(html):
    stats = {"total": None, "this_year": None}
    year = str(datetime.now(timezone.utc).year)

    m = re.search(
        r'href=["\']/' + re.escape(USERNAME) + r'/films/["\']'
        r'[\s\S]{0,200}?<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>([\d,]+)</span>',
        html
    )
    if m:
        stats["total"] = int(m.group(1).replace(",", ""))

    m = re.search(
        r'href=["\']/' + re.escape(USERNAME) + r'/diary/for/' + year + r'/["\']'
        r'[\s\S]{0,200}?<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>([\d,]+)</span>',
        html
    )
    if m:
        stats["this_year"] = int(m.group(1).replace(",", ""))

    return stats


# ── RSS ──────────────────────────────────────────────────────────────────────

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


def parse_rss(xml_text):
    root = ET.fromstring(xml_text.encode("utf-8"))
    films = []
    current_year = str(datetime.now(timezone.utc).year)
    year_count = 0
    for item in root.iter():
        if item.tag.split("}")[-1] != "item":
            continue
        title = local_text(item, "filmTitle")
        if not title:
            continue
        watched = local_text(item, "watchedDate")
        if watched.startswith(current_year):
            year_count += 1
        rating_raw = local_text(item, "memberRating")
        try:
            rating = float(rating_raw) if rating_raw else None
        except ValueError:
            rating = None
        if len(films) < MAX_FILMS:
            films.append({
                "title":   title,
                "year":    local_text(item, "filmYear"),
                "rating":  rating,
                "date":    format_date(watched),
                "url":     local_text(item, "link"),
                "rewatch": local_text(item, "rewatch").lower() == "yes",
            })
    return films, year_count


# ── main ─────────────────────────────────────────────────────────────────────

def load_existing():
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    existing  = load_existing()
    favorites = existing.get("favorites", [])
    stats     = existing.get("stats", {"total": None, "this_year": None})

    # Profile (favorites + stats)
    try:
        html = fetch(PROFILE_URL)
        fav = parse_favorites(html)
        st  = parse_stats(html)
        print(f"favorites: {fav}")
        print(f"stats:     {st}")
        if fav:
            favorites = fav
        if st["total"] is not None:
            stats["total"] = st["total"]
        if st["this_year"] is not None:
            stats["this_year"] = st["this_year"]
    except Exception as exc:
        print(f"WARNING profile: {exc}", file=sys.stderr)

    # RSS (recent films + year-count fallback)
    films = existing.get("films", [])
    try:
        rss = fetch(RSS_URL)
        parsed, year_count = parse_rss(rss)
        if parsed:
            films = parsed
            print(f"RSS: {len(films)} films, {year_count} in {datetime.now(timezone.utc).year}")
            if stats.get("this_year") is None and year_count:
                stats["this_year"] = year_count
    except Exception as exc:
        print(f"WARNING RSS: {exc}", file=sys.stderr)

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
    print(f"Written → {OUTPUT}")


if __name__ == "__main__":
    main()
