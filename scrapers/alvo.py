"""
Playwright scraper for Alvo.market (app.alvo.market/annonces/).

Login flow:
  1. Navigate to /connexion.
  2. If already redirected away from /connexion (saved session), skip login.
  3. Otherwise fill email + password and click "Se connecter".
  4. Search listings by keyword via URL query param and extract cards.

Note: Alvo is a React SPA — use networkidle / explicit waits rather than
domcontentloaded to ensure listing cards are rendered before extraction.
"""

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PWTimeout

from browser import browser_page, human_type, screenshot_on_failure
from config import CREDENTIALS, SEARCH_KEYWORDS, DELAY_BETWEEN_REQUESTS

logger = logging.getLogger(__name__)

SITE        = "alvo"
BASE_URL    = "https://app.alvo.market"
LOGIN_URL   = f"{BASE_URL}/connexion"
SEARCH_URL  = f"{BASE_URL}/annonces"
CREDS       = CREDENTIALS[SITE]


async def _login(page: Page) -> bool:
    """Attempt login. Returns True on success."""
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")

    # Already logged in? Check URL OR page content (Alvo shows "Vous êtes connecté"
    # on the /connexion page itself when a session is still active).
    if "connexion" not in page.url:
        logger.info("[alvo] Session already active, skipping login.")
        return True
    page_text = await page.inner_text("body")
    if "connecté" in page_text.lower() or "déconnecter" in page_text.lower():
        logger.info("[alvo] Session already active (detected from page content).")
        return True

    try:
        await human_type(page, 'input[type="email"], input[name="email"]', CREDS["email"])
        await human_type(page, 'input[type="password"], input[name="password"]', CREDS["password"])
        # Click "Se connecter" — try text match first, fall back to submit
        btn = await page.query_selector('button:has-text("Se connecter"), button[type="submit"]')
        if btn:
            await btn.click()
        else:
            await page.click('button[type="submit"], input[type="submit"]')
        await page.wait_for_url(lambda url: "connexion" not in url, timeout=10_000)
        logger.info("[alvo] Login successful.")
        return True
    except PWTimeout:
        await screenshot_on_failure(page, SITE, "login_failed")
        logger.error("[alvo] Login timed out — check credentials or screenshot.")
        return False


async def _extract_listings(page: Page) -> list[dict]:
    """Parse listing cards visible on the current page."""
    # Wait for at least one card to appear (SPA render)
    try:
        await page.wait_for_selector(
            "a[href*='/annonces/'], .annonce, article, [class*='card'], [class*='listing']",
            timeout=10_000,
        )
    except PWTimeout:
        logger.debug("[alvo] No listing cards appeared within timeout.")
        return []

    listings = []
    cards = await page.query_selector_all(
        "a[href*='/annonces/'], article, [class*='Card'], [class*='card'], [class*='listing-item']"
    )

    seen_hrefs: set[str] = set()
    for card in cards:
        try:
            # Resolve the link element — the card itself may be the <a>
            tag = await card.get_property("tagName")
            tag_name = (await tag.json_value()).upper()
            if tag_name == "A":
                link_el = card
            else:
                link_el = await card.query_selector("a[href*='/annonces/']")
            if not link_el:
                continue

            href = await link_el.get_attribute("href") or ""
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            url = href if href.startswith("http") else BASE_URL + href
            # Strip query params BEFORE the path-length check (query strings like
            # ?search=commissionnaire can make short nav paths appear long)
            url = url.split("?")[0].rstrip("/")

            # Exclude navigation links — real listing IDs are long random strings (>15 chars)
            path_tail = url.rsplit("/", 1)[-1]
            if len(path_tail) < 15:
                continue

            title_el = await card.query_selector(
                "h2, h3, h4, [class*='title'], [class*='titre'], [class*='name'], strong"
            )
            desc_el  = await card.query_selector(
                "[class*='description'], [class*='resume'], [class*='excerpt'], p"
            )
            price_el = await card.query_selector(
                "[class*='price'], [class*='prix'], [class*='amount'], [class*='valeur']"
            )
            loc_el   = await card.query_selector(
                "[class*='location'], [class*='localisation'], [class*='ville'], "
                "[class*='region'], [class*='city']"
            )

            title_text = (await title_el.inner_text()).strip() if title_el else ""
            if not title_text:
                # Fall back to the link's own text
                title_text = (await link_el.inner_text()).strip()
            if not title_text:
                continue

            listings.append({
                "source":      "Alvo",
                "title":       title_text,
                "url":         url.strip(),
                "description": (await desc_el.inner_text()).strip()[:300] if desc_el else "",
                "price":       (await price_el.inner_text()).strip() if price_el else "N/C",
                "location":    (await loc_el.inner_text()).strip() if loc_el else "N/C",
            })
        except Exception as exc:
            logger.debug("[alvo] Card parse error: %s", exc)

    return listings


async def _search(page: Page, keyword: str) -> list[dict]:
    """Navigate to listings filtered by keyword and extract results."""
    url = f"{SEARCH_URL}?search={keyword}"
    try:
        await page.goto(url, wait_until="networkidle", timeout=20_000)
    except PWTimeout:
        await screenshot_on_failure(page, SITE, f"search_{keyword[:20]}")
        logger.warning("[alvo] Page timed out for '%s'", keyword)
        return []

    results = await _extract_listings(page)
    logger.info("[alvo] '%s' -> %d results", keyword, len(results))
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
    logger.info("[alvo] Total unique: %d", len(all_results))
    return all_results


def scrape() -> list[dict]:
    """Synchronous entry point called by main.py."""
    return asyncio.run(_run())
