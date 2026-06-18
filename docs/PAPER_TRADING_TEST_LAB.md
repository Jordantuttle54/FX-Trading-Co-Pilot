# Paper Trading Test Lab

## Purpose

Use this system for a 7-day paper-trading validation sprint before making any decision about further automation.

The goal is not to prove the system can predict the market. The goal is to test whether the decision process improves discipline, risk control and repeatability.

## Rules for the 7-day test

1. Only record simulated trades. Live execution remains locked.
2. Every paper trade must have an entry, stop-loss, target, risk percentage, risk amount and notes.
3. A trade should only be opened after checking the news guard and setup scanner.
4. Close every paper trade with a final close price and R result.
5. Judge performance using closed trades only.
6. Export the CSV at the end of each day as a backup.

## Useful minimum sample

A week is only a first validation period. Treat the result as useful only if there are at least 10 closed paper trades.

## Review metrics

- Number of trades
- Number open
- Number closed
- Win rate
- Total R
- Estimated P/L
- Whether trades followed the confidence gate
- Whether news risk was respected
- Whether the user overtraded

## Important persistence note

The current online MVP still uses SQLite on the Vercel runtime path. This is suitable for feature testing, but it is not the final database architecture for a serious multi-user platform.

Before relying on this as a long-term trade journal, migrate persistence to hosted Postgres such as Neon or Supabase.

## End-of-week decision

If the test produces positive Total R, acceptable drawdown, clean journaling and disciplined execution, the next development step is persistent Postgres storage and a proper analytics dashboard.

If the result is negative or inconsistent, improve the scoring rules and checklist before adding any execution features.
