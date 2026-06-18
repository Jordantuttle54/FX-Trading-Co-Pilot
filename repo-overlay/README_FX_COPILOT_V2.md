# FX Co-Pilot V2: Economic Calendar + News Risk Guard

This overlay includes:

- News scanner
- Economic calendar scanner
- Economic event dashboard
- Blackout window engine
- Pair-level risk-check API
- Combined news + calendar risk-check API
- Supabase schema
- Vercel cron configuration

## Main onsite pages

- `/fx-copilot`
- `/fx-copilot/calendar`

## Main APIs

- `/api/fx-copilot/health`
- `/api/fx-copilot/cron`
- `/api/fx-copilot/calendar/sync`
- `/api/fx-copilot/calendar/upcoming`
- `/api/fx-copilot/calendar/risk-check?pair=GBP/USD`
- `/api/fx-copilot/risk-check`

## Before live trading

Run in demo/paper mode first. The guard should sit before your broker execution API and should never override your hard risk limits.
