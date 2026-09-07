# Tests

Run everything:

```bash
python tests/run_all.py
```

Run one suite while debugging it:

```bash
python tests/test_agent.py
```

Each file is a standalone script that prints `PASS`/`FAIL` per check and exits
non-zero if any fail. They run in separate processes because the app is a chain
of modules that patch routes onto one shared FastAPI instance and cache state in
module globals — sharing an interpreter would let them contaminate each other.

No database is needed. Every suite unsets `DATABASE_URL` so the app uses its
in-memory store, and market data is stubbed, so nothing here touches OANDA or
opens a real position.

## What each suite protects

| File | Covers |
| --- | --- |
| `test_agent.py` | The autonomous agent's safety gates: off by default, position and daily caps, kill switch, trading window, confidence floor, allowed pairs, loss-limit halts, dry run, and that its endpoints reject unauthenticated callers. |
| `test_strategies.py` | The strategy registry. Notably that trend continuation still returns byte-identical output to before it became pluggable, so old backtests and calibrations still mean what they meant. |
| `test_sl.py` | Stop and target triggering: the correct side of the spread, exact-touch behaviour, and that a gapped stop still fills *at* the stop for -1R. |
| `test_goldcap.py` | The gold risk cap, including that no other pair is affected. |
| `test_endpoint.py` | The trade history repair: dry run doesn't mutate, apply is correct and idempotent, manual closes are left alone, and the wallet recomputes. |
| `test_pricing.py` | That a trade is entered at a price it could actually have been filled at (ask for a buy, bid for a sell) without changing the stop distance or R:R, and that the backtest charges a spread so its results stay comparable to live. |
| `test_integrity.py` | That no deployment can open a trade while its prices are invented, that the client cannot dictate a trade's entry/stop/target/risk, that a trade's origin says who really placed it, and that the daily and weekly loss limits stop a person opening trades by hand, not just the agent. |
| `test_execution.py` | The broker order path: the stop and target ride the actual fill rather than a pre-fill quote, so a slipped fill still risks exactly what the position was sized for. Also that live trading stays locked. |
| `test_performance.py` | That the drawdown figure is computed rather than hardcoded to zero, and that the per-pair, per-setup and per-origin breakdowns actually split the trades — including the agent's results against your own. |
| `test_notify.py` | Alerting: what is worth interrupting someone for and what stays quiet, plus that a dead webhook cannot stop the agent trading. |
| `test_stale.py` | Refusing to trade on a closed market: a stale quote, a quote whose age can't be established, or one the broker flags as non-tradeable. With the London window switched off, this is the only thing keeping the agent out of the weekend. |

## Why these exist

Six bugs in this codebase have been the same shape: something used a price that
was convenient rather than true. Stops filled at the live price instead of the
stop level; a failed data call substituted invented prices that then closed real
positions; stale fallback candles were treated as current; open trades were
valued at the mid rather than the side they would actually close on.

Most of these were invisible until someone looked at a number and asked whether
it was right. The point of these suites is that the next one gets caught before
it reaches the journal.

When fixing a bug here, add the check that would have caught it.
