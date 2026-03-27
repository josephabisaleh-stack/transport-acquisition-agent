"""
Database layer — three backends in priority order:

1. DATABASE_URL set  → direct Postgres via psycopg2  (GitHub Actions, full IPv4/IPv6)
2. SUPABASE_URL + SUPABASE_KEY set  → Supabase REST API over HTTPS  (Streamlit Cloud, IPv4 only)
3. Neither set  → local SQLite  (offline dev)

This split exists because Streamlit Community Cloud doesn't support IPv6,
so the direct Postgres connection string (which resolves to an IPv6 address)
fails there. The REST API uses HTTPS on an IPv4 hostname instead.
"""
import os
import hashlib
import sqlite3
from datetime import datetime
from config import DB_PATH

# ── Read credentials from env vars, then Streamlit secrets ───────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

try:
    import streamlit as st
    DATABASE_URL = DATABASE_URL or st.secrets.get("DATABASE_URL", "")
    SUPABASE_URL = SUPABASE_URL or st.secrets.get("SUPABASE_URL", "")
    SUPABASE_KEY = SUPABASE_KEY or st.secrets.get("SUPABASE_KEY", "")
except Exception:
    pass


def _backend() -> str:
    # Supabase REST wins when keys are present — works from IPv4-only hosts (Streamlit Cloud)
    if SUPABASE_URL and SUPABASE_KEY:
        return "supabase"
    if DATABASE_URL:
        return "postgres"
    return "sqlite"


# ── Supabase REST helpers ─────────────────────────────────────────────────────

def _supa():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Postgres / SQLite helpers ─────────────────────────────────────────────────

def _connect():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)


def _ph() -> str:
    """SQL placeholder: %s for Postgres, ? for SQLite."""
    return "%s" if DATABASE_URL else "?"


def _insert_prefix() -> str:
    return "INSERT" if DATABASE_URL else "INSERT OR IGNORE"


def _on_conflict() -> str:
    return "ON CONFLICT DO NOTHING" if DATABASE_URL else ""


# ── Public API ────────────────────────────────────────────────────────────────

def init_db():
    """Create tables if they don't exist. Skipped for Supabase REST (tables created by Actions)."""
    if _backend() == "supabase":
        return  # Tables already exist — GitHub Actions creates them via psycopg2
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

    if _backend() == "supabase":
        ids = [make_id(l["url"]) for l in listings]
        existing = _supa().table("listings").select("id").in_("id", ids).execute()
        existing_ids = {r["id"] for r in existing.data}
        return [l for l in listings if make_id(l["url"]) not in existing_ids]

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
    if not listings:
        return

    if _backend() == "supabase":
        now = datetime.utcnow().isoformat()
        rows = [
            {
                "id":           make_id(l["url"]),
                "source":       l["source"],
                "title":        l["title"],
                "url":          l["url"],
                "description":  l.get("description", ""),
                "price":        l.get("price", "N/C"),
                "location":     l.get("location", "N/C"),
                "scraped_date": l.get("date", "N/C"),
                "first_seen":   now,
            }
            for l in listings
        ]
        _supa().table("listings").upsert(rows, on_conflict="id").execute()
        return

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
    if _backend() == "supabase":
        response = _supa().table("listings").select("*").order("first_seen", desc=True).execute()
        return response.data

    conn = _connect()
    try:
        if DATABASE_URL:
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
    if _backend() == "supabase":
        _supa().table("listings").update({
            "contacted":   int(contacted),
            "interesting": int(interesting),
            "status":      status,
            "notes":       notes,
        }).eq("id", listing_id).execute()
        return

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
    if _backend() == "supabase":
        _supa().table("digest_log").insert({
            "run_at":    datetime.utcnow().isoformat(),
            "new_count": new_count,
        }).execute()
        return

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
