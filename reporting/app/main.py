"""
Family finances - FastAPI app.

Run locally with:
    uvicorn app.main:app --reload

Then open http://localhost:8000/transactions in your browser.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator

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
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class AccountPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    institution: str | None = Field(default=None, max_length=100)
    account_type: Literal["checking", "savings", "credit_card", "meal_voucher"]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        return value

    @field_validator("institution")
    @classmethod
    def normalize_institution(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


@app.get("/transactions")
def list_transactions(request: Request):
    with closing(get_connection()) as conn:
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

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {"transactions": rows},
    )


@app.get("/accounts")
def list_accounts(request: Request):
    with closing(get_connection()) as conn:
        accounts = conn.execute(
            """
            SELECT
                accounts.id,
                accounts.name,
                accounts.institution,
                accounts.account_type,
                COUNT(transactions.id) AS transaction_count,
                COALESCE(SUM(transactions.amount), 0) AS balance
            FROM accounts
            LEFT JOIN transactions ON transactions.account_id = accounts.id
            GROUP BY accounts.id
            ORDER BY accounts.name COLLATE NOCASE
            """
        ).fetchall()

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {"accounts": accounts},
    )


@app.post("/api/accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountPayload):
    with closing(get_connection()) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO accounts (name, institution, account_type)
                VALUES (?, ?, ?)
                """,
                (payload.name, payload.institution, payload.account_type),
            )
            account_id = cursor.lastrowid

    return {"id": account_id}


@app.put("/api/accounts/{account_id}")
def update_account(account_id: int, payload: AccountPayload):
    with closing(get_connection()) as conn:
        with conn:
            cursor = conn.execute(
                """
                UPDATE accounts
                SET name = ?, institution = ?, account_type = ?
                WHERE id = ?
                """,
                (payload.name, payload.institution, payload.account_type, account_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Account not found")

    return {"id": account_id}


@app.delete("/api/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int):
    with closing(get_connection()) as conn:
        with conn:
            account = conn.execute(
                """
                SELECT
                    EXISTS(SELECT 1 FROM transactions WHERE account_id = ?) AS has_transactions,
                    EXISTS(SELECT 1 FROM import_batches WHERE account_id = ?) AS has_imports
                FROM accounts
                WHERE id = ?
                """,
                (account_id, account_id, account_id),
            ).fetchone()
            if account is None:
                raise HTTPException(status_code=404, detail="Account not found")
            if account["has_transactions"] or account["has_imports"]:
                raise HTTPException(
                    status_code=409,
                    detail="This account has imported history and cannot be deleted.",
                )
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


@app.get("/")
def root():
    return RedirectResponse(url="/transactions")