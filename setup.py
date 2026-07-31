import sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent  # folder this .py file lives in


conn = sqlite3.connect("../family-finances-data/finances.db")
with open(SCRIPT_DIR / "schema.sql") as f:
    conn.executescript(f.read())
conn.commit()
conn.close()
print("Database created!")