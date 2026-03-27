"""
Database layer — supports both SQLite (local dev) and Postgres (production).

If the DATABASE_URL environment variable is set, uses Postgres (Supabase).
Otherwise falls back to the local SQLite file defined in config.DB_PATH.
"""
import os
import hashlib
import sqlite3
from datetime import datetime
from config import DB_PATH

# Read DATABASE_URL from env var (GitHub Actions / local) or Streamlit secrets
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    try:
        import streamlit as st
        DATABASE_URL = st.secrets.get("DATABASE_URL", "")
    except Exception:
        pass


def _is_postgres() -> bool:
    return bool(DATABASE_URL)


def _connect():
    if _is_postgres():
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)


def _ph() -> str:
    """SQL placeholder: %s for Postgres, ? for SQLite."""
    return "%s" if _is_postgres() else "?"


def _insert_prefix() -> str:
    """INSERT prefix for upsert-ignore behaviour."""
    return "INSERT" if _is_postgres() else "INSERT OR IGNORE"


def _on_conflict() -> str:
    return "ON CONFLICT DO NOTHING" if _is_postgres() else ""


def init_db():
    """Create tables and indexes if they don't exist yet."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("""
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
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_first_seen
            ON listings(first_seen DESC)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_source
            ON listings(source)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS digest_log (
                run_at    TEXT NOT NULL,
                new_count INTEGER NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def make_id(url: str) -> str:
    """Stable ID derived from the listing URL."""
    return hashlib.sha1(url.strip().encode()).hexdigest()


def filter_new(listings: list[dict]) -> list[dict]:
    """Return only listings not yet stored in the database."""
    if not listings:
        return []
    ph = _ph()
    conn = _connect()
    try:
        cur = conn.cursor()
        new = []
        for listing in listings:
            lid = make_id(listing["url"])
            cur.execute(f"SELECT id FROM listings WHERE id = {ph}", (lid,))
            if cur.fetchone() is None:
                new.append(listing)
        return new
    finally:
        conn.close()


def mark_seen(listings: list[dict]):
    """Persist new listings with full data."""
    ph = _ph()
    prefix = _insert_prefix()
    conflict = _on_conflict()
    conn = _connect()
    try:
        cur = conn.cursor()
        now = datetime.utcnow().isoformat()
        for l in listings:
            cur.execute(
                f"""{prefix} INTO listings
                   (id, source, title, url, description, price, location, scraped_date, first_seen)
                   VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                   {conflict}""",
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
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_all_listings() -> list[dict]:
    """Return all listings ordered by first_seen DESC."""
    conn = _connect()
    try:
        if _is_postgres():
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
        cur.execute("SELECT * FROM listings ORDER BY first_seen DESC")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_listing_tracking(listing_id: str, contacted: bool, interesting: bool,
                             status: str, notes: str):
    """Update the user-managed CRM fields for a single listing."""
    ph = _ph()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE listings
               SET contacted = {ph}, interesting = {ph}, status = {ph}, notes = {ph}
               WHERE id = {ph}""",
            (int(contacted), int(interesting), status, notes, listing_id),
        )
        conn.commit()
    finally:
        conn.close()


def log_run(new_count: int):
    ph = _ph()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO digest_log (run_at, new_count) VALUES ({ph}, {ph})",
            (datetime.utcnow().isoformat(), new_count),
        )
        conn.commit()
    finally:
        conn.close()
