"""
agent_db.py – Database layer for the autonomous trading agent.

Extends the existing database.py with tables and queries specific to the
autonomous agent: agent_trades, audit_log, management_actions,
scan_results, and strategy_versions.

Every decision, trade, rejection and rule check is stored here
so the system is fully auditable (spec §4 and §16).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    Integer, Float, Text, Boolean,
    select, insert, update, delete, text,
)
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


def _default_sqlite_url() -> str:
      db_path = ROOT / "data" / "fx_copilot.sqlite3"
      db_path.parent.mkdir(parents=True, exist_ok=True)
      return f"sqlite:///{db_path}"


DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip() or _default_sqlite_url()
IS_SQLITE    = DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True, connect_args=connect_args)
metadata = MetaData()

# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

agent_trades = Table(
      "agent_trades", metadata,
      Column("id",              Integer, primary_key=True, autoincrement=True),
      Column("created_at",      Text,    nullable=False),
      Column("pair",            Text,    nullable=False),
      Column("direction",       Text,    nullable=False),
      Column("setup_type",      Text,    nullable=False),
      Column("setup_label",     Text,    nullable=False, server_default=""),
      Column("confidence",      Integer, nullable=False),
      Column("rr_estimate",     Float,   nullable=False),
      Column("entry_reason",    Text,    nullable=False, server_default=""),
      Column("entry_price",     Float,   nullable=False),
      Column("stop_loss",       Float,   nullable=False),
      Column("take_profit",     Float,   nullable=False),
      Column("stop_pips",       Float,   nullable=True),
      Column("position_units",  Float,   nullable=False),
      Column("risk_pct",        Float,   nullable=False),
      Column("risk_amount",     Float,   nullable=False),
      Column("session",         Text,    nullable=False, server_default=""),
      Column("status",          Text,    nullable=False, server_default="open"),  # open|closed|cancelled
      Column("broker_mode",     Text,    nullable=False, server_default="paper"),
      Column("broker_order_id", Text,    nullable=True),
      Column("filled_at",       Text,    nullable=True),
      Column("closed_at",       Text,    nullable=True),
      Column("close_price",     Float,   nullable=True),
      Column("close_reason",    Text,    nullable=True),  # stop|target|kill_switch|manual
      Column("result_r",        Float,   nullable=True),
      Column("pips_pnl",        Float,   nullable=True),
      Column("money_pnl",       Float,   nullable=True),
      Column("calendar_context", Text,   nullable=True),
      Column("pre_trade_notes", Text,    nullable=True),
      Column("post_trade_review", Text,  nullable=True),
      Column("quality_tag",     Text,    nullable=True),
      Column("broker_raw",      Text,    nullable=True),
)

audit_log = Table(
      "audit_log", metadata,
      Column("id",         Integer, primary_key=True, autoincrement=True),
      Column("created_at", Text,    nullable=False),
      Column("event_type", Text,    nullable=False),  # scan|rule_check|execution|rejection|management|review
      Column("pair",       Text,    nullable=True),
      Column("trade_id",   Integer, nullable=True),
      Column("decision",   Text,    nullable=False),  # allowed|blocked|executed|rejected
      Column("reason",     Text,    nullable=False, server_default=""),
      Column("details",    Text,    nullable=True),   # JSON blob
)

scan_results = Table(
      "scan_results", metadata,
      Column("id",              Integer, primary_key=True, autoincrement=True),
      Column("scanned_at",      Text,    nullable=False),
      Column("pair",            Text,    nullable=False),
      Column("direction",       Text,    nullable=False),
      Column("setup_type",      Text,    nullable=False),
      Column("confidence",      Integer, nullable=False),
      Column("rr_estimate",     Float,   nullable=False),
      Column("status",          Text,    nullable=False),
      Column("rejection_reason", Text,   nullable=True),
      Column("entry_reason",    Text,    nullable=False, server_default=""),
      Column("session",         Text,    nullable=False, server_default=""),
      Column("in_window",       Boolean, nullable=False, server_default="0"),
      Column("details",         Text,    nullable=True),
)

management_actions = Table(
      "management_actions", metadata,
      Column("id",          Integer, primary_key=True, autoincrement=True),
      Column("timestamp",   Text,    nullable=False),
      Column("trade_id",    Integer, nullable=True),
      Column("pair",        Text,    nullable=False),
      Column("action",      Text,    nullable=False),
      Column("reason",      Text,    nullable=False, server_default=""),
      Column("close_price", Float,   nullable=True),
      Column("result_r",    Float,   nullable=True),
      Column("details",     Text,    nullable=True),
)

strategy_versions = Table(
      "strategy_versions", metadata,
      Column("id",          Integer, primary_key=True, autoincrement=True),
      Column("created_at",  Text,    nullable=False),
      Column("version",     Text,    nullable=False),
      Column("description", Text,    nullable=False, server_default=""),
      Column("rules_json",  Text,    nullable=False),
      Column("approved",    Boolean, nullable=False, server_default="0"),
      Column("approved_at", Text,    nullable=True),
      Column("active",      Boolean, nullable=False, server_default="0"),
)

loss_tracker = Table(
      "loss_tracker", metadata,
      Column("id",         Integer, primary_key=True, autoincrement=True),
      Column("trade_date", Text,    nullable=False),  # YYYY-MM-DD
      Column("trade_week", Text,    nullable=False),  # YYYY-WW
      Column("loss_pct",   Float,   nullable=False),
      Column("trade_id",   Integer, nullable=True),
)


def init_agent_db():
      """Create all agent tables if they don't exist."""
      metadata.create_all(engine)


def _now() -> str:
      return datetime.now(timezone.utc).isoformat()


def _row(row) -> dict:
      return dict(row._mapping)


# ---------------------------------------------------------------------------
# Agent trades
# ---------------------------------------------------------------------------

def save_agent_trade(trade_data: Dict[str, Any]) -> int:
      """Insert a new agent trade record and return its ID."""
      with engine.begin() as conn:
                result = conn.execute(
                              insert(agent_trades).values(
                                                created_at    = _now(),
                                                pair          = trade_data.get("pair", ""),
                                                direction     = trade_data.get("direction", ""),
                                                setup_type    = trade_data.get("setup_type", ""),
                                                setup_label   = trade_data.get("setup_label", ""),
                                                confidence    = int(trade_data.get("confidence", 0)),
                                                rr_estimate   = float(trade_data.get("rr_estimate", 0)),
                                                entry_reason  = trade_data.get("entry_reason", ""),
                                                entry_price   = float(trade_data.get("entry", 0)),
                                                stop_loss     = float(trade_data.get("stop_loss", 0)),
                                                take_profit   = float(trade_data.get("take_profit", 0)),
                                                stop_pips     = float(trade_data.get("stop_pips", 0)),
                                                position_units= float(trade_data.get("position_units", 0)),
                                                risk_pct      = float(trade_data.get("risk_pct", 0.5)),
                                                risk_amount   = float(trade_data.get("risk_amount", 0)),
                                                session       = trade_data.get("session", ""),
                                                status        = "open",
                                                broker_mode   = trade_data.get("mode", "paper"),
                                                broker_order_id = trade_data.get("order_id"),
                                                filled_at     = trade_data.get("filled_at"),
                                                pre_trade_notes = trade_data.get("entry_reason", ""),
                                                broker_raw    = trade_data.get("broker_raw"),
                              )
                )
                return result.inserted_primary_key[0]


def get_open_agent_trades() -> List[Dict[str, Any]]:
      with engine.begin() as conn:
                rows = conn.execute(
                              select(agent_trades).where(agent_trades.c.status == "open")
                ).fetchall()
        return [_row(r) for r in rows]


def get_all_agent_trades(limit: int = 500) -> List[Dict[str, Any]]:
      with engine.begin() as conn:
                rows = conn.execute(
                              select(agent_trades).order_by(agent_trades.c.id.desc()).limit(limit)
                ).fetchall()
            return [_row(r) for r in rows]


def get_closed_agent_trades(limit: int = 500) -> List[Dict[str, Any]]:
      with engine.begin() as conn:
                rows = conn.execute(
                              select(agent_trades)
                              .where(agent_trades.c.status == "closed")
                              .order_by(agent_trades.c.id.desc())
                              .limit(limit)
                ).fetchall()
            return [_row(r) for r in rows]


def get_agent_trade(trade_id: int) -> Optional[Dict[str, Any]]:
      with engine.begin() as conn:
                row = conn.execute(
                              select(agent_trades).where(agent_trades.c.id == trade_id)
                ).fetchone()
            return _row(row) if row else None


def update_agent_trade_status(trade_id: int, update_data: Dict[str, Any]) -> None:
      allowed = {
          "status", "closed_at", "close_price", "close_reason",
          "result_r", "pips_pnl", "money_pnl", "post_trade_review", "quality_tag",
}
    values = {k: v for k, v in update_data.items() if k in allowed}
    if not values:
              return
          with engine.begin() as conn:
                    conn.execute(
                                  update(agent_trades).where(agent_trades.c.id == trade_id).values(**values)
                    )


def update_agent_trade_review(trade_id: int, review: str, tag: str) -> None:
      with engine.begin() as conn:
                conn.execute(
                              update(agent_trades)
                              .where(agent_trades.c.id == trade_id)
                              .values(post_trade_review=review, quality_tag=tag)
                )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def log_audit(
      event_type: str,
      decision: str,
      reason: str,
      pair: str = "",
      trade_id: Optional[int] = None,
      details: Optional[dict] = None,
) -> None:
      with engine.begin() as conn:
                conn.execute(
                              insert(audit_log).values(
                                                created_at = _now(),
                                                event_type = event_type,
                                                pair       = pair,
                                                trade_id   = trade_id,
                                                decision   = decision,
                                                reason     = reason,
                                                details    = json.dumps(details) if details else None,
                              )
                )


def get_audit_log(limit: int = 200) -> List[Dict[str, Any]]:
      with engine.begin() as conn:
                rows = conn.execute(
                              select(audit_log).order_by(audit_log.c.id.desc()).limit(limit)
                ).fetchall()
            return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Scan results
# ---------------------------------------------------------------------------

def save_scan_result(scan: Dict[str, Any]) -> None:
      with engine.begin() as conn:
                conn.execute(
                              insert(scan_results).values(
                                                scanned_at      = scan.get("scanned_at", _now()),
                                                pair            = scan.get("pair", ""),
                                                direction       = scan.get("direction", ""),
                                                setup_type      = scan.get("setup_type", ""),
                                                confidence      = int(scan.get("confidence", 0)),
                                                rr_estimate     = float(scan.get("rr_estimate", 0)),
                                                status          = scan.get("status", "no_setup"),
                                                rejection_reason= scan.get("rejection_reason"),
                                                entry_reason    = scan.get("entry_reason", ""),
                                                session         = scan.get("session", ""),
                                                in_window       = bool(scan.get("in_window", False)),
                                                details         = json.dumps({
                                                                      k: v for k, v in scan.items()
                                                                      if k not in ("scanned_at", "pair", "direction", "setup_type",
                                                                                                                    "confidence", "rr_estimate", "status",
                                                                                                                    "rejection_reason", "entry_reason", "session", "in_window")
                                                }),
                              )
                )


def get_recent_scan_results(limit: int = 100) -> List[Dict[str, Any]]:
      with engine.begin() as conn:
                rows = conn.execute(
                              select(scan_results).order_by(scan_results.c.id.desc()).limit(limit)
                ).fetchall()
            return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Management actions
# ---------------------------------------------------------------------------

def log_management_action(action: Dict[str, Any]) -> None:
      with engine.begin() as conn:
                conn.execute(
                              insert(management_actions).values(
                                                timestamp   = action.get("timestamp", _now()),
                                                trade_id    = action.get("trade_id"),
                                                pair        = action.get("pair", ""),
                                                action      = action.get("action", ""),
                                                reason      = action.get("reason", ""),
                                                close_price = action.get("close_price"),
                                                result_r    = action.get("result_r"),
                                                details     = json.dumps(action.get("broker", {})),
                              )
                )


# ---------------------------------------------------------------------------
# Loss tracker
# ---------------------------------------------------------------------------

def record_loss(trade_id: int, loss_pct: float) -> None:
      today = date.today()
    week  = today.strftime("%Y-%W")
    with engine.begin() as conn:
              conn.execute(
                            insert(loss_tracker).values(
                                              trade_date = today.isoformat(),
                                              trade_week = week,
                                              loss_pct   = loss_pct,
                                              trade_id   = trade_id,
                            )
              )


def get_daily_loss_pct() -> float:
      today = date.today().isoformat()
    with engine.begin() as conn:
              rows = conn.execute(
                            select(loss_tracker).where(loss_tracker.c.trade_date == today)
              ).fetchall()
          return sum(r.loss_pct for r in rows if r.loss_pct > 0)


def get_weekly_loss_pct() -> float:
      week = date.today().strftime("%Y-%W")
    with engine.begin() as conn:
              rows = conn.execute(
                            select(loss_tracker).where(loss_tracker.c.trade_week == week)
              ).fetchall()
          return sum(r.loss_pct for r in rows if r.loss_pct > 0)


# ---------------------------------------------------------------------------
# Strategy versions
# ---------------------------------------------------------------------------

def save_strategy_version(version: str, description: str, rules: dict) -> int:
      with engine.begin() as conn:
                result = conn.execute(
                              insert(strategy_versions).values(
                                                created_at  = _now(),
                                                version     = version,
                                                description = description,
                                                rules_json  = json.dumps(rules),
                                                approved    = False,
                                                active      = False,
                              )
                )
                return result.inserted_primary_key[0]


def get_strategy_versions() -> List[Dict[str, Any]]:
      with engine.begin() as conn:
                rows = conn.execute(
                              select(strategy_versions).order_by(strategy_versions.c.id.desc())
                ).fetchall()
            return [_row(r) for r in rows]
