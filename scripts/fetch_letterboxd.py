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
DEBUG_FILE  = "letterboxd_debug.html"   # ← committed once; delete after fixing

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


# ── write debug snapshot ──────────────────────────────────────────────────────

def write_debug(html):
    """
    Save key HTML snippets to letterboxd_debug.html so we can inspect
    Letterboxd's actual structure and tune the regex patterns.
    Delete this file (and the write_debug call) once patterns are confirmed.
    """
    markers = [
        "favourites", "favourite", "data-film-name", "data-film-slug",
        "poster-list", "profile-stats", "this-year", "value", "label",
        str(datetime.now(timezone.utc).year),
    ]
    lines = [f"Fetched: {datetime.now(timezone.utc).isoformat()}\n",
             f"Page length: {len(html):,} chars\n\n"]

    for m in markers:
        idx = html.lower().find(m.lower())
        if idx >= 0:
            snippet = html[max(0, idx - 120):idx + 300]
            lines.append(f"=== '{m}' found at {idx} ===\n{snippet}\n\n")
        else:
            lines.append(f"=== '{m}' NOT FOUND ===\n\n")

    # Also dump the first 3 KB and any <section> tags
    lines.append("=== FIRST 3KB ===\n" + html[:3000] + "\n\n")
    for s in re.findall(r'<section[^>]*>', html, re.I)[:20]:
        lines.append(f"SECTION TAG: {s}\n")

    with open(DEBUG_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"Debug snapshot → {DEBUG_FILE}", file=sys.stderr)


# ── profile scraping ──────────────────────────────────────────────────────────

def scrape_profile(html):
    favorites = _parse_favorites(html)
    stats     = _parse_stats(html)
    return favorites, stats


def _parse_favorites(html):
    seen, favorites = set(), []

    # Try every known attribute / structure Letterboxd has used
    patterns = [
        # Current: data-film-name + data-film-year (either order)
        r'data-film-name=["\']([^"\']+)["\'][^>]*?data-film-year=["\']([^"\']*)["\']',
        r'data-film-year=["\']([^"\']*)["\'][^>]*?data-film-name=["\']([^"\']+)["\']',
        # Slug-only fallback (convert hyphens to spaces as approximation)
        r'data-film-slug=["\']([^"\']+)["\'][^>]*?data-film-year=["\']([^"\']*)["\']',
        # img alt inside a .poster-container (very reliable)
        r'<img[^>]+alt=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*film-poster[^"\']*["\']',
        # title attribute on anchor links to /film/
        r'href=["\'][^"\']*?/film/[^"\']+/["\'][^>]*?title=["\']([^"\']+)["\']',
    ]

    # Narrow to favourites section if possible
    section_html = html
    for spat in [
        r'id=["\']favourites["\'][\s\S]*?</section>',
        r'class=["\'][^"\']*favourite[^"\']*["\'][\s\S]{0,5000}?</section>',
    ]:
        m = re.search(spat, html, re.I)
        if m:
            section_html = m.group(0)
            break

    for pat in patterns:
        for groups in re.findall(pat, section_html, re.S | re.I):
            if isinstance(groups, str):
                name, year = groups, ""
            else:
                # figure out which is name vs 4-digit year
                a, b = groups[0].strip(), groups[1].strip() if len(groups) > 1 else ""
                name, year = (b, a) if re.fullmatch(r'\d{4}', a) else (a, b)
            # Convert slug to rough title
            name = name.replace("-", " ").title() if re.fullmatch(r'[a-z0-9-]+', name) else name
            if name and name not in seen:
                seen.add(name)
                favorites.append({"title": name, "year": year})
            if len(favorites) >= 4:
                return favorites

    return favorites


def _parse_stats(html):
    stats = {"total": None, "this_year": None}
    year = str(datetime.now(timezone.utc).year)

    # total — <span class="value">N</span> near /films/ link
    for pat in [
        r'href=["\']/' + re.escape(USERNAME) + r'/films/["\'][\s\S]{0,400}?'
        r'<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>([\d,]+)</span>',

        r'<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>([\d,]+)</span>'
        r'[\s\S]{0,200}?<span[^>]*class=["\'][^"\']*label[^"\']*["\'][^>]*>[Ff]ilm',

        r'([\d,]+)\s*[Ff]ilms?\b',
    ]:
        m = re.search(pat, html, re.S)
        if m:
            stats["total"] = int(m.group(1).replace(",", ""))
            break

    # this_year — multiple strategies
    for pat in [
        # profile stats block near year
        r'href=["\']/' + re.escape(USERNAME) + r'/films/diary/for/' + year
        + r'/["\'][\s\S]{0,400}?<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>([\d,]+)</span>',

        r'<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>([\d,]+)</span>'
        r'[\s\S]{0,300}?' + year,

        year + r'[\s\S]{0,300}?'
        r'<span[^>]*class=["\'][^"\']*value[^"\']*["\'][^>]*>([\d,]+)</span>',

        r'([\d,]+)\s*(?:films?\s+)?in\s+' + year,
        year + r'\D{0,10}([\d,]+)\s*films?',
    ]:
        m = re.search(pat, html, re.S | re.I)
        if m:
            stats["this_year"] = int(m.group(1).replace(",", ""))
            break

    return stats


# ── RSS ───────────────────────────────────────────────────────────────────────

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
    films, current_year = [], str(datetime.now(timezone.utc).year)
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

    # ── profile ───────────────────────────────────────────────────────────────
    try:
        profile_html = fetch(PROFILE_URL)
        write_debug(profile_html)       # ← remove this call once patterns work
        fav, st = scrape_profile(profile_html)
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

    # ── RSS ───────────────────────────────────────────────────────────────────
    films = existing.get("films", [])
    try:
        rss_text = fetch(RSS_URL)
        parsed, year_count = parse_rss(rss_text)
        if parsed:
            films = parsed
            print(f"{len(films)} films from RSS; {year_count} in {datetime.now(timezone.utc).year}")
            # Use RSS year count as fallback if profile didn't give us one
            if stats.get("this_year") is None and year_count:
                stats["this_year"] = year_count
                print("(this_year filled from RSS count)")
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
