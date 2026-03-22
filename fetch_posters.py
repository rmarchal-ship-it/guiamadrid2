#!/usr/bin/env python3
"""
fetch_posters.py — Fetch movie poster URLs from TMDB and bake them into the HTML.

Reads TMDB_IDS from cartelera_standalone.html, fetches poster paths from TMDB API,
and updates EMBEDDED_MOVIES with real poster URLs. Run at build/scrape time.

Requires TMDB_API_KEY env var (free at https://www.themoviedb.org/).
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

HTML_FILE = Path(__file__).parent / "cartelera_standalone.html"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p/w500"


def get_api_key() -> str:
    key = os.environ.get("TMDB_API_KEY", "")
    if not key:
        print("❌ Set TMDB_API_KEY env var (free at https://www.themoviedb.org/)")
        sys.exit(1)
    return key


def fetch_poster_path(tmdb_id: int, api_key: str) -> str:
    """Fetch poster_path from TMDB API for a movie."""
    for lang in ["es-ES", "en-US", ""]:
        lang_param = f"&language={lang}" if lang else ""
        url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={api_key}{lang_param}"
        try:
            req = Request(url, headers={"User-Agent": "GuiaMadrid/1.0"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("poster_path"):
                    return data["poster_path"]
        except (URLError, json.JSONDecodeError, KeyError):
            continue
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
    print("=" * 60)
    print("🖼️  Fetch Posters — Guía Madrid Cartelera")
    print("=" * 60)

    api_key = get_api_key()
    html = HTML_FILE.read_text(encoding="utf-8")
    tmdb_ids = extract_tmdb_ids(html)

    if not tmdb_ids:
        print("❌ No TMDB_IDS found in HTML")
        return 1

    print(f"🎬 {len(tmdb_ids)} movies with TMDB IDs")

    poster_map: dict[str, str] = {}
    for title, tmdb_id in tmdb_ids.items():
        poster_path = fetch_poster_path(tmdb_id, api_key)
        if poster_path:
            poster_map[title] = f"{TMDB_IMG_BASE}{poster_path}"
            print(f"  ✅ {title}: {poster_path}")
        else:
            print(f"  ❌ {title}: no poster found")

    print(f"\n📊 {len(poster_map)}/{len(tmdb_ids)} posters found")

    if poster_map:
        html = update_movie_posters(html, poster_map)
        HTML_FILE.write_text(html, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
