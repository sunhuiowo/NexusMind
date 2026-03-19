#!/usr/bin/env python3
"""
Migration 001: Add user_id to memories table
Backfills existing memories with the owner user_id based on storage path.
Uses sqlite3 directly to avoid importing the memory_store module.
"""
import sys
import sqlite3
from pathlib import Path

def migrate_memories_table(db_path: str, user_id: str = "_default"):
    """
    Add user_id column to memories table if it doesn't exist.
    Uses direct sqlite3 connection to avoid module-level side effects.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Check if column already exists
        columns = [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
        print(f"Current columns: {columns}")

        if "user_id" in columns:
            print("user_id column already exists, skipping")
            return

        # Add the column
        conn.execute("ALTER TABLE memories ADD COLUMN user_id TEXT NOT NULL DEFAULT '_default'")
        conn.commit()
        print("Added user_id column to memories table")

        # Update all NULL/empty user_id to the target user_id
        conn.execute(f"UPDATE memories SET user_id = ? WHERE user_id IS NULL OR user_id = ''", (user_id,))
        conn.commit()
        print(f"Backfilled user_id values with: {user_id}")

if __name__ == "__main__":
    backend_root = Path(__file__).parent.parent.parent
    db_path = backend_root / "data" / "memories.db"
    user_id = sys.argv[1] if len(sys.argv) > 1 else "_default"
    migrate_memories_table(str(db_path), user_id)
    print(f"Migration complete. Existing memories assigned to user: {user_id}")