"""
Shared Playwright browser manager.

Key features:
  - Persistent login sessions: cookies are saved to disk after first login,
    so subsequent runs skip the login page entirely until the session expires.
  - Human-like behaviour: random typing delays, realistic viewport, slow_mo.
  - Screenshot on failure: saves a PNG whenever something goes wrong, so you
    can inspect exactly what the browser saw.
  - Context manager: `async with browser_page(site) as page:` — browser is
    always closed cleanly even on exceptions.
"""

import asyncio
import logging
import os
import random
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from config import HEADLESS, SLOW_MO_MS, PAGE_TIMEOUT_MS, SESSION_DIR

logger = logging.getLogger(__name__)


def _session_path(site: str) -> Path:
    """Return the path for this site's persistent cookie storage."""
    p = Path(SESSION_DIR)
    p.mkdir(exist_ok=True)
    return p / f"{site}_session.json"


async def human_type(page: Page, selector: str, text: str):
    """Type text character-by-character with random delays to mimic a human."""
    await page.click(selector)
    for char in text:
        await page.keyboard.type(char, delay=random.randint(40, 140))


async def screenshot_on_failure(page: Page, site: str, step: str):
    """Save a screenshot for debugging when something goes wrong."""
    path = f"debug_{site}_{step}.png"
    try:
        await page.screenshot(path=path)
        logger.info("Screenshot saved -> %s", path)
    except Exception:
        pass


@asynccontextmanager
async def browser_page(site: str):
    """
    Async context manager that yields a logged-in Playwright Page.

    Usage:
        async with browser_page("fusacq") as page:
            await page.goto("https://www.fusacq.com/annonces")
            ...
    """
    session_file = _session_path(site)
    has_session  = session_file.exists()

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO_MS,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        ctx_kwargs = dict(
            viewport={"width": 1280, "height": 800},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"},
        )

        if has_session:
            logger.info("[%s] Restoring saved session from %s", site, session_file)
            context: BrowserContext = await browser.new_context(
                storage_state=str(session_file), **ctx_kwargs
            )
        else:
            context = await browser.new_context(**ctx_kwargs)

        context.set_default_timeout(PAGE_TIMEOUT_MS)
        page: Page = await context.new_page()

        # Hide webdriver flag — many anti-bot systems check this
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        try:
            yield page
        finally:
            # Always persist the session so next run is already logged in
            await context.storage_state(path=str(session_file))
            logger.info("[%s] Session saved -> %s", site, session_file)
            await browser.close()
