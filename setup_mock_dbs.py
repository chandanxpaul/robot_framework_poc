#!/usr/bin/env python3
"""
setup_mock_dbs.py
=================
Creates two local SQLite databases used by the Robot Framework ETL tests:

  - source.db  -> represents the upstream / source system
  - target.db  -> represents the warehouse / target system after ETL

Both start with the SAME mock ``users`` rows. We then deliberately
corrupt ``target.db`` so the Robot tests can demonstrate real ETL failures:

  1. Completeness   - delete N rows from target
  2. Integrity      - set email = NULL on M target rows
  3. Reconciliation - change status on K target rows

Record counts and defect counts are configurable via CLI flags (or by
editing the DEFAULT_* constants below).

Examples:

    # Defaults: 200 records, 4 deletes, 7 NULL emails, 5 status flips
    python setup_mock_dbs.py

    # Custom scale
    python setup_mock_dbs.py --records 500 --delete-rows 10 --null-emails 15 --status-changes 8

    # Clean target (no intentional defects) — useful to see tests PASS
    python setup_mock_dbs.py --records 200 --delete-rows 0 --null-emails 0 --status-changes 0

    # Show all options
    python setup_mock_dbs.py --help
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths & default configuration
# ---------------------------------------------------------------------------
# Path(__file__) is this script's location. resolve().parent is the project
# folder, so the .db files are always created next to this script.
DB_DIR = Path(__file__).resolve().parent
SOURCE_DB = DB_DIR / "source.db"
TARGET_DB = DB_DIR / "target.db"

# Defaults used when you run the script with no CLI flags.
# Change these if you want different "out of the box" behavior.
DEFAULT_NUM_RECORDS = 200
DEFAULT_DELETE_ROWS = 4       # Completeness defects
DEFAULT_NULL_EMAILS = 7       # Integrity defects
DEFAULT_STATUS_CHANGES = 5    # Reconciliation defects

# Fixed seed => every run with the same settings produces the SAME defect IDs.
# That makes the Robot test failures predictable and easier to explain.
DEFAULT_RANDOM_SEED = 42

# Schema used in BOTH databases. email is nullable on purpose so we can
# inject NULL values for the integrity test without fighting a NOT NULL rule.
CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    registration_date TEXT NOT NULL,
    status TEXT NOT NULL
);
"""

# Keep status vocabulary realistic for demo data.
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI options for record volume and intentional defect counts."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate source.db and target.db for the Robot Framework ETL POC. "
            "Defect counts control how many intentional ETL failures are injected "
            "into target.db only."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-n",
        "--records",
        type=int,
        default=DEFAULT_NUM_RECORDS,
        metavar="N",
        help="Number of identical mock users to insert into both databases.",
    )
    parser.add_argument(
        "--delete-rows",
        type=int,
        default=DEFAULT_DELETE_ROWS,
        metavar="N",
        help="Completeness defects: rows to delete from target.db.",
    )
    parser.add_argument(
        "--null-emails",
        type=int,
        default=DEFAULT_NULL_EMAILS,
        metavar="N",
        help="Integrity defects: target rows whose email is set to NULL.",
    )
    parser.add_argument(
        "--status-changes",
        type=int,
        default=DEFAULT_STATUS_CHANGES,
        metavar="N",
        help="Reconciliation defects: target rows whose status is flipped.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        metavar="N",
        help="RNG seed for reproducible mock data and defect IDs.",
    )
    return parser.parse_args(argv)


def validate_config(
    records: int,
    delete_rows: int,
    null_emails: int,
    status_changes: int,
) -> None:
    """Ensure requested volumes are possible with non-overlapping defect rows.

    Defect types intentionally use distinct row IDs so each Robot test maps
    cleanly to one failure mode. Therefore:

        delete_rows + null_emails + status_changes  <=  records
    """
    counts = {
        "--records": records,
        "--delete-rows": delete_rows,
        "--null-emails": null_emails,
        "--status-changes": status_changes,
    }
    for name, value in counts.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0 (got {value}).")

    if records == 0:
        raise ValueError("--records must be >= 1 so the tables are not empty.")

    required = delete_rows + null_emails + status_changes
    if required > records:
        raise ValueError(
            f"Not enough rows for non-overlapping defects: "
            f"delete-rows ({delete_rows}) + null-emails ({null_emails}) + "
            f"status-changes ({status_changes}) = {required}, but "
            f"--records is only {records}. Increase --records or lower "
            f"the defect counts."
        )


def generate_users(n: int, seed: int) -> list[tuple]:
    """Generate ``n`` deterministic mock user rows.

    Returns a list of tuples shaped like:
        (id, name, email, registration_date, status)

    Using a seeded RNG means source.db and target.db always start identical.
    """
    rng = random.Random(seed)
    rows = []
    for user_id in range(1, n + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        name = f"{first} {last}"
        # Include user_id in the email so every address is unique.
        email = f"{first.lower()}.{last.lower()}{user_id}@example.com"
        year = rng.randint(2018, 2025)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)  # stay within valid calendar days simply
        registration_date = f"{year:04d}-{month:02d}-{day:02d}"
        status = rng.choice(STATUSES)
        rows.append((user_id, name, email, registration_date, status))
    return rows


def create_database(db_path: Path, rows: list[tuple]) -> None:
    """Create (or recreate) a SQLite DB and load the ``users`` table.

    If the file already exists we delete it first so each run starts clean.
    That avoids leftover rows from previous experiments confusing the tests.
    """
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(CREATE_USERS_SQL)
        # executemany is much faster than inserting one row at a time.
        cur.executemany(
            "INSERT INTO users (id, name, email, registration_date, status) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        # Always close the connection, even if something above fails.
        conn.close()


def introduce_etl_failures(
    db_path: Path,
    *,
    delete_rows: int,
    null_emails: int,
    status_changes: int,
    seed: int,
) -> dict:
    """Inject intentional discrepancies into ``target.db`` only.

    These defects are what make the three Robot Framework test cases FAIL
    (which is the desired outcome for this POC demo).

    Set any defect count to 0 to skip that failure type.

    Returns a dict of affected IDs so the script can print a clear summary.
    """
    # Same seed as generate_users, but this is a separate RNG stream used only
    # for picking which rows to corrupt.
    rng = random.Random(seed)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users ORDER BY id")
        all_ids = [row[0] for row in cur.fetchall()]

        deleted_ids: list[int] = []
        null_email_ids: list[int] = []
        status_change_ids: list[int] = []

        # ------------------------------------------------------------------
        # 1) Completeness failure — delete rows from target
        #    Robot test: "ETL Completeness Check" compares row counts.
        # ------------------------------------------------------------------
        if delete_rows > 0:
            deleted_ids = sorted(rng.sample(all_ids, delete_rows))
            cur.executemany(
                "DELETE FROM users WHERE id = ?",
                [(i,) for i in deleted_ids],
            )

        remaining_ids = [i for i in all_ids if i not in deleted_ids]

        # ------------------------------------------------------------------
        # 2) Integrity failure — set email to NULL
        #    Robot test: "Data Integrity Check" asserts COUNT(NULL emails) = 0.
        # ------------------------------------------------------------------
        if null_emails > 0:
            null_email_ids = sorted(rng.sample(remaining_ids, null_emails))
            cur.executemany(
                "UPDATE users SET email = NULL WHERE id = ?",
                [(i,) for i in null_email_ids],
            )

        # Avoid overlapping the same rows for status flips so each defect type
        # is easy to identify in the Robot log.
        after_null = [i for i in remaining_ids if i not in null_email_ids]

        # ------------------------------------------------------------------
        # 3) Reconciliation failure — flip status
        #    Robot test: "Row-by-Row Reconciliation Check" via ETLCustomLib.
        # ------------------------------------------------------------------
        if status_changes > 0:
            status_change_ids = sorted(rng.sample(after_null, status_changes))
            for user_id in status_change_ids:
                cur.execute("SELECT status FROM users WHERE id = ?", (user_id,))
                current = cur.fetchone()[0]
                # Pick a different status so the change is always a real mismatch.
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


def main(argv: list[str] | None = None) -> int:
    """Entrypoint: build identical DBs, then optionally corrupt target."""
    args = parse_args(argv)

    try:
        validate_config(
            args.records,
            args.delete_rows,
            args.null_emails,
            args.status_changes,
        )
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    rows = generate_users(args.records, args.seed)

    print(f"Creating {SOURCE_DB.name} with {args.records} identical users...")
    create_database(SOURCE_DB, rows)

    print(f"Creating {TARGET_DB.name} with {args.records} identical users...")
    create_database(TARGET_DB, rows)

    total_defects = args.delete_rows + args.null_emails + args.status_changes
    if total_defects == 0:
        print("Skipping ETL failures (--delete-rows/--null-emails/--status-changes are all 0).")
        failures = {
            "deleted_ids": [],
            "null_email_ids": [],
            "status_change_ids": [],
        }
    else:
        print(
            "Introducing intentional ETL failures in target.db "
            f"(delete={args.delete_rows}, null_emails={args.null_emails}, "
            f"status_changes={args.status_changes}, seed={args.seed})..."
        )
        failures = introduce_etl_failures(
            TARGET_DB,
            delete_rows=args.delete_rows,
            null_emails=args.null_emails,
            status_changes=args.status_changes,
            seed=args.seed,
        )

    print("\nDone.")
    print(f"  Records       – {args.records} (seed={args.seed})")
    print(f"  Completeness  – deleted rows (ids): {failures['deleted_ids'] or 'none'}")
    print(f"  Integrity     – NULL emails (ids):  {failures['null_email_ids'] or 'none'}")
    print(f"  Reconciliation – status flips (ids): {failures['status_change_ids'] or 'none'}")
    print(f"\nDatabases written to:\n  {SOURCE_DB}\n  {TARGET_DB}")
    return 0


# Standard Python pattern: only run main() when this file is executed directly
# (not when imported as a module).
if __name__ == "__main__":
    raise SystemExit(main())
