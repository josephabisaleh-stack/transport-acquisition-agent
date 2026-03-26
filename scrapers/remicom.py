"""
Playwright scraper for remicom.com (Remicom — business transfer platform).

Public site — no login required. Browses the business transfer listings
category and filters for transport-related entries.

URL pattern (category-based, no keyword search):
  https://www.remicom.com/fr/liste-objets-transmission-dentreprises?page={n}
"""

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PWTimeout

from browser import browser_page, screenshot_on_failure
from config import DELAY_BETWEEN_REQUESTS

logger = logging.getLogger(__name__)

SITE       = "remicom"
BASE_URL   = "https://www.remicom.com"
# Main category for business transfers (transmission d'entreprises)
LIST_URL   = f"{BASE_URL}/fr/liste-objets-transmission-dentreprises"
MAX_PAGES  = 10  # Safety cap to avoid infinite pagination

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
            "a[href*='/fr/'], .card, article, [class*='item'], [class*='offer'], [class*='object']",
            timeout=12_000,
        )
    except PWTimeout:
        logger.debug("[remicom] No listing cards appeared within timeout.")
        return []

    cards = await page.query_selector_all(
        "a[href*='/fr/objet-'], a[href*='/fr/offre-'], "
        "[class*='object-item'], [class*='offer-item'], [class*='listing-item'], "
        "article, .card"
    )

    for card in cards:
        try:
            tag = await card.get_property("tagName")
            tag_name = (await tag.json_value()).upper()
            if tag_name == "A":
                link_el = card
            else:
                link_el = await card.query_selector("a[href]")
            if not link_el:
                continue

            href = await link_el.get_attribute("href") or ""
            if not href:
                continue
            url = href if href.startswith("http") else BASE_URL + href

            # Skip navigation/category links — real listings have longer paths
            path_tail = url.rstrip("/").rsplit("/", 1)[-1]
            if len(path_tail) < 5:
                continue

            title_el = await card.query_selector(
                "h2, h3, h4, [class*='title'], [class*='titre'], [class*='name'], strong"
            )
            desc_el  = await card.query_selector(
                "[class*='description'], [class*='resume'], [class*='activite'], "
                "[class*='sector'], p"
            )
            price_el = await card.query_selector(
                "[class*='prix'], [class*='price'], [class*='valeur'], [class*='montant'], "
                "[class*='chf'], [class*='eur']"
            )
            loc_el   = await card.query_selector(
                "[class*='region'], [class*='location'], [class*='localisation'], "
                "[class*='canton'], [class*='ville'], [class*='pays']"
            )

            title_text = (await title_el.inner_text()).strip() if title_el else ""
            if not title_text:
                title_text = (await link_el.inner_text()).strip()
            if not title_text:
                continue

            listings.append({
                "source":      "Remicom",
                "title":       title_text,
                "url":         url.strip(),
                "description": (await desc_el.inner_text()).strip()[:300] if desc_el else "",
                "price":       (await price_el.inner_text()).strip() if price_el else "N/C",
                "location":    (await loc_el.inner_text()).strip() if loc_el else "N/C",
            })
        except Exception as exc:
            logger.debug("[remicom] Card parse error: %s", exc)

    return listings


async def _scrape_pages(page: Page) -> list[dict]:
    """Paginate through all listing pages and collect results."""
    seen_urls: set[str] = set()
    all_results: list[dict] = []

    for page_num in range(1, MAX_PAGES + 1):
        url = LIST_URL if page_num == 1 else f"{LIST_URL}?page={page_num}"
        try:
            await page.goto(url, wait_until="networkidle", timeout=25_000)
        except PWTimeout:
            await screenshot_on_failure(page, SITE, f"page_{page_num}")
            logger.warning("[remicom] Timed out on page %d", page_num)
            break

        results = await _extract_listings(page)
        if not results:
            logger.info("[remicom] No results on page %d — stopping pagination.", page_num)
            break

        new_count = 0
        for listing in results:
            if listing["url"] not in seen_urls:
                seen_urls.add(listing["url"])
                all_results.append(listing)
                new_count += 1

        logger.info("[remicom] Page %d -> %d new results", page_num, new_count)

        if new_count == 0:
            break  # No new URLs found — end of listings

        await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

    return all_results


async def _run() -> list[dict]:
    async with browser_page(SITE) as page:
        all_results = await _scrape_pages(page)

    logger.info("[remicom] Total unique (raw): %d", len(all_results))
    filtered = [l for l in all_results if _is_transport_related(l)]
    logger.info("[remicom] Transport-related: %d", len(filtered))
    return filtered


def scrape() -> list[dict]:
    return asyncio.run(_run())
