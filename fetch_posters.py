#!/usr/bin/env python3
"""
fetch_posters.py — Fetch movie poster URLs and bake them into the HTML.

Three strategies, tried in order (NO API keys needed for any):
  1. SensaCine internal API (already used for showtimes) — poster field
  2. TMDB website scraping (public HTML pages, no API key)
  3. FilmAffinity website scraping

Run at build/scrape time: python fetch_posters.py
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

HTML_FILE = Path(__file__).parent / "cartelera_standalone.html"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w500"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def _fetch(url: str) -> str:
    """Fetch a URL and return its text content."""
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_poster_sensacine(theater_id: str, date_str: str) -> dict[str, str]:
    """Extract poster URLs from SensaCine showtimes API (same endpoint we scrape)."""
    posters: dict[str, str] = {}
    url = f"https://www.sensacine.com/_/showtimes/theater-{theater_id}/d-{date_str}/p-1"
    try:
        data = json.loads(_fetch(url))
        for entry in data.get("results", []):
            movie = entry.get("movie", {})
            title = movie.get("title", "")
            if not title:
                continue
            poster_obj = movie.get("poster")
            poster_url = ""
            if isinstance(poster_obj, dict):
                poster_url = poster_obj.get("url", "")
            elif isinstance(poster_obj, str):
                poster_url = poster_obj
            if poster_url and title not in posters:
                posters[title] = poster_url
    except Exception as e:
        print(f"  ⚠ SensaCine {theater_id}: {e}")
    return posters


def fetch_poster_tmdb_scrape(tmdb_id: int) -> str:
    """Scrape poster path from TMDB movie page (no API key needed)."""
    url = f"https://www.themoviedb.org/movie/{tmdb_id}"
    try:
        html = _fetch(url)
        # Look for og:image meta tag (contains poster URL)
        og = re.search(r'<meta\s[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', html)
        if og:
            img_url = og.group(1)
            # Convert to w500 size if it's a TMDB image
            img_url = re.sub(r'/t/p/w\d+/', '/t/p/w500/', img_url)
            return img_url
        # Fallback: look for any poster image URL
        m = re.search(r'(https://image\.tmdb\.org/t/p/\w+/\w+\.jpg)', html)
        if m:
            return re.sub(r'/t/p/w\d+/', '/t/p/w500/', m.group(1))
    except Exception as e:
        print(f"  ⚠ TMDB scrape {tmdb_id}: {e}")
    return ""


def fetch_poster_filmaffinity(title: str) -> str:
    """Search FilmAffinity for poster URL (no API key needed)."""
    from urllib.parse import quote_plus
    search_url = f"https://www.filmaffinity.com/es/search.php?stext={quote_plus(title)}&stype=title"
    try:
        html = _fetch(search_url)
        # Look for poster image on search results or movie page
        m = re.search(r'(https://pics\.filmaffinity\.com/[^"\']+\.jpg)', html)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"  ⚠ FilmAffinity '{title}': {e}")
    return ""


def extract_tmdb_ids(html: str) -> dict[str, int]:
    """Parse TMDB_IDS from HTML."""
    match = re.search(r"const TMDB_IDS\s*=\s*\{([^}]*)\}", html)
    if not match:
        return {}
    ids = {}
    for line in match.group(1).split("\n"):
        m = re.match(r'\s*"([^"]+)":\s*(\d+)', line)
        if m:
            ids[m.group(1)] = int(m.group(2))
    return ids


def extract_theater_ids(html: str) -> list[str]:
    """Parse cinema IDs from config.py if available."""
    config_path = Path(__file__).parent / "guiamadrid" / "config.py"
    if not config_path.exists():
        return []
    config = config_path.read_text(encoding="utf-8")
    return re.findall(r'"(E\d+|G\w+)":', config)


def update_movie_posters(html: str, poster_map: dict[str, str]) -> str:
    """Update poster_url in EMBEDDED_MOVIES JSON."""
    match = re.search(r"(const EMBEDDED_MOVIES\s*=\s*)(\[.*?\]);\s*\n", html)
    if not match:
        print("⚠ Could not find EMBEDDED_MOVIES in HTML")
        return html

    movies = json.loads(match.group(2))
    updated = 0
    for mv in movies:
        title = mv["title"]
        if title in poster_map and poster_map[title]:
            mv["poster_url"] = poster_map[title]
            updated += 1

    new_json = json.dumps(movies, ensure_ascii=False, separators=(",", ": "))
    html = html.replace(match.group(0), f"{match.group(1)}{new_json};\n")
    print(f"✅ Updated {updated} poster URLs in EMBEDDED_MOVIES")
    return html


def main():
    from datetime import date

    print("=" * 60)
    print("🖼️  Fetch Posters — Guía Madrid Cartelera")
    print("   No API keys needed — uses web scraping")
    print("=" * 60)

    html = HTML_FILE.read_text(encoding="utf-8")
    tmdb_ids = extract_tmdb_ids(html)
    today = date.today().strftime("%Y-%m-%d")

    # Extract existing poster URLs to skip movies that already have them
    match = re.search(r"const EMBEDDED_MOVIES\s*=\s*(\[.*?\]);\s*\n", html)
    existing_movies = json.loads(match.group(1)) if match else []
    existing_posters = {m["title"]: m.get("poster_url", "") for m in existing_movies}
    missing = [t for t, url in existing_posters.items() if not url]

    print(f"🎬 {len(existing_movies)} movies, {len(missing)} missing posters")
    if not missing:
        print("✅ All movies have posters!")
        return 0

    poster_map: dict[str, str] = {}

    # Strategy 1: SensaCine API (try a few theaters)
    print("\n📡 Strategy 1: SensaCine internal API...")
    theater_ids = extract_theater_ids(html) or ["E0621", "E0402", "E0247"]
    for tid in theater_ids[:3]:  # Try first 3 theaters
        sc_posters = fetch_poster_sensacine(tid, today)
        for title, url in sc_posters.items():
            if title in missing and title not in poster_map:
                poster_map[title] = url
                print(f"  ✅ {title}")
        time.sleep(0.5)
    still_missing = [t for t in missing if t not in poster_map]

    # Strategy 2: TMDB web scraping (no API key)
    if still_missing and tmdb_ids:
        print(f"\n🌐 Strategy 2: TMDB website scraping ({len(still_missing)} remaining)...")
        for title in still_missing:
            tmdb_id = tmdb_ids.get(title)
            if not tmdb_id:
                continue
            url = fetch_poster_tmdb_scrape(tmdb_id)
            if url:
                poster_map[title] = url
                print(f"  ✅ {title}")
            else:
                print(f"  ❌ {title}")
            time.sleep(0.5)
    still_missing = [t for t in missing if t not in poster_map]

    # Strategy 3: FilmAffinity scraping
    if still_missing:
        print(f"\n🎬 Strategy 3: FilmAffinity scraping ({len(still_missing)} remaining)...")
        for title in still_missing:
            url = fetch_poster_filmaffinity(title)
            if url:
                poster_map[title] = url
                print(f"  ✅ {title}")
            else:
                print(f"  ❌ {title}")
            time.sleep(1)

    # Summary
    final_missing = [t for t in missing if t not in poster_map]
    print(f"\n📊 Found {len(poster_map)}/{len(missing)} missing posters")
    if final_missing:
        print(f"❌ Still missing: {', '.join(final_missing)}")

    if poster_map:
        html = update_movie_posters(html, poster_map)
        HTML_FILE.write_text(html, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
