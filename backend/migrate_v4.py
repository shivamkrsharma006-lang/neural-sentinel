"""
Database migration: Add V4 metadata columns to events table.
Safe to run multiple times — checks if columns exist before adding.
"""
import sqlite3
import sys
from pathlib import Path

# Check data directory first (production location), then backend directory
DB_PATH = Path(__file__).parent.parent / "data" / "neural_sentinel.db"
if not DB_PATH.exists():
    DB_PATH = Path(__file__).parent / "neural_sentinel.db"

if not DB_PATH.exists():
    print("Database not found — it will be created on next startup with the new schema.")
    sys.exit(0)

conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

# Get existing columns
cursor.execute("PRAGMA table_info(events)")
existing_cols = {row[1] for row in cursor.fetchall()}

NEW_COLUMNS = [
    ("bbox_json", "TEXT DEFAULT ''"),
    ("direction", "TEXT DEFAULT ''"),
    ("speed_estimate", "TEXT DEFAULT ''"),
    ("dominant_colors", "TEXT DEFAULT ''"),
    ("object_details", "TEXT DEFAULT '{}'"),
    ("duration_seconds", "REAL DEFAULT 0.0"),
    ("fsm_state", "TEXT DEFAULT ''"),
]

added = 0
for col_name, col_def in NEW_COLUMNS:
    if col_name not in existing_cols:
        sql = f"ALTER TABLE events ADD COLUMN {col_name} {col_def}"
        cursor.execute(sql)
        print(f"  Added column: {col_name}")
        added += 1
    else:
        print(f"  Column already exists: {col_name}")

conn.commit()
conn.close()

if added:
    print(f"\nMigration complete: {added} column(s) added.")
else:
    print("\nNo migration needed — all columns already exist.")
