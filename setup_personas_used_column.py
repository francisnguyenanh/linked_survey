#!/usr/bin/env python
"""
Script to add 'used' column to existing personas.csv file.
Run this once to prepare the file for tracking used personas.
"""

import pandas as pd
from pathlib import Path

PERSONAS_CSV = Path(__file__).parent / "survey-bot" / "data" / "personas.csv"

if not PERSONAS_CSV.exists():
    print(f"Error: {PERSONAS_CSV} not found")
    exit(1)

print(f"Loading {PERSONAS_CSV}...")
df = pd.read_csv(PERSONAS_CSV, dtype=str)

if 'used' in df.columns:
    print("✅ Column 'used' already exists in personas.csv")
    print(f"   Total rows: {len(df)}")
    print(f"   Used: {(df['used'].astype(str) == '1').sum()}")
    print(f"   Unused: {(df['used'].astype(str) == '0').sum()}")
else:
    print(f"Adding 'used' column to {len(df)} rows...")
    df['used'] = 0
    df.to_csv(PERSONAS_CSV, index=False)
    print(f"✅ Successfully added 'used' column to {PERSONAS_CSV}")
    print(f"   All {len(df)} personas marked as unused (used=0)")

# Show preview
print("\nFirst 3 rows:")
print(df.head(3).to_string())
