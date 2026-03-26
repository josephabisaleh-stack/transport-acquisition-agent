"""
Playwright scraper for Fusacq.com — no login required.

Fusacq shows search results publicly. We go directly to the results URL,
dismiss the cookie consent banner if present, and extract listing cards.
"""

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PWTimeout

from browser import browser_page, screenshot_on_failure
from config import SEARCH_KEYWORDS, DELAY_BETWEEN_REQUESTS

logger = logging.getLogger(__name__)

SITE        = "fusacq"
BASE_URL    = "https://www.fusacq.com"
RESULTS_URL = (
    f"{BASE_URL}/reprendre-une-entreprise/"
    "resultats-annonces-cession-entreprise_fr_"
    "?reference_mots_cles={{keyword}}"
    "&type_recherche=5&rechercher="
)


async def _dismiss_cookies(page: Page):
    """Dismiss the Cookiebot consent banner if it appears."""
    try:
        await page.click('button:has-text("Tout autoriser")', timeout=4_000)
        logger.debug("[fusacq] Cookie banner dismissed.")
    except PWTimeout:
        pass  # Banner already gone or not shown


async def _extract_listings(page: Page) -> list[dict]:
    """Parse listing cards on the current results page.

    Card structure (as observed):
      div.card.no_shadow.card-ie.filet_gris
        h5.titre_annonce > a[href, title]   ← title attr has the clean title
        span / strong with CA info
    Links with href="#" are elite/paywalled — skip them, they have no detail page.
    Real detail links follow /vente-entreprise-..._fr_ pattern.
    """
    listings = []
    cards = await page.query_selector_all("div.card-ie, div.card.no_shadow")
    for card in cards:
        try:
            link_el = await card.query_selector("h5.titre_annonce a, .titre_annonce a")
            if not link_el:
                continue
            href  = (await link_el.get_attribute("href") or "").strip()
            title = (await link_el.get_attribute("title") or "").strip()
            if not title:
                title = (await link_el.inner_text()).strip()
            # Skip paywalled elite listings (href="#")
            if not href or href == "#":
                continue
            # Clean query-string navigation params — keep only the path
            url = (href if href.startswith("http") else BASE_URL + href).split("?")[0]

            ca_el  = await card.query_selector("strong")
            loc_el = await card.query_selector(".localisation, [class*='loc'], .region, .ville")

            listings.append({
                "source":      "Fusacq",
                "title":       title,
                "url":         url,
                "description": "",
                "price":       (await ca_el.inner_text()).strip() if ca_el else "N/C",
                "location":    (await loc_el.inner_text()).strip() if loc_el else "N/C",
            })
        except Exception as exc:
            logger.debug("[fusacq] Card parse error: %s", exc)
    return listings


async def _search(page: Page, keyword: str) -> list[dict]:
    url = RESULTS_URL.replace("{{keyword}}", keyword.replace(" ", "+"))
    try:
        await page.goto(url, wait_until="networkidle", timeout=25_000)
    except PWTimeout:
        await screenshot_on_failure(page, SITE, f"search_{keyword[:20]}")
        logger.warning("[fusacq] Page timed out for '%s'", keyword)
        return []

    await _dismiss_cookies(page)

    # Wait for listing content to render
    try:
        await page.wait_for_selector(
            ".annonce-card, .annonce, article, a[href*='/annonce-']",
            timeout=8_000,
        )
    except PWTimeout:
        pass

    results = await _extract_listings(page)
    logger.info("[fusacq] '%s' -> %d results", keyword, len(results))
    return results


async def _run() -> list[dict]:
    seen_urls: set[str] = set()
    all_results: list[dict] = []
    async with browser_page(SITE) as page:
        for keyword in SEARCH_KEYWORDS:
            for listing in await _search(page, keyword):
                if listing["url"] not in seen_urls:
                    seen_urls.add(listing["url"])
                    all_results.append(listing)
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
    logger.info("[fusacq] Total unique: %d", len(all_results))
    return all_results


def scrape() -> list[dict]:
    """Synchronous entry point called by main.py."""
    return asyncio.run(_run())
