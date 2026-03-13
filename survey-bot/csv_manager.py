"""
csv_manager.py — Load and serve persona rows from a CSV file.

CSV must have columns: name, email, phone
Optional column: used (0/1 or False/True) to track used personas
Each run consumes exactly one unused row (by run_index).
When the index exceeds available unused rows, get_row() returns None → stop signal.
"""

from pathlib import Path

import pandas as pd


class CSVManager:
    def __init__(self):
        self._df: pd.DataFrame | None = None
        self._filepath: str | None = None
        self._unused_indices: list[int] | None = None  # Indices of unused rows in the original DF

    # ------------------------------------------------------------------
    def load(self, filepath: str) -> int:
        """
        Load CSV from *filepath* into memory.
        Returns total row count (including already-used rows).
        Raises ValueError if required columns are missing.
        
        Automatically adds 'used' column if it doesn't exist (default=0).
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
        
        # Add 'used' column if it doesn't exist
        if 'used' not in df.columns:
            df['used'] = 0
            # Save the updated CSV with the new column
            df.to_csv(path, index=False)
        
        # Convert 'used' to int (handle both string "0"/"1" and boolean True/False)
        df['used'] = df['used'].astype(str).apply(lambda x: 1 if x.lower() in ('1', 'true', 'yes') else 0)
        
        self._df = df
        self._filepath = str(filepath)
        self._update_unused_indices()
        return len(df)

    # ------------------------------------------------------------------
    def get_row(self, run_index: int) -> dict | None:
        """
        Return the persona row for *run_index* (0-based, only unused rows) as a dict.
        Returns None when the index is out of range (all unused rows exhausted).
        Also returns the internal row index for marking as used later.
        """
        if self._df is None or self._unused_indices is None or run_index >= len(self._unused_indices):
            return None
        actual_row_idx = self._unused_indices[run_index]
        row = self._df.iloc[actual_row_idx]
        return {
            "name": str(row.get("name", "")).strip(),
            "email": str(row.get("email", "")).strip(),
            "phone": str(row.get("phone", "")).strip(),
            "_row_index": actual_row_idx,  # Internal: actual row index in DataFrame
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
        """Return first *n* unused rows as a list of dicts."""
        if self._df is None or self._unused_indices is None:
            return []
        preview_list = []
        for idx in self._unused_indices[:n]:
            row = self._df.iloc[idx]
            preview_list.append({
                "name": str(row.get("name", "")).strip(),
                "email": str(row.get("email", "")).strip(),
                "phone": str(row.get("phone", "")).strip(),
            })
        return preview_list

    def total_rows(self) -> int:
        """Return total number of persona rows (0 if not loaded) - including used and unused."""
        if self._df is None:
            return 0
        return len(self._df)

    def unused_rows(self) -> int:
        """Return number of available unused persona rows."""
        if self._unused_indices is None:
            return 0
        return len(self._unused_indices)

    # ------------------------------------------------------------------
    def mark_as_used(self, row_index: int) -> bool:
        """
        Mark a row as used by its internal index.
        Updates the CSV file.
        Returns True on success, False on failure.
        """
        if self._df is None or self._filepath is None:
            return False
        if row_index < 0 or row_index >= len(self._df):
            return False
        
        try:
            self._df.at[row_index, 'used'] = 1
            self._df.to_csv(self._filepath, index=False)
            self._update_unused_indices()
            return True
        except Exception as e:
            print(f"[CSVManager] Error marking row {row_index} as used: {e}")
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _update_unused_indices(self):
        """Update the list of unused row indices based on 'used' column."""
        if self._df is None:
            self._unused_indices = None
        else:
            self._unused_indices = self._df[self._df['used'] == 0].index.tolist()

    @staticmethod
    def _check_columns(df: pd.DataFrame, required: list[str]) -> tuple[bool, str]:
        missing = [c for c in required if c not in df.columns]
        if missing:
            return False, f"missing columns: {', '.join(missing)}"
        return True, ""
