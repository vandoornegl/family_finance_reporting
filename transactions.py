"""
CSV importer for family-finances.

Reads a CSV from one of two known sources (meal vouchers or Belfius bank
export), normalizes it into the common `transactions` schema, and inserts
new rows while skipping anything already imported (based on dedup_hash).

Usage:
    python import_transactions.py --file path\to\export.csv --source mealvoucher --account-id 1
    python import_transactions.py --file path\to\export.csv --source bank --account-id 2
"""

import argparse
import hashlib
import os
import sqlite3
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).parent
DB_PATH = os.environ.get("FINANCES_DB_PATH", str(SCRIPT_DIR / "finances.db"))


# ---------- Adapters: raw CSV -> common shape (date, description, amount, account_id) ----------

def load_meal_vouchers(filepath: str, account_id: int) -> pd.DataFrame:
    df = pd.read_csv(filepath, sep=";")
    df = df.rename(columns={"Date": "date", "Details": "description", "Amount": "amount"})

    # "Date" includes a time component (dd/mm/yyyy hh:mm) - keep only the date part.
    df["date"] = pd.to_datetime(df["date"], dayfirst=True).dt.strftime("%Y-%m-%d")

    # "Amount" arrives as text like "-11.05 €" - strip the currency symbol/whitespace and convert to float.
    df["amount"] = (
        df["amount"].astype(str).str.replace("€", "", regex=False).str.strip().astype(float)
    )

    df["account_id"] = account_id
    return df[["date", "description", "amount", "account_id"]]


def load_bank_export(filepath: str, account_id: int) -> pd.DataFrame:
    # Belfius export: ';' separators, plain dot decimals (e.g. -2.5), dd-mm-yyyy dates.
    df = pd.read_csv(filepath, sep=";")
    df["description"] = (
        df.get("Naam tegenpartij", pd.Series(dtype=str)).fillna("")
        + " - "
        + df.get("Mededeling", pd.Series(dtype=str)).fillna("")
    ).str.strip(" -")
    df = df.rename(columns={"Boekdatum": "date", "Bedrag": "amount"})
    df["date"] = pd.to_datetime(df["date"], dayfirst=True).dt.strftime("%Y-%m-%d")
    df["account_id"] = account_id
    return df[["date", "description", "amount", "account_id"]]


ADAPTERS = {
    "mealvoucher": load_meal_vouchers,
    "bank": load_bank_export,
}


# ---------- Dedup + insert ----------

def compute_dedup_hash(row) -> str:
    raw = f"{row['account_id']}{row['date']}{row['amount']}{row['description']}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def import_csv(filepath: str, source: str, account_id: int) -> None:
    adapter = ADAPTERS[source]
    df = adapter(filepath, account_id)
    df["dedup_hash"] = df.apply(compute_dedup_hash, axis=1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO import_batches (account_id, filename, row_count) VALUES (?, ?, ?)",
        (account_id, os.path.basename(filepath), len(df)),
    )
    batch_id = cur.lastrowid

    inserted, skipped = 0, 0
    for _, row in df.iterrows():
        try:
            cur.execute(
                """
                INSERT INTO transactions
                    (account_id, date, amount, description, import_batch_id, dedup_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["account_id"],
                    row["date"],
                    row["amount"],
                    row["description"],
                    batch_id,
                    row["dedup_hash"],
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # dedup_hash already exists -> this transaction was imported before
            skipped += 1

    conn.commit()
    conn.close()

    print(f"Done. Inserted: {inserted}, skipped as duplicates: {skipped}, total rows in file: {len(df)}")


# ---------- CLI ----------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import a CSV into the family-finances database.")
    parser.add_argument("--file", required=True, help="Path to the CSV file to import")
    parser.add_argument("--source", required=True, choices=ADAPTERS.keys(), help="Which CSV format this is")
    parser.add_argument("--account-id", required=True, type=int, help="ID from the accounts table")
    args = parser.parse_args()

    import_csv(args.file, args.source, args.account_id)