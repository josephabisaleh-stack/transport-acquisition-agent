"""
SQLite-backed store for listings.
Handles deduplication, full data persistence, and CRM tracking fields.
"""
import sqlite3
import hashlib
from datetime import datetime
from config import DB_PATH


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create the database and tables if they don't exist yet."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id           TEXT PRIMARY KEY,
                source       TEXT NOT NULL,
                title        TEXT NOT NULL,
                url          TEXT NOT NULL UNIQUE,
                description  TEXT NOT NULL DEFAULT '',
                price        TEXT NOT NULL DEFAULT 'N/C',
                location     TEXT NOT NULL DEFAULT 'N/C',
                scraped_date TEXT NOT NULL DEFAULT 'N/C',
                first_seen   TEXT NOT NULL,
                contacted    INTEGER NOT NULL DEFAULT 0,
                interesting  INTEGER NOT NULL DEFAULT 0,
                status       TEXT    NOT NULL DEFAULT 'À contacter',
                notes        TEXT    NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_first_seen
            ON listings(first_seen DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_source
            ON listings(source)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS digest_log (
                run_at     TEXT NOT NULL,
                new_count  INTEGER NOT NULL
            )
        """)
        conn.commit()


def make_id(url: str) -> str:
    """Stable ID derived from the listing URL."""
    return hashlib.sha1(url.strip().encode()).hexdigest()


def filter_new(listings: list[dict]) -> list[dict]:
    """Return only listings not yet stored in the database."""
    if not listings:
        return []
    with _connect() as conn:
        new = []
        for listing in listings:
            lid = make_id(listing["url"])
            row = conn.execute(
                "SELECT id FROM listings WHERE id = ?", (lid,)
            ).fetchone()
            if row is None:
                new.append(listing)
        return new


def mark_seen(listings: list[dict]):
    """Persist new listings with full data so they won't appear in future digests."""
    with _connect() as conn:
        now = datetime.utcnow().isoformat()
        conn.executemany(
            """INSERT OR IGNORE INTO listings
               (id, source, title, url, description, price, location, scraped_date, first_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    make_id(l["url"]),
                    l["source"],
                    l["title"],
                    l["url"],
                    l.get("description", ""),
                    l.get("price", "N/C"),
                    l.get("location", "N/C"),
                    l.get("date", "N/C"),
                    now,
                )
                for l in listings
            ],
        )
        conn.commit()


def get_all_listings() -> list[dict]:
    """Return all listings ordered by first_seen DESC."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM listings ORDER BY first_seen DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def update_listing_tracking(listing_id: str, contacted: bool, interesting: bool,
                             status: str, notes: str):
    """Update the user-managed CRM fields for a single listing."""
    with _connect() as conn:
        conn.execute(
            """UPDATE listings
               SET contacted = ?, interesting = ?, status = ?, notes = ?
               WHERE id = ?""",
            (int(contacted), int(interesting), status, notes, listing_id),
        )
        conn.commit()


def log_run(new_count: int):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO digest_log (run_at, new_count) VALUES (?, ?)",
            (datetime.utcnow().isoformat(), new_count),
        )
        conn.commit()
