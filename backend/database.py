"""
Persistence layer.

Local development: SQLite file under data/ (fine for one person testing on one machine).
Any hosted/serverless deployment (Vercel, Railway, etc.): set DATABASE_URL to a hosted
Postgres connection string. The app will refuse to start on Vercel without it, because
Vercel's filesystem is ephemeral and SQLite data written there can disappear between
requests or deployments without warning.

Free Postgres options that work fine for this app's size: Neon, Supabase, Railway.
"""

import os
from pathlib import Path

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    Float,
    Text,
    select,
    insert,
    update,
    delete,
    text,
)
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


def _default_sqlite_url() -> str:
    db_path = ROOT / "data" / "fx_copilot.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip() or _default_sqlite_url()
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if os.getenv("VERCEL") and IS_SQLITE:
    raise RuntimeError(
        "DATABASE_URL is not set. Running on Vercel with local SQLite will silently lose "
        "journal and paper-trade data, because Vercel's filesystem is ephemeral. Set "
        "DATABASE_URL to a hosted Postgres connection string (Neon, Supabase, Railway, etc.) "
        "before deploying."
    )

connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True, connect_args=connect_args)
metadata = MetaData()

journal = Table(
    "journal",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", Text, nullable=False),
    Column("date", Text, nullable=False),
    Column("pair", Text, nullable=False),
    Column("direction", Text, nullable=False),
    Column("result_r", Float, nullable=False),
    Column("reason", Text, nullable=False, server_default=""),
    Column("lesson", Text, nullable=False, server_default=""),
    Column("user_name", Text, nullable=False, server_default="legacy"),
)

paper_trades = Table(
    "paper_trades",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("created_at", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("pair", Text, nullable=False),
    Column("direction", Text, nullable=False),
    Column("entry", Float, nullable=False),
    Column("stop_loss", Float, nullable=False),
    Column("target", Float, nullable=False),
    Column("risk_pct", Float, nullable=False),
    Column("risk_amount", Float, nullable=False),
    Column("position_units", Float, nullable=False),
    Column("notes", Text, nullable=False, server_default=""),
    Column("closed_at", Text, nullable=True),
    Column("close_price", Float, nullable=True),
    Column("result_r", Float, nullable=True),
    Column("user_name", Text, nullable=False, server_default="legacy"),
)


def init_db():
    """Create tables if they don't exist, and migrate an old pre-user-accounts
    SQLite file (one that predates the user_name column) if we find one."""
    metadata.create_all(engine)
    if IS_SQLITE:
        _migrate_legacy_sqlite_columns()


def _migrate_legacy_sqlite_columns():
    """One-off patch for local SQLite files created before multi-user support existed."""
    with engine.begin() as conn:
        for table_name in ("journal", "paper_trades"):
            cols = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]
            if cols and "user_name" not in cols:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN user_name TEXT NOT NULL DEFAULT 'legacy'"))


def row_to_dict(row) -> dict:
    return dict(row._mapping)


# ---- Journal ----

def add_user_journal(entry: dict, user_name: str) -> dict:
    from datetime import datetime

    with engine.begin() as conn:
        result = conn.execute(
            insert(journal).values(
                created_at=datetime.utcnow().isoformat(),
                date=entry["date"],
                pair=entry["pair"],
                direction=entry["direction"],
                result_r=entry["result_r"],
                reason=entry.get("reason", ""),
                lesson=entry.get("lesson", ""),
                user_name=user_name,
            )
        )
        new_id = result.inserted_primary_key[0]
        row = conn.execute(select(journal).where(journal.c.id == new_id)).fetchone()
        return row_to_dict(row) if row else {}


def list_user_journal(user_name: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(journal)
            .where(journal.c.user_name == user_name)
            .order_by(journal.c.date.desc(), journal.c.id.desc())
            .limit(500)
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def clear_user_journal(user_name: str):
    with engine.begin() as conn:
        conn.execute(delete(journal).where(journal.c.user_name == user_name))


# ---- Paper trades ----

def add_user_paper_trade(trade: dict, user_name: str) -> dict:
    from datetime import datetime

    with engine.begin() as conn:
        result = conn.execute(
            insert(paper_trades).values(
                created_at=datetime.utcnow().isoformat(),
                status="OPEN",
                pair=trade["pair"],
                direction=trade["direction"],
                entry=trade["entry"],
                stop_loss=trade["stop_loss"],
                target=trade["target"],
                risk_pct=trade["risk_pct"],
                risk_amount=trade["risk_amount"],
                position_units=trade["position_units"],
                notes=trade.get("notes", ""),
                user_name=user_name,
            )
        )
        new_id = result.inserted_primary_key[0]
        row = conn.execute(select(paper_trades).where(paper_trades.c.id == new_id)).fetchone()
        return row_to_dict(row) if row else {}


def list_user_paper_trades(user_name: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(paper_trades)
            .where(paper_trades.c.user_name == user_name)
            .order_by(paper_trades.c.id.desc())
            .limit(500)
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def close_user_paper_trade(trade_id: int, close_price: float, result_r: float, user_name: str) -> dict:
    from datetime import datetime

    with engine.begin() as conn:
        conn.execute(
            update(paper_trades)
            .where(paper_trades.c.id == trade_id, paper_trades.c.user_name == user_name)
            .values(
                status="CLOSED",
                closed_at=datetime.utcnow().isoformat(),
                close_price=close_price,
                result_r=result_r,
            )
        )
        row = conn.execute(
            select(paper_trades).where(paper_trades.c.id == trade_id, paper_trades.c.user_name == user_name)
        ).fetchone()
        return row_to_dict(row) if row else {}


def paper_stats(rows: list[dict]) -> dict:
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
