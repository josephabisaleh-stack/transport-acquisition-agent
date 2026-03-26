#!/usr/bin/env python3
"""
Transport Acquisition Agent — Main Orchestrator
================================================
Run manually:      python main.py
Run silently:      python main.py --quiet
Force email:       python main.py --force-email
Dry run (no DB):   python main.py --dry-run
"""

import argparse
import logging
import sys
from datetime import datetime

import db
from email_sender import send_digest
from scrapers import fusacq, cession_pme, transentreprise, alvo, bpifrance, remicom, transmibat


def setup_logging(quiet: bool):
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("agent.log"),
        ],
    )


def run(dry_run: bool = False, force_email: bool = False):
    logger = logging.getLogger("main")
    logger.info("=" * 60)
    logger.info("Agent started at %s", datetime.now().isoformat())

    # 1. Initialise database
    db.init_db()

    # 2. Scrape all sources
    all_listings: list[dict] = []
    for scraper_module in [fusacq, cession_pme, transentreprise, alvo, bpifrance, remicom, transmibat]:
        name = scraper_module.__name__.split(".")[-1]
        logger.info("Scraping %s …", name)
        try:
            results = scraper_module.scrape()
            all_listings.extend(results)
            logger.info("  %s -> %d listings", name, len(results))
        except Exception as exc:
            logger.error("  %s scraper failed: %s", name, exc)

    logger.info("Total raw listings collected: %d", len(all_listings))

    # 3. Deduplicate against database
    new_listings = db.filter_new(all_listings)
    logger.info("New listings (not seen before): %d", len(new_listings))

    # 4. Persist new listings
    if not dry_run and new_listings:
        db.mark_seen(new_listings)

    # 5. Split into keyword-matched vs all listings for two email digests
    kw_lower = [kw.lower() for kw in SEARCH_KEYWORDS]
    keyword_listings = [
        l for l in new_listings
        if any(kw in (l["title"] + " " + l.get("description", "")).lower() for kw in kw_lower)
    ]
    logger.info("Keyword-matched listings: %d", len(keyword_listings))

    # 6. Send email digests
    if not dry_run:
        send_digest(keyword_listings, force=force_email, label="Mots-clés ciblés")
        send_digest(new_listings,     force=force_email, label="Toutes les annonces")
        db.log_run(len(new_listings))
    else:
        logger.info("[DRY RUN] Keyword-matched (%d):", len(keyword_listings))
        for l in keyword_listings:
            logger.info("  • [%s] %s — %s", l["source"], l["title"], l["url"])
        logger.info("[DRY RUN] All listings (%d):", len(new_listings))
        for l in new_listings:
            logger.info("  • [%s] %s — %s", l["source"], l["title"], l["url"])

    logger.info("Agent finished. New listings: %d total, %d keyword-matched", len(new_listings), len(keyword_listings))
    return len(new_listings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transport Acquisition Agent")
    parser.add_argument("--quiet",       action="store_true", help="Suppress INFO logs")
    parser.add_argument("--dry-run",     action="store_true", help="Don't write to DB or send email")
    parser.add_argument("--force-email", action="store_true", help="Send email even with 0 new listings")
    args = parser.parse_args()

    setup_logging(args.quiet)
    run(dry_run=args.dry_run, force_email=args.force_email)
