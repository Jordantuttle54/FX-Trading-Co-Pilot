import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]

# Local development can use the project data folder.
# Vercel/serverless runtime should use /tmp because the deployed project folder is read-only.
DEFAULT_DB_PATH = "/tmp/fx_copilot.sqlite3" if os.getenv("VERCEL") else str(ROOT / "data" / "fx_copilot.sqlite3")
DB_PATH = Path(os.getenv("FX_COPILOT_DB_PATH", DEFAULT_DB_PATH))

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            date TEXT NOT NULL,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            result_r REAL NOT NULL,
            reason TEXT,
            lesson TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            target REAL NOT NULL,
            risk_pct REAL NOT NULL,
            risk_amount REAL NOT NULL,
            position_units REAL NOT NULL,
            notes TEXT,
            closed_at TEXT,
            close_price REAL,
            result_r REAL
        )
        """)

def add_journal(entry: dict) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO journal (created_at, date, pair, direction, result_r, reason, lesson)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                entry["date"],
                entry["pair"],
                entry["direction"],
                entry["result_r"],
                entry.get("reason", ""),
                entry.get("lesson", ""),
            ),
        )
        conn.commit()
        return get_journal_by_id(cur.lastrowid)

def get_journal_by_id(row_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM journal WHERE id = ?", (row_id,)).fetchone()
        return dict(row)

def list_journal() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM journal ORDER BY date DESC, id DESC LIMIT 500").fetchall()
        return [dict(r) for r in rows]

def clear_journal():
    with get_conn() as conn:
        conn.execute("DELETE FROM journal")
        conn.commit()

def add_paper_trade(trade: dict) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO paper_trades
            (created_at, status, pair, direction, entry, stop_loss, target, risk_pct, risk_amount, position_units, notes)
            VALUES (?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                trade["pair"],
                trade["direction"],
                trade["entry"],
                trade["stop_loss"],
                trade["target"],
                trade["risk_pct"],
                trade["risk_amount"],
                trade["position_units"],
                trade.get("notes", ""),
            ),
        )
        conn.commit()
        return get_paper_trade(cur.lastrowid)

def close_paper_trade(trade_id: int, close_price: float, result_r: float) -> Dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE paper_trades
            SET status = 'CLOSED', closed_at = ?, close_price = ?, result_r = ?
            WHERE id = ?
            """,
            (datetime.utcnow().isoformat(), close_price, result_r, trade_id),
        )
        conn.commit()
        return get_paper_trade(trade_id)

def get_paper_trade(trade_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM paper_trades WHERE id = ?", (trade_id,)).fetchone()
        return dict(row)

def list_paper_trades() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM paper_trades ORDER BY id DESC LIMIT 500").fetchall()
        return [dict(r) for r in rows]
