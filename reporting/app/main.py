"""
Family finances - FastAPI app.

Run locally with:
    uvicorn app.main:app --reload

Then open http://localhost:8000/transactions in your browser.
"""

import os
import sqlite3
from contextlib import closing
from datetime import date, timedelta
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


class TransactionCategoryPayload(BaseModel):
    category_id: int | None


class CategoryPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        return value


def validate_category(
    conn: sqlite3.Connection,
    payload: CategoryPayload,
    category_id: int | None = None,
) -> None:
    if payload.parent_id is not None:
        parent_exists = conn.execute(
            "SELECT 1 FROM categories WHERE id = ?",
            (payload.parent_id,),
        ).fetchone()
        if parent_exists is None:
            raise HTTPException(status_code=400, detail="Parent category not found")

    if category_id is not None and payload.parent_id is not None:
        creates_cycle = conn.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT id FROM categories WHERE parent_id = ?
                UNION ALL
                SELECT categories.id
                FROM categories
                JOIN descendants ON categories.parent_id = descendants.id
            )
            SELECT 1
            WHERE ? = ? OR EXISTS(
                SELECT 1 FROM descendants WHERE id = ?
            )
            """,
            (category_id, category_id, payload.parent_id, payload.parent_id),
        ).fetchone()
        if creates_cycle is not None:
            raise HTTPException(
                status_code=400,
                detail="A category cannot be nested under itself or one of its children.",
            )

    duplicate = conn.execute(
        """
        SELECT 1
        FROM categories
        WHERE name = ? COLLATE NOCASE
          AND parent_id IS ?
          AND (? IS NULL OR id <> ?)
        """,
        (payload.name, payload.parent_id, category_id, category_id),
    ).fetchone()
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail="A category with this name already exists at that level.",
        )


@app.get("/transactions")
def list_transactions(request: Request, month: str | None = None):
    if month is None:
        selected_month = date.today().replace(day=1)
    else:
        try:
            year_text, month_text = month.split("-")
            if len(year_text) != 4 or len(month_text) != 2:
                raise ValueError
            selected_month = date(int(year_text), int(month_text), 1)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Month must use the YYYY-MM format.",
            ) from None

    next_month = (selected_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    previous_month = (selected_month - timedelta(days=1)).replace(day=1)

    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT
                transactions.id,
                transactions.date,
                transactions.description,
                transactions.amount,
                transactions.category_id,
                accounts.name AS account_name,
                categories.name AS category_name
            FROM transactions
            LEFT JOIN accounts ON accounts.id = transactions.account_id
            LEFT JOIN categories ON categories.id = transactions.category_id
            WHERE transactions.date >= ? AND transactions.date < ?
            ORDER BY transactions.date DESC, transactions.id DESC
            """,
            (selected_month.isoformat(), next_month.isoformat()),
        ).fetchall()
        categories = conn.execute(
            """
            SELECT
                categories.id,
                categories.name,
                parents.name AS parent_name
            FROM categories
            LEFT JOIN categories AS parents ON parents.id = categories.parent_id
            ORDER BY
                COALESCE(parents.name, categories.name) COLLATE NOCASE,
                parents.name IS NULL DESC,
                categories.name COLLATE NOCASE
            """
        ).fetchall()

    income = sum(row["amount"] for row in rows if row["amount"] > 0)
    spending = -sum(row["amount"] for row in rows if row["amount"] < 0)
    net = income - spending
    uncategorized_count = sum(row["category_id"] is None for row in rows)

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "transactions": rows,
            "categories": categories,
            "selected_month": selected_month.strftime("%Y-%m"),
            "month_label": selected_month.strftime("%B %Y"),
            "previous_month": previous_month.strftime("%Y-%m"),
            "next_month": next_month.strftime("%Y-%m"),
            "current_month": date.today().strftime("%Y-%m"),
            "income": income,
            "spending": spending,
            "net": net,
            "uncategorized_count": uncategorized_count,
        },
    )


@app.patch("/api/transactions/{transaction_id}/category")
def update_transaction_category(transaction_id: int, payload: TransactionCategoryPayload):
    with closing(get_connection()) as conn:
        with conn:
            if payload.category_id is not None:
                category_exists = conn.execute(
                    "SELECT 1 FROM categories WHERE id = ?",
                    (payload.category_id,),
                ).fetchone()
                if category_exists is None:
                    raise HTTPException(status_code=400, detail="Category not found")

            cursor = conn.execute(
                "UPDATE transactions SET category_id = ? WHERE id = ?",
                (payload.category_id, transaction_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Transaction not found")

    return {"id": transaction_id, "category_id": payload.category_id}


@app.get("/categories")
def list_categories(request: Request):
    with closing(get_connection()) as conn:
        categories = conn.execute(
            """
            SELECT
                categories.id,
                categories.name,
                categories.parent_id,
                parents.name AS parent_name,
                COUNT(DISTINCT transactions.id) AS transaction_count,
                COUNT(DISTINCT children.id) AS child_count
            FROM categories
            LEFT JOIN categories AS parents ON parents.id = categories.parent_id
            LEFT JOIN transactions ON transactions.category_id = categories.id
            LEFT JOIN categories AS children ON children.parent_id = categories.id
            GROUP BY categories.id
            ORDER BY
                COALESCE(parents.name, categories.name) COLLATE NOCASE,
                parents.name IS NULL DESC,
                categories.name COLLATE NOCASE
            """
        ).fetchall()

    return templates.TemplateResponse(
        request,
        "categories.html",
        {"categories": categories},
    )


@app.post("/api/categories", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryPayload):
    with closing(get_connection()) as conn:
        with conn:
            validate_category(conn, payload)
            cursor = conn.execute(
                "INSERT INTO categories (name, parent_id) VALUES (?, ?)",
                (payload.name, payload.parent_id),
            )
            category_id = cursor.lastrowid

    return {"id": category_id}


@app.put("/api/categories/{category_id}")
def update_category(category_id: int, payload: CategoryPayload):
    with closing(get_connection()) as conn:
        with conn:
            category_exists = conn.execute(
                "SELECT 1 FROM categories WHERE id = ?",
                (category_id,),
            ).fetchone()
            if category_exists is None:
                raise HTTPException(status_code=404, detail="Category not found")

            validate_category(conn, payload, category_id)
            conn.execute(
                "UPDATE categories SET name = ?, parent_id = ? WHERE id = ?",
                (payload.name, payload.parent_id, category_id),
            )

    return {"id": category_id}


@app.delete("/api/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int):
    with closing(get_connection()) as conn:
        with conn:
            category = conn.execute(
                """
                SELECT
                    EXISTS(SELECT 1 FROM transactions WHERE category_id = ?) AS has_transactions,
                    EXISTS(SELECT 1 FROM budgets WHERE category_id = ?) AS has_budgets,
                    EXISTS(SELECT 1 FROM category_rules WHERE category_id = ?) AS has_rules,
                    EXISTS(SELECT 1 FROM categories WHERE parent_id = ?) AS has_children
                FROM categories
                WHERE id = ?
                """,
                (category_id, category_id, category_id, category_id, category_id),
            ).fetchone()
            if category is None:
                raise HTTPException(status_code=404, detail="Category not found")
            if any(category):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This category is in use. Reassign its transactions, budgets, "
                        "rules, and child categories before deleting it."
                    ),
                )
            conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


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