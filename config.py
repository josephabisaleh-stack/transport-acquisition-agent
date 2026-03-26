"""
Configuration for the Transport Acquisition Agent.
Edit this file before running the agent locally.
In CI (GitHub Actions) all secrets are injected via environment variables —
see .github/workflows/daily_scan.yml.
"""

import os

# ── Search ─────────────────────────────────────────────────────────────────
SEARCH_KEYWORDS = [
    "commissionnaire de transport",
    "commissionnaire transport",
    "freight forwarder",
    "transitaire",
]
NAF_CODE  = "5229A"   # French NAF code for commissionnaires de transport
COUNTRIES = ["france", "suisse", "switzerland"]

# ── Site credentials ────────────────────────────────────────────────────────
# Env vars take priority (used in CI). Fallback to hardcoded values for local runs.
CREDENTIALS = {
    "fusacq": {
        "email":    os.environ.get("FUSACQ_EMAIL",    "helvetiatransmission@gmail.com"),
        "password": os.environ.get("FUSACQ_PASSWORD", "Helvetia@Fusacq_123"),
    },
    "cession_pme": {
        "email":    os.environ.get("CESSION_PME_EMAIL",    "your_email@example.com"),
        "password": os.environ.get("CESSION_PME_PASSWORD", "your_cession_pme_password"),
    },
    "transentreprise": {
        "email":    os.environ.get("TRANSENTREPRISE_EMAIL",    "your_email@example.com"),
        "password": os.environ.get("TRANSENTREPRISE_PASSWORD", "your_transentreprise_password"),
    },
    "alvo": {
        "email":    os.environ.get("ALVO_EMAIL",    "helvetiatransmission@gmail.com"),
        "password": os.environ.get("ALVO_PASSWORD", "Helvetia&123456"),
    },
}

# ── Email digest ─────────────────────────────────────────────────────────────
EMAIL_SENDER     = os.environ.get("EMAIL_SENDER",   "joseph.abisaleh@gmail.com")
EMAIL_PASSWORD   = os.environ.get("EMAIL_PASSWORD", "tmoi mzsu wyzb qjvn")
EMAIL_RECIPIENTS = [
    "helvetiatransmission@gmail.com",
]
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = "seen_listings.db"

# ── Playwright browser settings ───────────────────────────────────────────────
HEADLESS          = True    # False → watch the browser (useful for debugging)
SLOW_MO_MS        = 80      # Milliseconds between actions — mimics human speed
PAGE_TIMEOUT_MS   = 30_000  # Max time to wait for a page load (30 s)
SESSION_DIR       = ".browser_sessions"  # Where login cookies are persisted

# ── Scraping ──────────────────────────────────────────────────────────────────
DELAY_BETWEEN_REQUESTS = 2  # seconds between keyword searches
