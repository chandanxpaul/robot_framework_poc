"""Custom Robot Framework library for ETL source-vs-target DataFrame comparisons."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from robot.api import logger


class ETLCustomLib:
    """Compare query results from source.db and target.db using Pandas."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"
    ROBOT_LIBRARY_VERSION = "1.0"

    def __init__(self) -> None:
        self._base_dir = Path(__file__).resolve().parent
        self.source_db = self._base_dir / "source.db"
        self.target_db = self._base_dir / "target.db"

    def compare_source_and_target_dataframes(self, query: str) -> None:
        """Execute ``query`` against source and target DBs and assert equal results.

        Raises:
            AssertionError: When row counts, missing rows, or cell values differ.
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
            # Print so the summary appears clearly in Robot Framework logs.
            print(summary)
            logger.error(summary)
            raise AssertionError(summary)

        success_msg = (
            "SUCCESS: Source and target DataFrames match perfectly "
            f"({len(source_df)} row(s), {len(source_df.columns)} column(s))."
        )
        print(success_msg)
        logger.info(success_msg)

    def _load_dataframe(self, db_path: Path, query: str) -> pd.DataFrame:
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(query, conn)

        # Normalize for stable comparisons (NULL/NaN handling, column order).
        return df.convert_dtypes().reset_index(drop=True)

    def _find_differences(
        self, source_df: pd.DataFrame, target_df: pd.DataFrame
    ) -> dict:
        differences: dict = {}

        if list(source_df.columns) != list(target_df.columns):
            differences["column_mismatch"] = {
                "source_columns": list(source_df.columns),
                "target_columns": list(target_df.columns),
            }
            return differences

        if source_df.equals(target_df):
            return differences

        if len(source_df) != len(target_df):
            differences["row_count"] = {
                "source": len(source_df),
                "target": len(target_df),
                "delta": len(source_df) - len(target_df),
            }

        # Prefer key-based comparison when an id column is present.
        if "id" in source_df.columns:
            return self._compare_by_key(source_df, target_df, key="id", differences=differences)

        return self._compare_full_rows(source_df, target_df, differences=differences)

    def _compare_by_key(
        self,
        source_df: pd.DataFrame,
        target_df: pd.DataFrame,
        key: str,
        differences: dict,
    ) -> dict:
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

        common_ids = sorted(set(source_keyed.index) & set(target_keyed.index))
        value_mismatches = []
        for row_id in common_ids:
            src_row = source_keyed.loc[row_id]
            tgt_row = target_keyed.loc[row_id]
            # Skip ambiguous duplicate-key cases; compare only unique key rows.
            if isinstance(src_row, pd.DataFrame) or isinstance(tgt_row, pd.DataFrame):
                continue

            changed_cols = []
            for col in source_df.columns:
                src_val = src_row[col]
                tgt_val = tgt_row[col]
                if pd.isna(src_val) and pd.isna(tgt_val):
                    continue
                if pd.isna(src_val) or pd.isna(tgt_val) or src_val != tgt_val:
                    changed_cols.append(
                        {
                            "column": col,
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
        lines = ["ASSERTION FAILED: Source and target DataFrames do not match.", ""]

        if "column_mismatch" in differences:
            cols = differences["column_mismatch"]
            lines.append(f"Column mismatch:")
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
