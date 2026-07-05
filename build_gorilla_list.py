#!/usr/bin/env python3

import json
import re
import time
from collections import deque
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE = "https://www.gorillasland.com/"

START_PAGES = [
    "https://www.gorillasland.com/",
    "https://www.gorillasland.com/gorilla-database.php",
    "https://www.gorillasland.com/north-american-database.php",
    "https://www.gorillasland.com/european-database.php",
    "https://www.gorillasland.com/asian-database.php",
    "https://www.gorillasland.com/oceanian-database.php",
    "https://www.gorillasland.com/south-american-database.php",
]

OUTPUT_FILE = Path(__file__).with_name("gorilla_pages.js")

HEADERS = {
    "User-Agent": "Personal local random gorilla page list builder"
}


def normalize_url(url: str) -> str:
    parsed = urlparse(url)

    # Keep only scheme, domain, and path.
    # This removes fragments and query strings.
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def is_gorillasland_page(url: str) -> bool:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return False

    if parsed.netloc != "www.gorillasland.com":
        return False

    if not parsed.path.endswith(".php") and parsed.path not in {"", "/"}:
        return False

    return True


def extract_links(html: str, current_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        full_url = normalize_url(urljoin(current_url, href))

        if is_gorillasland_page(full_url):
            links.append(full_url)

    return links


def looks_like_individual_gorilla_profile(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()

    # Zoo pages often contain "Current gorilla population".
    # Individual profile pages are more likely to contain these profile fields.
    profile_markers = [
        "official register",
        "species:",
        "sex:",
    ]

    birth_markers = [
        "date of birth",
        "birth date",
        "birthdate",
        "born:",
    ]

    has_profile_markers = all(marker in text for marker in profile_markers)
    has_birth_marker = any(marker in text for marker in birth_markers)

    return has_profile_markers and has_birth_marker


def infer_alive_status(html: str) -> bool | None:
    """
    Returns:
      True  = death fields explicitly say alive
      False = death fields contain actual death information
      None  = death fields could not be found clearly
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    death_fields = [
        "Date of death",
        "Place of death",
        "Cause of death",
    ]

    values = {}

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        for field in death_fields:
            # Handles either:
            #   Date of death: alive
            # or:
            #   Date of death:
            #   alive
            if line.lower().startswith(field.lower()):
                value = line[len(field):].strip()

                if value.startswith(":"):
                    value = value[1:].strip()

                if not value and i + 1 < len(lines):
                    value = lines[i + 1].strip()

                values[field] = value.lower()

    if not values:
        return None

    # Live gorillas have all death fields marked "alive".
    if all(values.get(field) == "alive" for field in death_fields):
        return True

    # If any death field exists and is not "alive", treat as deceased.
    if any(field in values and values[field] != "alive" for field in death_fields):
        return False

    return None


def crawl(max_pages: int = 8000) -> list[dict[str, object]]:
    session = requests.Session()
    session.headers.update(HEADERS)

    queue = deque(START_PAGES)
    seen = set()
    profiles = {}

    while queue and len(seen) < max_pages:
        url = normalize_url(queue.popleft())

        if url in seen:
            continue

        seen.add(url)
        if len(seen) % 100 == 0:
            print(f"Checked {len(seen)} pages, found {len(profiles)} profiles, queue={len(queue)}")

        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
        except requests.RequestException:
            continue

        html = response.text

        if looks_like_individual_gorilla_profile(html):
            profiles[url] = {
                "url": url,
                "isAlive": infer_alive_status(html),
            }

        for link in extract_links(html, url):
            if link not in seen:
                queue.append(link)

        # Avoid hammering the site.
        time.sleep(0.15)

    return [profiles[url] for url in sorted(profiles)]


def write_js_file(profiles: list[dict[str, object]]) -> None:
    urls = [profile["url"] for profile in profiles]
    js = (
        "// Generated by build_gorilla_list.py\n"
        "// Re-run the Python script if you want to refresh the list.\n\n"
        "window.GORILLA_PAGES = "
        + json.dumps(urls, indent=2)
        + ";\n\n"
        "window.GORILLA_PAGE_DATA = "
        + json.dumps(profiles, indent=2)
        + ";\n\n"
        "window.GORILLA_PAGES_UPDATED = "
        + json.dumps(date.today().isoformat())
        + ";\n"
    )

    OUTPUT_FILE.write_text(js, encoding="utf-8")


def main() -> None:
    profiles = crawl()
    write_js_file(profiles)

    print(f"Saved {len(profiles)} gorilla profile URLs to:")
    print(OUTPUT_FILE)

    if not profiles:
        print()
        print("No profiles were found. The page-detection rules may need adjustment.")


if __name__ == "__main__":
    main()
