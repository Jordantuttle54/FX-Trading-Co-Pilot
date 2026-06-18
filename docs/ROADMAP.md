# Roadmap

## Phase 1: Secure GitHub import

- Import clean package into a private GitHub repo.
- Confirm no secrets are committed.
- Rotate any keys that were stored in local/synced folders.

## Phase 2: Private hosted MVP

- Deploy private preview.
- Add environment variables.
- Confirm fallback-data warnings.
- Keep paper/manual review only.

## Phase 3: Database migration

- Replace SQLite with hosted Postgres.
- Add schema migrations.
- Add journal export/import.

## Phase 4: Product hardening

- Add authentication.
- Add tests.
- Add structured logs.
- Add provider-health checks.
- Add version/status endpoint.

## Phase 5: Evidence and backtesting

- Add historical trade/setup dataset.
- Backtest setup score rules.
- Track expectancy by setup type, pair, session and news condition.
- Keep live trading locked until evidence and controls are mature.
