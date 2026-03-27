"""
One-time migration: promote seen_listings to the full listings table.
Run once: python3 migrate.py
"""
import sqlite3
from config import DB_PATH
from db import init_db

with sqlite3.connect(DB_PATH) as conn:
    init_db()  # Create new listings table if not exists

    has_old = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='seen_listings'"
    ).fetchone()

    if has_old:
        rows = conn.execute("SELECT COUNT(*) FROM seen_listings").fetchone()[0]
        conn.execute("""
            INSERT OR IGNORE INTO listings (id, source, title, url, first_seen)
            SELECT id, source, title, url, first_seen FROM seen_listings
        """)
        conn.commit()
        print(f"Migrated {rows} rows from seen_listings -> listings.")
        conn.execute("DROP TABLE seen_listings")
        conn.commit()
        print("Dropped old seen_listings table.")
    else:
        print("No seen_listings table found — nothing to migrate.")

print("Migration complete.")
