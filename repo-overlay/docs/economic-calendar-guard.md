# Economic Calendar Guard for Self-Trading AI

This module turns the FX co-pilot into a full economic calendar and risk guard.

## What it does

- Syncs scheduled economic events
- Tracks country, currency, event, period, previous, forecast, actual and revised values
- Classifies event importance: low, medium, high, critical
- Creates pair-level blackout windows
- Exposes an API for your self-trading AI to check before placing a live order
- Shows an onsite dashboard at `/fx-copilot/calendar`
- Combines calendar risk with the FX news co-pilot in `/api/fx-copilot/risk-check`

## Provider options

Preferred:
- Trading Economics: set `FX_CALENDAR_PROVIDER=trading_economics` and `TRADING_ECONOMICS_KEY`

Fallback:
- Financial Modeling Prep: set `FX_CALENDAR_PROVIDER=financial_modeling_prep` and `FMP_API_KEY`

Testing:
- Demo mode: set `FX_CALENDAR_PROVIDER=demo`

## Setup

1. Copy `repo-overlay` into your GitHub repo root.
2. Run `supabase/fx_copilot_schema.sql` in Supabase SQL Editor.
3. Add variables from `.env.example.fx-copilot` into Vercel.
4. Deploy.
5. Test `/api/fx-copilot/health`.
6. Sync calendar using `/api/fx-copilot/calendar/sync`.
7. Open `/fx-copilot/calendar`.

## Important API endpoints

### Upcoming events

```txt
GET /api/fx-copilot/calendar/upcoming?hours=168
GET /api/fx-copilot/calendar/upcoming?currencies=GBP,USD&importance=high,critical
```

### Calendar-only pair risk

```txt
GET /api/fx-copilot/calendar/risk-check?pair=GBP/USD
```

### Combined news + calendar risk

```txt
POST /api/fx-copilot/risk-check
Content-Type: application/json

{
  "pair": "GBP/USD",
  "side": "buy",
  "strategy": "London breakout",
  "intendedRiskPct": 0.5,
  "entryReason": "Strategy signal"
}
```

Possible decisions:

- `allow`
- `reduce_risk`
- `block`
- `paper_only`

Calendar-only decisions include:

- `allow`
- `watch`
- `reduce_risk`
- `block_new_entries`
- `close_only`
- `paper_only`

## Recommended execution engine behaviour

The self-trading AI should call the combined risk endpoint before every live order.

```txt
Strategy signal
  -> /api/fx-copilot/risk-check
  -> hard risk engine
  -> broker execution API
```

Suggested hard behaviour:

- `allow`: continue if all other risk rules pass
- `reduce_risk`: reduce position size or require extra confirmation
- `block`: do not open new live trades
- `paper_only`: route signal to paper trading only
- `close_only`: no new trades; allow close/reduce-only orders

## Default blackout rules

- Critical events: 120 minutes before and 120 minutes after
- High events: 60 minutes before and 60 minutes after
- Medium events: 20 minutes before and 15 minutes after
- Low events: no blackout

You can change these in Vercel environment variables.

## What counts as critical

The module automatically upgrades obvious macro events such as:

- Interest rate decisions
- FOMC / Fed policy
- Bank of England decisions
- ECB decisions
- CPI / inflation
- Non-farm payrolls

## Safety note

The calendar guard should not be the only control. Keep these hard-coded outside the AI layer:

- max risk per trade
- max daily loss
- max open trades
- max currency exposure
- spread/slippage checks
- broker connection health
- emergency kill switch
- full audit log
