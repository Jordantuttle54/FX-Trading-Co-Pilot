"""
Thin compatibility layer. The actual persistence logic now lives in database.py
(SQLAlchemy-based, works with SQLite locally and Postgres in production via
DATABASE_URL). This module just re-exports the same function names so main.py
doesn't need to change.
"""

from .database import (
    add_user_journal,
    list_user_journal,
    clear_user_journal,
    add_user_paper_trade,
    list_user_paper_trades,
    close_user_paper_trade,
    paper_stats,
)


def prepare_user_columns():
    """No-op kept for backward compatibility with main.py's startup call.
    Column setup and legacy migration now happen inside database.init_db()."""
    pass
