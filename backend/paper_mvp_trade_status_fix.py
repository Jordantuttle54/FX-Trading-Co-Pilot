from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends

from . import paper_mvp_persistent as base
from .paper_mvp_finalfix import app
from .paper_mvp_persistent import (
    DAILY_LIMIT,
    WEEKLY_LIMIT,
    KILL_SWITCH,
    current_user,
    list_trades,
    manage_trades,
    snapshot,
    storage_mode,
)


def _remove_routes(path: str, methods: Optional[set[str]] = None) -> None:
    kept = []
    for route in app.router.routes:
        route_path = getattr(route, "path", None)
        route_methods = getattr(route, "methods", set()) or set()
        if route_path == path and (methods is None or route_methods.intersection(methods)):
            continue
        kept.append(route)
    app.router.routes = kept


def _migrate_trade_candidate_status() -> None:
    """Convert successfully executed legacy paper trades from trade_candidate to open.

    The scanner uses status=trade_candidate. The first execution version saved the
    candidate payload as-is, which meant the trade existed in the journal but did
    not appear in the Open Paper Trades panel and was not