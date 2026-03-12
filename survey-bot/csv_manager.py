"""
csv_manager.py — Load and serve persona rows from a CSV file.

CSV must have columns: name, email, phone
Each run consumes exactly one row (by run_index).
When the index exceeds available rows, get_row() returns None → stop signal.
"""

from pathlib import Path

import pandas as pd


class CSVManager:
    def __init__(self):
        self._df: pd.DataFrame | None = None
        self._filepath: str | None = None

    # ------------------------------------------------------------------
    def load(self, filepath: str) -> int:
        """
        Load CSV from *filepath* into memory.
        Returns total row count.
        Raises ValueError if required columns are missing.
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {filepath}")
        df = pd.read_csv(path, dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        ok, msg = self._check_columns(df, ["name", "email", "phone"])
        if not ok:
            raise ValueError(f"CSV validation failed — {msg}")
        # Drop fully-empty rows
        df = df.dropna(subset=["name", "email", "phone"]).reset_index(drop=True)
        self._df = df
        self._filepath = str(filepath)
        return len(df)

    # ------------------------------------------------------------------
    def get_row(self, run_index: int) -> dict | None:
        """
        Return the persona row for *run_index* (0-based) as a dict.
        Returns None when the index is out of range (CSV exhausted).
        """
        if self._df is None or run_index >= len(self._df):
            return None
        row = self._df.iloc[run_index]
        return {
            "name": str(row.get("name", "")).strip(),
            "email": str(row.get("email", "")).strip(),
            "phone": str(row.get("phone", "")).strip(),
        }

    # ------------------------------------------------------------------
    def validate(self, required_columns: list[str]) -> tuple[bool, str]:
        """
        Check that a loaded DataFrame has the required columns.
        Returns (True, "") on success, or (False, "missing: X, Y") on failure.
        """
        if self._df is None:
            return False, "No CSV loaded"
        return self._check_columns(self._df, required_columns)

    def preview(self, n: int = 5) -> list[dict]:
        """Return first *n* rows as a list of dicts."""
        if self._df is None:
            return []
        return self._df.head(n).to_dict(orient="records")

    def total_rows(self) -> int:
        """Return number of available persona rows (0 if not loaded)."""
        if self._df is None:
            return 0
        return len(self._df)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    @staticmethod
    def _check_columns(df: pd.DataFrame, required: list[str]) -> tuple[bool, str]:
        missing = [c for c in required if c not in df.columns]
        if missing:
            return False, f"missing columns: {', '.join(missing)}"
        return True, ""
