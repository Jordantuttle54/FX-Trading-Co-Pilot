from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import paper_mvp_persistent as base
from .paper_mvp_persistent_execfix import app
from .paper_mvp_persistent import (
    START_BALANCE,
    current_user,
    save_trade,
    list_trades,
    storage_mode,
    now,
)


class LegacyJournalEntryIn(BaseModel):
    date: str
    pair: str
    direction: str
    result_r: float
    reason: str = ""
    lesson