from pydantic import BaseModel, Field
from typing import Optional, List

class ScanRequest(BaseModel):
    pair: str
    direction: str
    timeframe: str = "1H"
    risk_reward: float = 2.0
    checklist: dict = Field(default_factory=dict)

class RiskRequest(BaseModel):
    account_balance: float
    risk_pct: float
    pair: str
    entry: float
    stop_loss: float
    target: float
    pip_value_per_standard_lot: float = 10.0

class JournalEntryIn(BaseModel):
    date: str
    pair: str
    direction: str
    result_r: float
    reason: str = ""
    lesson: str = ""

class PaperTradeIn(BaseModel):
    pair: str
    direction: str
    entry: float
    stop_loss: float
    target: float
    risk_pct: float
    risk_amount: float
    position_units: float
    notes: str = ""

class AutomationReadinessIn(BaseModel):
    backtested_trades: int
    forward_trades: int
    win_rate_pct: float
    avg_r: float
    max_drawdown_pct: float
    max_daily_loss_pct: float
