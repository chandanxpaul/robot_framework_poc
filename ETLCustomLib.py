"""
ETLCustomLib.py — Custom Robot Framework library
================================================

If you are new to Robot Framework:
  A "library" is a Python module/class that exposes methods as keywords.
  Your .robot tests call those keywords like plain English steps.

Example in etl_test_suite.robot:

    Library    ETLCustomLib.py

    Compare Source And Target Dataframes    SELECT * FROM users ORDER BY id

How naming works:
  Python method : compare_source_and_target_dataframes
  Robot keyword : Compare Source And Target Dataframes

Robot Framework automatically converts snake_case method names into
Title Case keywords. Arguments in Python become arguments after the keyword.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

# robot.api.logger writes messages into Robot's log.html report.
# Prefer this over plain print() when you want structured log levels,
# but we also print() so the console output is easy to read while learning.
from robot.api import logger


class ETLCustomLib:
    """Compare SQL query results from source.db vs target.db using Pandas.

    Robot Framework discovers public methods on this class and turns them
    into keywords. Methods starting with '_' are private helpers and are
    NOT exposed as keywords.
    """

    # ROBOT_LIBRARY_SCOPE controls how long one library instance lives.
    #   GLOBAL  -> one instance for the whole test execution (typical)
    #   SUITE   -> one instance per suite
    #   TEST    -> new instance for every test case
    ROBOT_LIBRARY_SCOPE = "GLOBAL"
    ROBOT_LIBRARY_VERSION = "1.0"

    def __init__(self) -> None:
        # Resolve DB paths relative to THIS file so the library works even if
        # you launch `robot` from another working directory.
        self._base_dir = Path(__file__).resolve().parent
        self.source_db = self._base_dir / "source.db"
        self.target_db = self._base_dir / "target.db"

    # ------------------------------------------------------------------
    # Public keyword (called from Robot Framework)
    # ------------------------------------------------------------------
    def compare_source_and_target_dataframes(self, query: str) -> None:
        """Execute ``query`` against both databases and assert equal results.

        This becomes the Robot keyword:
            Compare Source And Target Dataframes

        Args:
            query: Any SELECT statement valid in both SQLite databases.
                   Example: ``SELECT * FROM users ORDER BY id``

        Behavior:
            - If DataFrames match  -> log a success message (test continues)
            - If they differ       -> print a clear summary and raise
              AssertionError so Robot Framework marks the test as FAIL

        Tip for beginners:
            In Robot Framework, an uncaught AssertionError in a library
            keyword is the standard way to fail a test with a message.
        """
        source_df = self._load_dataframe(self.source_db, query)
        target_df = self._load_dataframe(self.target_db, query)

        logger.info(
            f"Loaded {len(source_df)} source row(s) and {len(target_df)} target "
            f"row(s) for comparison."
        )

        differences = self._find_differences(source_df, target_df)
        if differences:
            summary = self._format_difference_summary(differences)
            # print() shows up in the terminal AND in Robot's log.
            print(summary)
            logger.error(summary)
            # Raising AssertionError = keyword FAIL = test FAIL in Robot.
            raise AssertionError(summary)

        success_msg = (
            "SUCCESS: Source and target DataFrames match perfectly "
            f"({len(source_df)} row(s), {len(source_df.columns)} column(s))."
        )
        print(success_msg)
        logger.info(success_msg)

    # ------------------------------------------------------------------
    # Private helpers (NOT available as Robot keywords)
    # ------------------------------------------------------------------
    def _load_dataframe(self, db_path: Path, query: str) -> pd.DataFrame:
        """Run ``query`` against one SQLite file and return a DataFrame."""
        if not db_path.exists():
            raise FileNotFoundError(
                f"Database not found: {db_path}. "
                "Run setup_mock_dbs.py first to generate source.db / target.db."
            )

        # sqlite3 + pandas is a common ETL validation pattern:
        # SQL fetches the slice of data, Pandas compares it.
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(query, conn)

        # convert_dtypes() improves NULL/NaN handling across pandas versions.
        # reset_index(drop=True) gives a clean 0..n index for comparisons.
        return df.convert_dtypes().reset_index(drop=True)

    def _find_differences(
        self, source_df: pd.DataFrame, target_df: pd.DataFrame
    ) -> dict:
        """Return a dict describing mismatches, or {} if the frames match.

        Comparison strategy:
          1. Column names must match.
          2. If pandas says the frames are equal -> done.
          3. If an ``id`` column exists -> key-based (row-by-row) compare.
          4. Otherwise -> full-row anti-join (rows present in only one side).
        """
        differences: dict = {}

        if list(source_df.columns) != list(target_df.columns):
            differences["column_mismatch"] = {
                "source_columns": list(source_df.columns),
                "target_columns": list(target_df.columns),
            }
            return differences

        # Fast path: identical shape, columns, and values (including order).
        if source_df.equals(target_df):
            return differences

        if len(source_df) != len(target_df):
            differences["row_count"] = {
                "source": len(source_df),
                "target": len(target_df),
                "delta": len(source_df) - len(target_df),
            }

        # For our users table, ``id`` is the natural business key.
        if "id" in source_df.columns:
            return self._compare_by_key(
                source_df, target_df, key="id", differences=differences
            )

        return self._compare_full_rows(source_df, target_df, differences=differences)

    def _compare_by_key(
        self,
        source_df: pd.DataFrame,
        target_df: pd.DataFrame,
        key: str,
        differences: dict,
    ) -> dict:
        """Compare rows that share the same key (usually ``id``).

        This is the most useful ETL report style:
          - rows missing from target (completeness)
          - rows only in target (unexpected extras)
          - same id but different column values (reconciliation / integrity)
        """
        source_keyed = source_df.set_index(key, drop=False)
        target_keyed = target_df.set_index(key, drop=False)

        source_only_ids = sorted(set(source_keyed.index) - set(target_keyed.index))
        target_only_ids = sorted(set(target_keyed.index) - set(source_keyed.index))

        if source_only_ids:
            differences["rows_only_in_source"] = (
                source_keyed.loc[source_only_ids].reset_index(drop=True)
            )
        if target_only_ids:
            differences["rows_only_in_target"] = (
                target_keyed.loc[target_only_ids].reset_index(drop=True)
            )

        # For IDs present on both sides, compare each column value.
        common_ids = sorted(set(source_keyed.index) & set(target_keyed.index))
        value_mismatches = []
        for row_id in common_ids:
            src_row = source_keyed.loc[row_id]
            tgt_row = target_keyed.loc[row_id]

            # If a key is duplicated, .loc returns a DataFrame. Skip those
            # ambiguous cases rather than guessing which row to compare.
            if isinstance(src_row, pd.DataFrame) or isinstance(tgt_row, pd.DataFrame):
                continue

            changed_cols = []
            for col in source_df.columns:
                src_val = src_row[col]
                tgt_val = tgt_row[col]

                # Treat NULL/NaN on BOTH sides as equal.
                if pd.isna(src_val) and pd.isna(tgt_val):
                    continue

                # NULL on one side only, or different concrete values => mismatch.
                if pd.isna(src_val) or pd.isna(tgt_val) or src_val != tgt_val:
                    changed_cols.append(
                        {
                            "column": col,
                            # Convert NaN to None so the Robot log shows "None"
                            # instead of a noisy pandas NA representation.
                            "source": None if pd.isna(src_val) else src_val,
                            "target": None if pd.isna(tgt_val) else tgt_val,
                        }
                    )
            if changed_cols:
                value_mismatches.append({"id": row_id, "differences": changed_cols})

        if value_mismatches:
            differences["value_mismatches"] = value_mismatches

        return differences

    def _compare_full_rows(
        self,
        source_df: pd.DataFrame,
        target_df: pd.DataFrame,
        differences: dict,
    ) -> dict:
        """Fallback compare when there is no ``id`` (or other) key column.

        Uses an anti-join style merge to find entire rows that exist on only
        one side. This is less precise than key-based comparison but still
        useful for ad-hoc queries.
        """
        src_merged = source_df.merge(target_df, how="left", indicator=True)
        tgt_merged = target_df.merge(source_df, how="left", indicator=True)

        only_source = src_merged[src_merged["_merge"] == "left_only"].drop(
            columns=["_merge"]
        )
        only_target = tgt_merged[tgt_merged["_merge"] == "left_only"].drop(
            columns=["_merge"]
        )

        if not only_source.empty:
            differences["rows_only_in_source"] = only_source.reset_index(drop=True)
        if not only_target.empty:
            differences["rows_only_in_target"] = only_target.reset_index(drop=True)

        return differences

    def _format_difference_summary(self, differences: dict) -> str:
        """Build the multi-line failure message shown in Robot's log/report."""
        lines = ["ASSERTION FAILED: Source and target DataFrames do not match.", ""]

        if "column_mismatch" in differences:
            cols = differences["column_mismatch"]
            lines.append("Column mismatch:")
            lines.append(f"  Source columns: {cols['source_columns']}")
            lines.append(f"  Target columns: {cols['target_columns']}")
            lines.append("")

        if "row_count" in differences:
            counts = differences["row_count"]
            lines.append(
                f"Row count mismatch: source={counts['source']}, "
                f"target={counts['target']} (delta={counts['delta']:+d})"
            )
            lines.append("")

        if "rows_only_in_source" in differences:
            df = differences["rows_only_in_source"]
            lines.append(f"Rows only in SOURCE ({len(df)}):")
            lines.append(df.to_string(index=False))
            lines.append("")

        if "rows_only_in_target" in differences:
            df = differences["rows_only_in_target"]
            lines.append(f"Rows only in TARGET ({len(df)}):")
            lines.append(df.to_string(index=False))
            lines.append("")

        if "value_mismatches" in differences:
            mismatches = differences["value_mismatches"]
            lines.append(f"Value mismatches ({len(mismatches)} row(s)):")
            for item in mismatches:
                lines.append(f"  id={item['id']}")
                for diff in item["differences"]:
                    lines.append(
                        f"    - {diff['column']}: "
                        f"source={diff['source']!r} | target={diff['target']!r}"
                    )
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
