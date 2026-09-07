from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import paper_mvp_persistent as analysis
from . import paper_mvp_wallet as chain

app = chain.app

MAX_CANDLES = 5000
MIN_CANDLES = 200

# Typical round-trip dealing cost, in pips, for each pair. The backtest fills
# at mid on both sides, so without this every result it produces is better
# than anything the account could achieve - the live agent now enters at the
# ask (buy) or bid (sell) and pays this for real. Charging one full spread per
# trade keeps the two comparable. Widen for a pessimistic run via env, e.g.
# BACKTEST_SPREAD_MULTIPLIER=2.
SPREAD_PIPS = {
    "EUR/USD": 1.0,
    "GBP/USD": 1.3,
    "USD/JPY": 1.0,
    "EUR/GBP": 1.2,
    "GBP/JPY": 2.5,
    "XAU/USD": 3.0,
}
DEFAULT_SPREAD_PIPS = 1.5
SPREAD_MULTIPLIER = float(os.getenv("BACKTEST_SPREAD_MULTIPLIER", "1"))


def spread_cost(pair: str) -> float:
    """The round-trip cost of one trade on this pair, as a price distance."""
    pips = SPREAD_PIPS.get(pair, DEFAULT_SPREAD_PIPS) * SPREAD_MULTIPLIER
    return pips * analysis.pip_size(pair)


class BacktestRequest(BaseModel):
    pairs: Optional[List[str]] = None
    candle_count: int = 1000
    lookback: int = 120


def _historical_candles(pair: str, count: int) -> List[Dict[str, Any]]:
    if analysis.oanda_configured():
        try:
            url = f"{analysis.oanda_base()}/v3/instruments/{pair.replace('/', '_')}/candles"
            with httpx.Client(timeout=20) as client:
                res = client.get(
                    url,
                    params={"count": count, "granularity": "H1", "price": "M"},
                    headers={"Authorization": f"Bearer {os.getenv('OANDA_ACCESS_TOKEN')}"},
                )
                res.raise_for_status()
                data = res.json()
            out = []
            for c in data.get("candles", []):
                if not c.get("complete", True):
                    continue
                m = c["mid"]
                out.append({"open": float(m["o"]), "high": float(m["h"]), "low": float(m["l"]), "close": float(m["c"])})
            if len(out) >= MIN_CANDLES:
                return out
        except Exception as exc:
            # Swallowing this silently meant a backtest could run entirely on
            # invented history and report its results as though they were real.
            analysis.log.error("Backtest candle fetch failed for %s, falling back to invented history: %s", pair, exc)
    # Fallback only - synthetic history has no relation to real market
    # behaviour, so results from this path are for smoke-testing the
    # simulator itself, not for judging the strategy. synthetic_candles tags
    # every candle, which is what is_synthetic() below reads.
    analysis.log.warning("Backtesting %s on invented history - results are meaningless for judging the strategy.", pair)
    return analysis.synthetic_candles(pair, count)


def is_synthetic(candles: List[Dict[str, Any]]) -> bool:
    """Whether this history was invented rather than fetched from the broker."""
    return any(c.get("synthetic") for c in candles[:5])


def _simulate_pair_trades(pair: str, candles: List[Dict[str, Any]], lookback: int, strategy_overrides: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    n = len(candles)
    i = lookback
    while i < n:
        window = candles[max(0, i - lookback + 1):i + 1]
        try:
            candidate = analysis.score_candidate(pair, analysis.START_BALANCE, None, candles=window, strategy_overrides=strategy_overrides)
        except Exception:
            i += 1
            continue
        if candidate.get("status") != "trade_candidate":
            i += 1
            continue

        direction = candidate["direction"]
        entry = float(candidate["entry"])
        sl = float(candidate["stop_loss"])
        tp = float(candidate["take_profit"])
        stop_dist = abs(entry - sl)

        exit_idx = exit_price = exit_reason = None
        for j in range(i + 1, n):
            c = candles[j]
            high, low = float(c["high"]), float(c["low"])
            if direction == "buy":
                hit_sl, hit_tp = low <= sl, high >= tp
            else:
                hit_sl, hit_tp = high >= sl, low <= tp
            # If a single candle's range spans both levels, assume the worse
            # outcome (stop hit first) rather than the optimistic one.
            if hit_sl:
                exit_idx, exit_price, exit_reason = j, sl, "stop_loss"
                break
            if hit_tp:
                exit_idx, exit_price, exit_reason = j, tp, "take_profit"
                break

        if exit_idx is None:
            break  # ran out of history with the trade still open - stop here

        # Trigger levels stay on the mid series the candles are quoted in; the
        # spread is charged once against the outcome, which is where a real
        # round trip actually loses it. A stop-out therefore costs slightly
        # more than 1R, exactly as it does on a live account.
        gross_move = (exit_price - entry) if direction == "buy" else (entry - exit_price)
        cost = spread_cost(pair)
        net_move = gross_move - cost
        result_r = (net_move / stop_dist) if stop_dist > 0 else 0.0
        gross_r = (gross_move / stop_dist) if stop_dist > 0 else 0.0
        trades.append({
            "pair": pair,
            "direction": direction,
            "entry": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "result_r": round(result_r, 3),
            "gross_result_r": round(gross_r, 3),
            "spread_cost_r": round(cost / stop_dist, 3) if stop_dist > 0 else 0.0,
            "bars_held": exit_idx - i,
            "confidence": candidate.get("confidence"),
        })
        i = exit_idx + 1  # no overlapping positions on the same pair

    return trades


def _summarize(label: str, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"pair": label, "trades": 0, "win_rate_pct": 0.0, "avg_r": 0.0, "total_r": 0.0, "profit_factor": 0.0, "max_drawdown_r": 0.0, "sample": []}
    rs = [t["result_r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    total_r = sum(rs)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    running = peak = max_dd = 0.0
    for r in rs:
        running += r
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    return {
        "pair": label,
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "avg_r": round(total_r / len(trades), 3),
        "total_r": round(total_r, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (round(gross_win, 2) if gross_win else 0.0),
        "max_drawdown_r": round(max_dd, 2),
        "sample": trades[-10:],
    }


def run_backtest(pairs: List[str], candle_count: int, lookback: int) -> Dict[str, Any]:
    per_pair = []
    all_trades: List[Dict[str, Any]] = []
    warnings = []
    synthetic_pairs = []
    for pair in pairs:
        candles = _historical_candles(pair, candle_count)
        if is_synthetic(candles):
            synthetic_pairs.append(pair)
            warnings.append(f"{pair}: RAN ON INVENTED HISTORY - these results say nothing about the strategy.")
        if len(candles) < lookback + 10:
            warnings.append(f"{pair}: only {len(candles)} candles available - results may be thin.")
        trades = _simulate_pair_trades(pair, candles, lookback)
        all_trades.extend(trades)
        per_pair.append({**_summarize(pair, trades), "synthetic_history": pair in synthetic_pairs})
    overall = _summarize("ALL", all_trades)
    return {
        "generated_at": analysis.now(),
        "candle_count": candle_count,
        "lookback": lookback,
        # Reported from the candles actually used, not from whether credentials
        # happen to exist - a configured provider whose call fails still lands
        # on invented history, and used to report itself as "oanda".
        "data_provider": "synthetic-fallback" if synthetic_pairs else "oanda",
        "synthetic_pairs": synthetic_pairs,
        "trustworthy": not synthetic_pairs,
        "warnings": warnings,
        "per_pair": per_pair,
        "overall": overall,
    }


@app.post("/api/agent/backtest")
async def agent_backtest(req: BacktestRequest, user: str = Depends(analysis.current_user)):
    pairs = [p for p in (req.pairs or analysis.WATCHLIST) if p in analysis.WATCHLIST]
    if not pairs:
        raise HTTPException(status_code=400, detail="No valid pairs given.")
    candle_count = max(MIN_CANDLES, min(int(req.candle_count), MAX_CANDLES))
    lookback = max(30, min(int(req.lookback), 200))
    return run_backtest(pairs, candle_count, lookback)
