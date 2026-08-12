"""
Family finances - FastAPI app.

Run locally with:
    uvicorn app.main:app --reload

Then open http://localhost:8000/transactions in your browser.
"""

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).parent
REPO_ROOT = APP_DIR.parent


def find_env_file(start: Path) -> Path | None:
    for folder in [start, *start.parents]:
        candidate = folder / ".env"
        if candidate.exists():
            return candidate
    return None


env_file = find_env_file(APP_DIR)
if env_file:
    load_dotenv(env_file)

DB_PATH = os.environ.get("FINANCES_DB_PATH", str(REPO_ROOT / "finances.db"))

app = FastAPI(title="Family Finances")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # lets us access columns by name, e.g. row["date"]
    return conn


@app.get("/transactions")
def list_transactions(request: Request):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            transactions.id,
            transactions.date,
            transactions.description,
            transactions.amount,
            accounts.name AS account_name,
            categories.name AS category_name
        FROM transactions
        LEFT JOIN accounts ON accounts.id = transactions.account_id
        LEFT JOIN categories ON categories.id = transactions.category_id
        ORDER BY transactions.date DESC, transactions.id DESC
        """
    ).fetchall()
    conn.close()

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {"transactions": rows},
    )


@app.get("/")
def root():
    return {"message": "Family Finances app is running. Try /transactions"}