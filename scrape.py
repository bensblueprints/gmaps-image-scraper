"""
Google Maps business-photo scraper.

Usage:
    python scrape.py "joe's pizza brooklyn"
    python scrape.py --url "https://www.google.com/maps/place/..."
    python scrape.py --csv queries.csv          # one query per line
    python scrape.py "query" --max 50 --out ./photos --headful

Notes:
    - Uses Playwright (headless Chromium). Run `playwright install chromium` once.
    - Scrapes the public photo grid; no API key required.
    - Be considerate with rate. ToS-grey: use for your own research, not resale.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.async_api import Page, async_playwright

PHOTO_URL_RE = re.compile(r"https://[^\"'\\)]+?googleusercontent\.com/[^\"'\\)\s]+")


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)[:80] or "place"


def upgrade_resolution(url: str) -> str:
    # Google photo URLs end in =wNNN-hNNN-... — bump to a large size.
    return re.sub(r"=w\d+-h\d+(-[a-z0-9-]+)?$", "=w2048-h2048-k-no", url)


async def accept_consent(page: Page) -> None:
    for sel in [
        'button:has-text("Accept all")',
        'button:has-text("I agree")',
        'button[aria-label*="Accept"]',
        'form[action*="consent"] button',
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await page.wait_for_timeout(800)
                return
        except Exception:
            pass


async def open_place(page: Page, query_or_url: str) -> None:
    if query_or_url.startswith("http"):
        await page.goto(query_or_url, wait_until="domcontentloaded")
    else:
        await page.goto(
            f"https://www.google.com/maps/search/{query_or_url.replace(' ', '+')}",
            wait_until="domcontentloaded",
        )
    await accept_consent(page)
    await page.wait_for_timeout(1500)

    # If a search result list appears, click the first card.
    try:
        first = page.locator('a.hfpxzc').first
        if await first.is_visible(timeout=2500):
            await first.click()
            await page.wait_for_timeout(2000)
    except Exception:
        pass


async def open_photos_panel(page: Page) -> bool:
    candidates = [
        'button[aria-label^="Photo of"]',
        'button[jsaction*="pane.heroHeaderImage"]',
        'div[aria-label="Photo"]',
        'button:has-text("See photos")',
    ]
    for sel in candidates:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2500):
                await el.click()
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    return False


async def scroll_collect(page: Page, max_photos: int) -> set[str]:
    found: set[str] = set()
    # The photo grid is inside a scrollable region; find it by aria role.
    scroller = page.locator('div[role="main"]').last
    stale_rounds = 0
    for _ in range(80):
        html = await page.content()
        for m in PHOTO_URL_RE.findall(html):
            found.add(m)
        if len(found) >= max_photos:
            break
        before = len(found)
        try:
            await scroller.evaluate("el => el.scrollBy(0, 1200)")
        except Exception:
            await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(700)
        stale_rounds = stale_rounds + 1 if len(found) == before else 0
        if stale_rounds >= 5:
            break
    return found


async def download(urls: list[str], out_dir: Path, max_photos: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for url in urls[:max_photos]:
            big = upgrade_resolution(url)
            try:
                r = await client.get(big)
                r.raise_for_status()
            except Exception:
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                except Exception as e:
                    print(f"  skip {url[:80]}... ({e})")
                    continue
            ext = ".jpg"
            ctype = r.headers.get("content-type", "")
            if "png" in ctype:
                ext = ".png"
            elif "webp" in ctype:
                ext = ".webp"
            name = hashlib.sha1(url.encode()).hexdigest()[:16] + ext
            (out_dir / name).write_bytes(r.content)
            saved += 1
    return saved


async def scrape_one(query: str, out_root: Path, max_photos: int, headful: bool) -> None:
    label = slugify(query if not query.startswith("http") else urlparse(query).path)
    out_dir = out_root / label
    print(f"\n=> {query}\n   out: {out_dir}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 950},
            locale="en-US",
        )
        page = await ctx.new_page()
        try:
            await open_place(page, query)
            if not await open_photos_panel(page):
                print("   ! could not open photos panel; collecting hero images only")
            urls = await scroll_collect(page, max_photos)
            print(f"   found {len(urls)} candidate URLs")
            saved = await download(sorted(urls), out_dir, max_photos)
            print(f"   saved {saved} files -> {out_dir}")
        finally:
            await browser.close()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Google Maps photo scraper")
    ap.add_argument("query", nargs="?", help="search query, e.g. \"joe's pizza brooklyn\"")
    ap.add_argument("--url", help="direct google maps place URL")
    ap.add_argument("--csv", help="CSV/text file, one query or URL per line")
    ap.add_argument("--max", type=int, default=40, help="max photos per place")
    ap.add_argument("--out", default="./photos", help="output directory")
    ap.add_argument("--headful", action="store_true", help="show browser window")
    return ap.parse_args()


async def main() -> int:
    args = parse_args()
    queries: list[str] = []
    if args.csv:
        with open(args.csv, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and row[0].strip():
                    queries.append(row[0].strip())
    if args.url:
        queries.append(args.url)
    if args.query:
        queries.append(args.query)
    if not queries:
        print("error: provide a query, --url, or --csv", file=sys.stderr)
        return 2
    out_root = Path(args.out)
    for q in queries:
        try:
            await scrape_one(q, out_root, args.max, args.headful)
        except Exception as e:
            print(f"   ! failed: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
