from __future__ import annotations

from itertools import product
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import paper_mvp_persistent as analysis
from . import backtest

app = backtest.app

# A parameter combo needs at least this many trades in the backtest window
# before it's trusted at all - a config that only fired 3 trades isn't
# meaningful no matter how good those 3 happened to look.
MIN_TRADES_FOR_TRUST = 12

# Deliberately small, bounded grid - this runs synchronously inside one HTTP
# request, so the search space is kept small enough to finish in a reasonable
# time instead of exhaustively searching every combination. 5 x 3 x 3 = 45
# backtests per pair.
TREND_STRENGTH_GRID = [0.0, 0.3, 0.6, 1.0, 1.5]
RR_GRID = [1.8, 2.2, 2.6]
STOP_ATR_MULT_GRID = [1.0, 1.2, 1.5]


class CalibrateRequest(BaseModel):
    pair: str
    candle_count: int = 2000
    lookback: int = 150


def _combo_score(trades: List[Dict[str, Any]]) -> float:
    if len(trades) < MIN_TRADES_FOR_TRUST:
        return float("-inf")
    return sum(t["result_r"] for t in trades)


def _summary_row(pair: str, overrides: Dict[str, Any], trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = backtest._summarize(pair, trades)
    summary.pop("sample", None)
    return {**overrides, **summary}


def calibrate_pair(pair: str, candle_count: int, lookback: int) -> Dict[str, Any]:
    if pair not in analysis.WATCHLIST:
        raise HTTPException(status_code=400, detail=f"Unknown pair: {pair}")
    candle_count = max(backtest.MIN_CANDLES, min(int(candle_count), backtest.MAX_CANDLES))
    lookback = max(30, min(int(lookback), 200))
    candles = backtest._historical_candles(pair, candle_count)

    current = analysis.get_pair_strategy(pair)
    results: List[Dict[str, Any]] = []
    best_overrides: Optional[Dict[str, Any]] = None
    best_score = float("-inf")

    for trend_strength, rr, stop_mult in product(TREND_STRENGTH_GRID, RR_GRID, STOP_ATR_MULT_GRID):
        overrides = {"min_trend_strength": trend_strength, "rr": rr, "stop_atr_mult": stop_mult}
        trades = backtest._simulate_pair_trades(pair, candles, lookback, strategy_overrides=overrides)
        results.append(_summary_row(pair, overrides, trades))
        score = _combo_score(trades)
        if score > best_score:
            best_score = score
            best_overrides = overrides

    results.sort(key=lambda r: r["total_r"], reverse=True)

    current_trades = backtest._simulate_pair_trades(pair, candles, lookback, strategy_overrides=current)
    best_trades = backtest._simulate_pair_trades(pair, candles, lookback, strategy_overrides=best_overrides) if best_overrides else []

    return {
        "pair": pair,
        "candle_count": candle_count,
        "lookback": lookback,
        "data_provider": "oanda" if analysis.oanda_configured() else "synthetic-fallback",
        "combos_tested": len(results),
        "min_trades_for_trust": MIN_TRADES_FOR_TRUST,
        "current_config": current,
        "current_result": _summary_row(pair, {}, current_trades),
        "best_config": best_overrides,
        "best_result": _summary_row(pair, {}, best_trades) if best_overrides else None,
        "insufficient_data": best_overrides is None,
        "top_results": results[:10],
    }


@app.post("/api/agent/strategy/calibrate")
async def agent_strategy_calibrate(req: CalibrateRequest, user: str = Depends(analysis.current_user)):
    return calibrate_pair(req.pair, req.candle_count, req.lookback)
