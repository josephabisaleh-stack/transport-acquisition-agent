"""
Playwright scraper for transmibat.fr (FFB — French construction sector business transfers).

Public site — no login required. Listings are displayed as clickable table rows
with a data-href attribute. Filters results for any transport-related entries.

Listings URL: https://www.transmibat.fr/espace-cession/accueil
"""

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PWTimeout

from browser import browser_page, screenshot_on_failure
from config import DELAY_BETWEEN_REQUESTS

logger = logging.getLogger(__name__)

SITE      = "transmibat"
BASE_URL  = "https://www.transmibat.fr"
LIST_URL  = f"{BASE_URL}/espace-cession/accueil"
MAX_PAGES = 10

_TRANSPORT_KW = [
    "transport", "transitaire", "logistique", "freight", "commissionnaire",
    "affrètement", "messagerie", "fret", "expéditeur", "shipping",
    "douane", "douanier", "camion", "camionnage", "livreur", "coursier",
]


def _is_transport_related(listing: dict) -> bool:
    combined = (listing["title"] + " " + listing["description"]).lower()
    return any(kw in combined for kw in _TRANSPORT_KW)


async def _extract_listings(page: Page) -> list[dict]:
    listings = []

    try:
        await page.wait_for_selector(
            "tr.table-row, tr[data-href], table tbody tr, [data-href], "
            "[class*='row'], [class*='item'], article, .card",
            timeout=15_000,
        )
    except PWTimeout:
        logger.debug("[transmibat] No listing rows appeared within timeout.")
        return []

    rows = await page.query_selector_all(
        "tr.table-row, tr[data-href], table tbody tr[class], "
        "[data-href]:not(head):not(html):not(body)"
    )

    # Fallback: any table row with a link inside
    if not rows:
        rows = await page.query_selector_all("table tbody tr")

    for row in rows:
        try:
            href = await row.get_attribute("data-href") or ""
            if not href:
                # Fallback: look for an anchor inside the row
                link_el = await row.query_selector("a[href]")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
            if not href:
                continue

            url = href if href.startswith("http") else BASE_URL + (href if href.startswith("/") else "/" + href)

            cells = await row.query_selector_all("td")
            texts = []
            for cell in cells:
                t = (await cell.inner_text()).strip()
                if t:
                    texts.append(t)

            if not texts:
                continue

            # Transmibat table columns: date | activity | location | revenue
            date     = texts[0] if len(texts) > 0 else "N/C"
            title    = texts[1] if len(texts) > 1 else texts[0]
            location = texts[2] if len(texts) > 2 else "N/C"
            price    = texts[3] if len(texts) > 3 else "N/C"

            listings.append({
                "source":      "Transmibat",
                "title":       title,
                "url":         url.strip(),
                "description": "",
                "price":       price,
                "location":    location,
                "date":        date,
            })
        except Exception as exc:
            logger.debug("[transmibat] Row parse error: %s", exc)

    return listings


async def _scrape_pages(page: Page) -> list[dict]:
    seen_urls: set[str] = set()
    all_results: list[dict] = []

    for page_num in range(1, MAX_PAGES + 1):
        url = LIST_URL if page_num == 1 else f"{LIST_URL}?page={page_num}"
        try:
            await page.goto(url, wait_until="networkidle", timeout=35_000)
        except PWTimeout:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                await asyncio.sleep(4)  # Allow JS click handlers to attach
            except PWTimeout:
                await screenshot_on_failure(page, SITE, f"timeout_page_{page_num}")
                logger.warning("[transmibat] Timed out on page %d", page_num)
                break

        results = await _extract_listings(page)
        if not results:
            await screenshot_on_failure(page, SITE, f"no_results_page_{page_num}")
            logger.info("[transmibat] No results on page %d — stopping.", page_num)
            break

        new_count = 0
        for listing in results:
            if listing["url"] not in seen_urls:
                seen_urls.add(listing["url"])
                all_results.append(listing)
                new_count += 1

        logger.info("[transmibat] Page %d -> %d new results", page_num, new_count)

        if new_count == 0:
            break

        await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

    return all_results


async def _run() -> list[dict]:
    async with browser_page(SITE) as page:
        all_results = await _scrape_pages(page)

    logger.info("[transmibat] Total unique: %d", len(all_results))
    return all_results


def scrape() -> list[dict]:
    return asyncio.run(_run())
