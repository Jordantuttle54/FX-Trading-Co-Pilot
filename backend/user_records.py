from datetime import datetime
from typing import Any, Dict, List

from .database import get_conn


def prepare_user_columns():
    with get_conn() as conn:
        for table in ["journal", "paper_trades"]:
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "user_name" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_name TEXT NOT NULL DEFAULT 'legacy'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_user ON journal(user_name, date DESC, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_user ON paper_trades(user_name, id DESC)")
        conn.commit()


def add_user_journal(entry: dict, user_name: str) -> Dict[str, Any]:
    prepare_user_columns()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO journal (created_at, date, pair, direction, result_r, reason, lesson, user_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.utcnow().isoformat(), entry["date"], entry["pair"], entry["direction"], entry["result_r"], entry.get("reason", ""), entry.get("lesson", ""), user_name),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM journal WHERE id = ? AND user_name = ?", (cur.lastrowid, user_name)).fetchone()
        return dict(row) if row else {}


def list_user_journal(user_name: str) -> List[Dict[str, Any]]:
    prepare_user_columns()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM journal WHERE user_name = ? ORDER BY date DESC, id DESC LIMIT 500", (user_name,)).fetchall()
        return [dict(r) for r in rows]


def clear_user_journal(user_name: str):
    prepare_user_columns()
    with get_conn() as conn:
        conn.execute("DELETE FROM journal WHERE user_name = ?", (user_name,))
        conn.commit()


def add_user_paper_trade(trade: dict, user_name: str) -> Dict[str, Any]:
    prepare_user_columns()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO paper_trades
            (created_at, status, pair, direction, entry, stop_loss, target, risk_pct, risk_amount, position_units, notes, user_name)
            VALUES (?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.utcnow().isoformat(), trade["pair"], trade["direction"], trade["entry"], trade["stop_loss"], trade["target"], trade["risk_pct"], trade["risk_amount"], trade["position_units"], trade.get("notes", ""), user_name),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM paper_trades WHERE id = ? AND user_name = ?", (cur.lastrowid, user_name)).fetchone()
        return dict(row) if row else {}


def list_user_paper_trades(user_name: str) -> List[Dict[str, Any]]:
    prepare_user_columns()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM paper_trades WHERE user_name = ? ORDER BY id DESC LIMIT 500", (user_name,)).fetchall()
        return [dict(r) for r in rows]


def close_user_paper_trade(trade_id: int, close_price: float, result_r: float, user_name: str) -> Dict[str, Any]:
    prepare_user_columns()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE paper_trades
            SET status = 'CLOSED', closed_at = ?, close_price = ?, result_r = ?
            WHERE id = ? AND user_name = ?
            """,
            (datetime.utcnow().isoformat(), close_price, result_r, trade_id, user_name),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM paper_trades WHERE id = ? AND user_name = ?", (trade_id, user_name)).fetchone()
        return dict(row) if row else {}


def paper_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [r for r in rows if r.get("status") == "CLOSED"]
    wins = [r for r in closed if float(r.get("result_r") or 0) > 0]
    total_r = sum(float(r.get("result_r") or 0) for r in closed)
    estimated_pnl = sum(float(r.get("risk_amount") or 0) * float(r.get("result_r") or 0) for r in closed)
    return {
        "trades": len(rows),
        "open": len([r for r in rows if r.get("status") == "OPEN"]),
        "closed": len(closed),
        "win_rate_pct": round((len(wins) / len(closed)) * 100, 1) if closed else 0,
        "total_r": round(total_r, 2),
        "estimated_pnl": round(estimated_pnl, 2),
    }
