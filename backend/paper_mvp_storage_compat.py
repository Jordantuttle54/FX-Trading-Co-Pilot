from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from psycopg2.extras import Json
from pydantic import BaseModel, Field

from . import paper_mvp_persistent as base
from .paper_mvp_trade_status_fix import app

PAPER_TABLE = "paper_trades_agent"
AUDIT_TABLE = "agent_audit_agent"


class AgentExecuteCompatRequest(BaseModel):
    pair