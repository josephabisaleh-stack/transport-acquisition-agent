"""
Playwright scraper for Transentreprise.com (CCI-backed platform).
Also checks the RSS feed first — if available, that's always preferred
over scraping as it's faster and more stable.
"""

import asyncio
import logging
import xml.etree.ElementTree as ET

import requests

from playwright.async_api import Page, TimeoutError as PWTimeout

from browser import browser_page, human_type, screenshot_on_failure
from config import CREDENTIALS, SEARCH_KEYWORDS, DELAY_BETWEEN_REQUESTS

logger = logging.getLogger(__name__)

SITE          = "transentreprise"
BASE_URL      = "https://www.transentreprise.com"
LOGIN_URL     = f"{BASE_URL}/connexion"
SEARCH_URL    = f"{BASE_URL}/offres"
# Direct transport/logistics category — no keyword search needed
TRANSPORT_URL = f"{BASE_URL}/offres/activite/Transport-logistique-L"
CREDS         = CREDENTIALS[SITE]

# Transentreprise RSS feed candidates
RSS_URLS  = [
    f"{BASE_URL}/offres.rss",
    f"{BASE_URL}/annonces.rss",
    f"{BASE_URL}/feed.rss",
    f"{BASE_URL}/rss.xml",
]


# ── RSS fast-path ─────────────────────────────────────────────────────────────

def _fetch_rss() -> list[dict]:
    """Try to pull listings from the RSS feed (no login required)."""
    resp = None
    for rss_url in RSS_URLS:
        try:
            r = requests.get(rss_url, timeout=15, headers={"Accept-Language": "fr-FR"})
            if r.status_code == 200:
                resp = r
                logger.info("[transentreprise] RSS found at %s", rss_url)
                break
        except Exception:
            continue
    if resp is None:
        logger.info("[transentreprise] No RSS feed found, falling back to browser.")
        return []
    try:
        root = ET.fromstring(resp.content)  # type: ignore[union-attr]
        items = root.findall(".//item")
        results = []
        for item in items:
            title = (item.findtext("title") or "").strip()
            url   = (item.findtext("link")  or "").strip()
            desc  = (item.findtext("description") or "").strip()[:300]
            date  = (item.findtext("pubDate") or "").strip()
            if title and url:
                # Only keep transport-related listings
                combined = (title + " " + desc).lower()
                if any(kw in combined for kw in ["transport", "transitaire", "logistique", "freight"]):
                    results.append({
                        "source":      "Transentreprise (CCI) RSS",
                        "title":       title,
                        "url":         url,
                        "description": desc,
                        "price":       "N/C",
                        "location":    "N/C",
                        "date":        date or "N/C",
                    })
        if results:
            logger.info("[transentreprise] RSS -> %d relevant listings", len(results))
        return results
    except Exception as exc:
        logger.info("[transentreprise] RSS not available (%s), falling back to browser.", exc)
        return []


# ── Browser fallback ──────────────────────────────────────────────────────────

async def _login(page: Page) -> bool:
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")

    if "connexion" not in page.url and "login" not in page.url:
        logger.info("[transentreprise] Session already active.")
        return True

    try:
        await human_type(page, 'input[name="email"], input[type="email"]', CREDS["email"])
        await human_type(page, 'input[name="password"], input[type="password"]', CREDS["password"])
        await page.click('button[type="submit"], input[type="submit"]')
        await page.wait_for_url(
            lambda url: "connexion" not in url and "login" not in url, timeout=10_000
        )
        logger.info("[transentreprise] Login successful.")
        return True
    except PWTimeout:
        await screenshot_on_failure(page, SITE, "login_failed")
        logger.error("[transentreprise] Login timed out.")
        return False


_TRANSPORT_PATH_TERMS = [
    "transport", "logistique", "transitaire", "freight", "messagerie",
    "fret", "affrètement", "affretemement", "commissionnaire",
]


async def _extract_listings(page: Page) -> list[dict]:
    """Extract listings by finding /offres/fiche/ links that are transport-related.

    Uses page.evaluate() to collect all link data in one JS call, avoiding
    stale element references that occur when the page navigates during iteration.
    """
    try:
        links_data = await page.evaluate("""
            () => [...document.querySelectorAll("a[href*='/offres/fiche/']")]
                .map(a => ({ href: a.getAttribute('href') || '', text: a.innerText.trim() }))
        """)
    except Exception as exc:
        logger.debug("[transentreprise] evaluate failed: %s", exc)
        return []

    listings = []
    seen_hrefs: set[str] = set()

    for item in links_data:
        href = (item.get("href") or "").strip()
        if not href or href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        # Filter: only keep URLs whose path contains a transport-related term
        if not any(t in href.lower() for t in _TRANSPORT_PATH_TERMS):
            continue

        url = href if href.startswith("http") else BASE_URL + href

        # Parse business type and location from URL segments
        # e.g. /offres/fiche/ARA257824C/transport-routier/auvergne/rhone-alpes/lyon
        parts = [p for p in href.split("/") if p]
        business_type = parts[3].replace("-", " ").title() if len(parts) > 3 else ""
        location_parts = parts[5:] if len(parts) > 5 else []
        location = ", ".join(p.replace("-", " ").title() for p in location_parts)

        link_text = (item.get("text") or "").strip()
        title = link_text if link_text and len(link_text) > 3 else business_type

        listings.append({
            "source":      "Transentreprise (CCI)",
            "title":       title or business_type,
            "url":         url,
            "description": "",
            "price":       "N/C",
            "location":    location or "N/C",
            "date":        "N/C",
        })
    return listings


_SEARCH_TERMS = [
    "commissionnaire de transport",
    "transitaire",
    "transport de marchandises",
]


async def _search_one(page: Page, keyword: str) -> list[dict]:
    """Search for one keyword via the form and return matching listings."""
    try:
        await page.goto(SEARCH_URL, wait_until="networkidle", timeout=20_000)
    except PWTimeout:
        pass  # Page may still be partially loaded

    # Find the keyword input — the form is JS-rendered so we wait for it
    try:
        await page.wait_for_selector('input[type="text"], input[type="search"]', timeout=8_000)
    except PWTimeout:
        logger.debug("[transentreprise] No text inputs appeared for '%s'", keyword)
        return []

    # Identify the right text input (prefer one with a transport/activity placeholder)
    keyword_input = None
    for sel in [
        "input[placeholder*='mot']", "input[placeholder*='Activité']",
        "input[placeholder*='clé']", "input[name*='mot']",
        "input[name*='recherche']", "input[name*='keyword']",
    ]:
        try:
            el = await page.query_selector(sel)
            if el:
                keyword_input = el
                break
        except Exception:
            continue

    if keyword_input is None:
        # Fall back to the first visible text input
        inputs = await page.query_selector_all('input[type="text"]')
        keyword_input = inputs[0] if inputs else None

    if not keyword_input:
        logger.debug("[transentreprise] Could not find keyword input for '%s'", keyword)
        return []

    await keyword_input.fill("")
    await keyword_input.fill(keyword)
    # Do NOT hold keyword_input reference after fill — filling triggers live AJAX
    # which can detach the element. Use page-level selectors from here on.

    # Submit: try a visible Rechercher button first, then fall back to Enter
    try:
        await page.click(
            "button:has-text('Rechercher'), button[type='submit'], input[type='submit']",
            timeout=3_000,
        )
    except Exception:
        # Press Enter via page-level selector to avoid stale element reference
        try:
            await page.press(
                "input[type='text'], input[type='search']", "Enter", timeout=3_000
            )
        except Exception:
            pass

    try:
        await page.wait_for_load_state("networkidle", timeout=12_000)
    except PWTimeout:
        pass

    results = await _extract_listings(page)
    logger.info("[transentreprise] '%s' -> %d results", keyword, len(results))
    return results


async def _scrape_transport_category(page: Page) -> list[dict]:
    """Browse the transport/logistics category URL directly."""
    try:
        await page.goto(TRANSPORT_URL, wait_until="networkidle", timeout=25_000)
    except PWTimeout:
        await page.goto(TRANSPORT_URL, wait_until="domcontentloaded", timeout=20_000)
        await asyncio.sleep(3)

    results = await _extract_listings(page)
    logger.info("[transentreprise] Transport category -> %d results", len(results))
    return results


async def _run_browser() -> list[dict]:
    """Search transentreprise.com for transport listings."""
    seen_urls: set[str] = set()
    all_results: list[dict] = []

    async with browser_page(SITE) as page:
        if not await _login(page):
            return []

        # Try direct transport category first
        for listing in await _scrape_transport_category(page):
            if listing["url"] not in seen_urls:
                seen_urls.add(listing["url"])
                all_results.append(listing)

        await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

        # Also try keyword search
        for keyword in _SEARCH_TERMS:
            for listing in await _search_one(page, keyword):
                if listing["url"] not in seen_urls:
                    seen_urls.add(listing["url"])
                    all_results.append(listing)
            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

        if not all_results:
            await screenshot_on_failure(page, SITE, "no_results_all_keywords")
            logger.warning("[transentreprise] 0 results across all keywords — screenshot saved")

    logger.info("[transentreprise] Total unique: %d", len(all_results))
    return all_results


def scrape() -> list[dict]:
    # Try RSS first — faster, no browser needed
    rss_results = _fetch_rss()
    if rss_results:
        return rss_results
    # Fall back to authenticated browser scraping
    return asyncio.run(_run_browser())
