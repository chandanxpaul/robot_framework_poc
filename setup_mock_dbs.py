#!/usr/bin/env python3
"""Create source.db and target.db with intentional ETL discrepancies for testing."""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
SOURCE_DB = DB_DIR / "source.db"
TARGET_DB = DB_DIR / "target.db"

NUM_RECORDS = 200
RANDOM_SEED = 42

CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    registration_date TEXT NOT NULL,
    status TEXT NOT NULL
);
"""

STATUSES = ["active", "inactive", "pending", "suspended"]
FIRST_NAMES = [
    "Alice", "Bob", "Carol", "David", "Eve", "Frank", "Grace", "Henry",
    "Ivy", "Jack", "Karen", "Leo", "Mia", "Noah", "Olivia", "Paul",
    "Quinn", "Rachel", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xavier",
    "Yara", "Zane",
]
LAST_NAMES = [
    "Anderson", "Brown", "Clark", "Davis", "Edwards", "Foster", "Garcia",
    "Harris", "Ivanov", "Jones", "Kim", "Lopez", "Miller", "Nguyen",
    "Owens", "Patel", "Quinn", "Roberts", "Singh", "Taylor", "Underwood",
    "Vargas", "Wilson", "Xu", "Young", "Zhang",
]


def generate_users(n: int) -> list[tuple]:
    """Generate n deterministic mock user rows."""
    rng = random.Random(RANDOM_SEED)
    rows = []
    for user_id in range(1, n + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{user_id}@example.com"
        year = rng.randint(2018, 2025)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        registration_date = f"{year:04d}-{month:02d}-{day:02d}"
        status = rng.choice(STATUSES)
        rows.append((user_id, name, email, registration_date, status))
    return rows


def create_database(db_path: Path, rows: list[tuple]) -> None:
    """Create (or recreate) a SQLite DB and load the users table."""
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(CREATE_USERS_SQL)
        cur.executemany(
            "INSERT INTO users (id, name, email, registration_date, status) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def introduce_etl_failures(db_path: Path) -> dict:
    """Inject intentional discrepancies into target.db."""
    rng = random.Random(RANDOM_SEED)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users ORDER BY id")
        all_ids = [row[0] for row in cur.fetchall()]

        # 1. Completeness: delete 4 random rows
        deleted_ids = sorted(rng.sample(all_ids, 4))
        cur.executemany("DELETE FROM users WHERE id = ?", [(i,) for i in deleted_ids])

        remaining_ids = [i for i in all_ids if i not in deleted_ids]

        # 2. Integrity: set email to NULL for 7 random remaining rows
        null_email_ids = sorted(rng.sample(remaining_ids, 7))
        cur.executemany(
            "UPDATE users SET email = NULL WHERE id = ?",
            [(i,) for i in null_email_ids],
        )

        after_null = [i for i in remaining_ids if i not in null_email_ids]

        # 3. Reconciliation: flip status for 5 specific remaining rows
        status_change_ids = sorted(rng.sample(after_null, 5))
        for user_id in status_change_ids:
            cur.execute("SELECT status FROM users WHERE id = ?", (user_id,))
            current = cur.fetchone()[0]
            alternatives = [s for s in STATUSES if s != current]
            new_status = rng.choice(alternatives)
            cur.execute(
                "UPDATE users SET status = ? WHERE id = ?",
                (new_status, user_id),
            )

        conn.commit()
        return {
            "deleted_ids": deleted_ids,
            "null_email_ids": null_email_ids,
            "status_change_ids": status_change_ids,
        }
    finally:
        conn.close()


def main() -> None:
    rows = generate_users(NUM_RECORDS)

    print(f"Creating {SOURCE_DB.name} with {NUM_RECORDS} identical users...")
    create_database(SOURCE_DB, rows)

    print(f"Creating {TARGET_DB.name} with {NUM_RECORDS} identical users...")
    create_database(TARGET_DB, rows)

    print("Introducing intentional ETL failures in target.db...")
    failures = introduce_etl_failures(TARGET_DB)

    print("\nDone.")
    print(f"  Completeness  – deleted rows (ids): {failures['deleted_ids']}")
    print(f"  Integrity     – NULL emails (ids):  {failures['null_email_ids']}")
    print(f"  Reconciliation – status flips (ids): {failures['status_change_ids']}")
    print(f"\nDatabases written to:\n  {SOURCE_DB}\n  {TARGET_DB}")


if __name__ == "__main__":
    main()
