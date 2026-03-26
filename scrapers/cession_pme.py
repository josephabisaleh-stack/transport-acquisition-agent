"""
Playwright scraper for CessionPME.com.
Handles login, then searches for commissionnaire de transport listings.
"""

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PWTimeout

from browser import browser_page, human_type, screenshot_on_failure
from config import CREDENTIALS, SEARCH_KEYWORDS, DELAY_BETWEEN_REQUESTS

logger = logging.getLogger(__name__)

SITE       = "cession_pme"

# Keywords used to filter results — cessionpme returns broad results for any search term
_TRANSPORT_KW = [
    "transport", "transitaire", "logistique", "freight", "commissionnaire",
    "affrètement", "messagerie", "fret", "expéditeur", "shipping",
    "douane", "douanier", "camion", "camionnage",
]


def _is_transport_related(listing: dict) -> bool:
    combined = (listing["title"] + " " + listing["description"]).lower()
    return any(kw in combined for kw in _TRANSPORT_KW)
BASE_URL   = "https://www.cessionpme.com"
LOGIN_URL  = f"{BASE_URL}/connexion"
SEARCH_URL = f"{BASE_URL}/annonces"
CREDS      = CREDENTIALS[SITE]


async def _login(page: Page) -> bool:
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")

    if "connexion" not in page.url and "login" not in page.url:
        logger.info("[cession_pme] Session already active.")
        return True

    try:
        await human_type(page, 'input[name="email"], input[type="email"]', CREDS["email"])
        await human_type(page, 'input[name="password"], input[type="password"]', CREDS["password"])
        await page.click('button[type="submit"], input[type="submit"]')
        await page.wait_for_url(
            lambda url: "connexion" not in url and "login" not in url, timeout=10_000
        )
        logger.info("[cession_pme] Login successful.")
        return True
    except PWTimeout:
        await screenshot_on_failure(page, SITE, "login_failed")
        logger.error("[cession_pme] Login timed out.")
        return False


async def _extract_listings(page: Page) -> list[dict]:
    listings = []
    cards = await page.query_selector_all(
        ".annonce-item, .annonce, article, .card, .listing-card"
    )
    for card in cards:
        try:
            title_el = await card.query_selector("h2, h3, .titre, .title, a")
            link_el  = await card.query_selector("a[href]")
            desc_el  = await card.query_selector(".description, .resume, p")
            price_el = await card.query_selector(".prix, .price, [class*='prix']")
            loc_el   = await card.query_selector(".localisation, .ville, .region, [class*='loc']")
            date_el  = await card.query_selector(
                "time, [class*='date'], [class*='Date'], .date_publication, .date"
            )
            if not title_el or not link_el:
                continue
            href = await link_el.get_attribute("href") or ""
            if href.startswith("http"):
                url = href
            elif href.startswith("/"):
                url = BASE_URL + href
            else:
                url = BASE_URL + "/" + href
            listings.append({
                "source":      "Cession PME",
                "title":       (await title_el.inner_text()).strip(),
                "url":         url.strip(),
                "description": (await desc_el.inner_text()).strip()[:300] if desc_el else "",
                "price":       (await price_el.inner_text()).strip() if price_el else "N/C",
                "location":    (await loc_el.inner_text()).strip() if loc_el else "N/C",
                "date":        (await date_el.inner_text()).strip() if date_el else "N/C",
            })
        except Exception as exc:
            logger.debug("[cession_pme] Card parse error: %s", exc)
    return listings


async def _search(page: Page, keyword: str) -> list[dict]:
    try:
        await page.goto(
            f"{SEARCH_URL}?recherche={keyword}&type=cession",
            wait_until="networkidle", timeout=20_000,
        )
    except PWTimeout:
        await screenshot_on_failure(page, SITE, f"search_{keyword[:20]}")
        logger.warning("[cession_pme] Page timed out for '%s'", keyword)
        return []
    results = await _extract_listings(page)
    logger.info("[cession_pme] '%s' -> %d results", keyword, len(results))
    return results


async def _run() -> list[dict]:
    seen_urls: set[str] = set()
    all_results: list[dict] = []
    async with browser_page(SITE) as page:
        if not await _login(page):
            return []
        for keyword in SEARCH_KEYWORDS:
            for listing in await _search(page, keyword):
                if listing["url"] not in seen_urls:
                    seen_urls.add(listing["url"])
                    all_results.append(listing)
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
    logger.info("[cession_pme] Total unique (raw): %d", len(all_results))
    # Filter to transport-related listings only — site returns broad results
    filtered = [l for l in all_results if _is_transport_related(l)]
    logger.info("[cession_pme] Transport-related: %d", len(filtered))
    return filtered


def scrape() -> list[dict]:
    return asyncio.run(_run())
