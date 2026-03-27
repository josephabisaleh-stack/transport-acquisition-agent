"""
Playwright scraper for reprise-entreprise.bpifrance.fr.

Public site — no login required. Searches for transport-related business
transfer listings using the site's keyword search.

URL pattern:
  https://reprise-entreprise.bpifrance.fr/Annonces?motsCles={keyword}
"""

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PWTimeout

from browser import browser_page, human_type, screenshot_on_failure
from config import SEARCH_KEYWORDS, DELAY_BETWEEN_REQUESTS

logger = logging.getLogger(__name__)

SITE       = "bpifrance"
BASE_URL   = "https://reprise-entreprise.bpifrance.fr"
SEARCH_URL = f"{BASE_URL}/Annonces"

# Alternative URL params to try if the first doesn't work
_SEARCH_PARAMS = ["motsCles", "q", "search", "keywords", "keyword"]

_TRANSPORT_KW = [
    "transport", "transitaire", "logistique", "freight", "commissionnaire",
    "affrètement", "messagerie", "fret", "expéditeur", "shipping",
    "douane", "douanier", "camion", "camionnage",
]


def _is_transport_related(listing: dict) -> bool:
    combined = (listing["title"] + " " + listing["description"]).lower()
    return any(kw in combined for kw in _TRANSPORT_KW)


async def _extract_listings(page: Page) -> list[dict]:
    listings = []

    # Wait for cards to render (JS-heavy SPA)
    try:
        await page.wait_for_selector(
            "article, .annonce, .card, [class*='annonce'], [class*='card'], "
            "[class*='listing'], [class*='result'], li[class], a[href*='/Annonces/']",
            timeout=15_000,
        )
    except PWTimeout:
        logger.debug("[bpifrance] No listing cards appeared within timeout.")
        return []

    cards = await page.query_selector_all(
        "article, .annonce-item, .annonce, [class*='annonce'], [class*='card-annonce'], "
        "[class*='listing-item'], [class*='result-item'], li[class*='item'], "
        "a[href*='/Annonces/']"
    )

    for card in cards:
        try:
            title_el = await card.query_selector(
                "h2, h3, h4, [class*='title'], [class*='titre'], [class*='name'], strong, a"
            )
            link_el = await card.query_selector("a[href]")
            desc_el  = await card.query_selector(
                "[class*='description'], [class*='resume'], [class*='excerpt'], "
                "[class*='activite'], p"
            )
            price_el = await card.query_selector(
                "[class*='prix'], [class*='price'], [class*='valeur'], [class*='montant']"
            )
            loc_el   = await card.query_selector(
                "[class*='localisation'], [class*='location'], [class*='region'], "
                "[class*='departement'], [class*='ville']"
            )
            date_el  = await card.query_selector(
                "time, [class*='date'], [class*='Date'], [class*='publication'], [class*='created']"
            )

            if not title_el or not link_el:
                continue

            href = await link_el.get_attribute("href") or ""
            if not href:
                continue
            url = href if href.startswith("http") else BASE_URL + (href if href.startswith("/") else "/" + href)

            title_text = (await title_el.inner_text()).strip()
            if not title_text:
                continue

            listings.append({
                "source":      "BPI France Reprise",
                "title":       title_text,
                "url":         url.strip(),
                "description": (await desc_el.inner_text()).strip()[:300] if desc_el else "",
                "price":       (await price_el.inner_text()).strip() if price_el else "N/C",
                "location":    (await loc_el.inner_text()).strip() if loc_el else "N/C",
                "date":        (await date_el.inner_text()).strip() if date_el else "N/C",
            })
        except Exception as exc:
            logger.debug("[bpifrance] Card parse error: %s", exc)

    return listings


async def _search(page: Page, keyword: str) -> list[dict] | None:
    """Return listings, or None if the site is blocking us (403/WAF)."""
    url = f"{SEARCH_URL}?motsCles={keyword.replace(' ', '+')}"
    try:
        response = await page.goto(url, wait_until="networkidle", timeout=45_000)
    except PWTimeout:
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(4)
        except PWTimeout:
            await screenshot_on_failure(page, SITE, f"timeout_{keyword[:20]}")
            logger.warning("[bpifrance] Page timed out for '%s'", keyword)
            return []

    # CloudFront/WAF blocks GitHub Actions IPs with 403
    if response and response.status == 403:
        logger.warning("[bpifrance] 403 blocked by CDN — skipping remaining keywords.")
        return None  # Signal caller to abort

    results = await _extract_listings(page)

    if not results:
        await screenshot_on_failure(page, SITE, f"no_results_{keyword[:20]}")

    logger.info("[bpifrance] '%s' -> %d results", keyword, len(results))
    return results


async def _run() -> list[dict]:
    seen_urls: set[str] = set()
    all_results: list[dict] = []

    async with browser_page(SITE) as page:
        for keyword in SEARCH_KEYWORDS:
            result = await _search(page, keyword)
            if result is None:
                break  # Site is blocking us, no point retrying other keywords
            for listing in result:
                if listing["url"] not in seen_urls:
                    seen_urls.add(listing["url"])
                    all_results.append(listing)
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

    logger.info("[bpifrance] Total unique: %d", len(all_results))
    return all_results


def scrape() -> list[dict]:
    return asyncio.run(_run())
