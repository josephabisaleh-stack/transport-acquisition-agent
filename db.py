"""
SQLite-backed store for seen listings.
Prevents the same listing from appearing in multiple digests.
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
            CREATE TABLE IF NOT EXISTS seen_listings (
                id          TEXT PRIMARY KEY,
                source      TEXT NOT NULL,
                title       TEXT NOT NULL,
                url         TEXT NOT NULL,
                first_seen  TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS digest_log (
                run_at      TEXT NOT NULL,
                new_count   INTEGER NOT NULL
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
                "SELECT id FROM seen_listings WHERE id = ?", (lid,)
            ).fetchone()
            if row is None:
                new.append(listing)
        return new


def mark_seen(listings: list[dict]):
    """Persist new listings so they won't appear in future digests."""
    with _connect() as conn:
        now = datetime.utcnow().isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO seen_listings (id, source, title, url, first_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (make_id(l["url"]), l["source"], l["title"], l["url"], now)
                for l in listings
            ],
        )
        conn.commit()


def log_run(new_count: int):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO digest_log (run_at, new_count) VALUES (?, ?)",
            (datetime.utcnow().isoformat(), new_count),
        )
        conn.commit()
