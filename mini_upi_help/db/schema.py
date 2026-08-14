"""SQLite schema for the mandate/payment database, with seed data and reset support."""
from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "upi_help.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS mandates (
    mandate_id TEXT PRIMARY KEY,
    merchant TEXT NOT NULL,
    amount INTEGER NOT NULL,
    frequency TEXT NOT NULL,
    status TEXT NOT NULL,           -- ACTIVE, PAUSED, REVOKED
    is_pause INTEGER NOT NULL,      -- 0/1
    is_revoke INTEGER NOT NULL,
    is_unpause INTEGER NOT NULL,
    umn TEXT NOT NULL,
    upi_app TEXT NOT NULL,
    paused_until TEXT               -- DD-MM-YYYY, nullable
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    merchant TEXT NOT NULL,
    status TEXT NOT NULL,           -- SUCCESS, FAILED, PENDING
    date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_intents (
    intent_id TEXT PRIMARY KEY,
    mandate_id TEXT NOT NULL,
    action TEXT NOT NULL,           -- pause, revoke, unpause
    till_date TEXT,                 -- only for pause
    created_at TEXT NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (mandate_id) REFERENCES mandates(mandate_id)
);

CREATE TABLE IF NOT EXISTS disputes (
    dispute_id TEXT PRIMARY KEY,
    txn_id TEXT,
    mandate_id TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,           -- OPEN, RESOLVED
    evidence TEXT,                  -- JSON blob of attached evidence
    created_at TEXT NOT NULL
);
"""

SEED_MANDATES = [
    ("M001", "Spotify", 199, "Monthly", "ACTIVE", 1, 1, 0, "UMN-SECRET-001", "Google Pay", None),
    ("M002", "Netflix", 649, "Monthly", "ACTIVE", 1, 0, 0, "UMN-SECRET-002", "PhonePe", None),
    ("M003", "Netflix", 199, "Monthly", "ACTIVE", 1, 1, 0, "UMN-SECRET-003", "Google Pay", None),
    ("M004", "HomeLoan EMI", 25000, "Monthly", "ACTIVE", 0, 0, 0, "UMN-SECRET-004", "Bank Direct", None),
    ("M005", "Spotify", 119, "Monthly", "ACTIVE", 1, 1, 0, "UMN-SECRET-005", "PhonePe", None),
    ("M006", "Spotify", 179, "Monthly", "ACTIVE", 1, 1, 0, "UMN-SECRET-006", "Paytm", None),
]

SEED_TRANSACTIONS = [
    ("TXN001", 500, "Amazon", "SUCCESS", "10-07-2026"),
    ("TXN002", 1200, "Swiggy", "FAILED", "12-07-2026"),
    ("TXN003", 75, "BluSmart", "PENDING", "14-07-2026"),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(reset: bool = False):
    """Create tables. If reset=True, wipe and reseed everything from scratch."""
    conn = get_connection()
    cur = conn.cursor()

    if reset:
        cur.executescript("""
            DROP TABLE IF EXISTS mandates;
            DROP TABLE IF EXISTS transactions;
            DROP TABLE IF EXISTS pending_intents;
            DROP TABLE IF EXISTS disputes;
        """)

    cur.executescript(SCHEMA)

    cur.execute("SELECT COUNT(*) FROM mandates")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO mandates VALUES (?,?,?,?,?,?,?,?,?,?,?)", SEED_MANDATES
        )
    cur.execute("SELECT COUNT(*) FROM transactions")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO transactions VALUES (?,?,?,?,?)", SEED_TRANSACTIONS
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db(reset=True)
    print(f"Database initialized at {DB_PATH}")
    