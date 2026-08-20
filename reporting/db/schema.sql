-- Users (just the two of you)
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Bank/card accounts
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,              -- "Chase Checking", "Amex Card"
    institution TEXT,                -- "Chase", "Amex" — used to pick the right CSV parser
    account_type TEXT NOT NULL,      -- 'checking', 'savings', 'credit_card', 'meal_voucher'
    created_at TEXT DEFAULT (datetime('now'))
);

-- Categories (self-referencing for parent/child grouping)
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,              -- "Groceries", "Rent", "Dining Out"
    parent_id INTEGER REFERENCES categories(id),  -- NULL if top-level
    UNIQUE(name, parent_id)
);

-- Transactions — the core table
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),  -- NULL until categorized
    date TEXT NOT NULL,              -- ISO format 'YYYY-MM-DD'
    amount REAL NOT NULL,            -- negative = expense, positive = income
    description TEXT NOT NULL,       -- raw text from bank CSV
    notes TEXT,                      -- optional manual note
    import_batch_id INTEGER REFERENCES import_batches(id),
    dedup_hash TEXT NOT NULL,        -- hash of (account_id, date, amount, description) to catch duplicate imports
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(dedup_hash)               -- re-importing overlapping CSVs won't double-count
);

-- Tracks each CSV upload, so you can see import history / undo a bad import
CREATE TABLE import_batches (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    filename TEXT,
    imported_by INTEGER REFERENCES users(id),
    imported_at TEXT DEFAULT (datetime('now')),
    row_count INTEGER
);

-- Monthly budgets per category
CREATE TABLE budgets (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    month TEXT NOT NULL,             -- 'YYYY-MM'
    limit_amount REAL NOT NULL,
    UNIQUE(category_id, month)
);

-- Simple rule-based auto-categorization
CREATE TABLE category_rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,           -- substring or SQL LIKE pattern, e.g. '%WHOLEFDS%'
    category_id INTEGER NOT NULL REFERENCES categories(id),
    priority INTEGER DEFAULT 0       -- higher priority rules checked first
);

CREATE INDEX idx_transactions_date ON transactions(date);
CREATE INDEX idx_transactions_account ON transactions(account_id);
CREATE INDEX idx_transactions_category ON transactions(category_id);