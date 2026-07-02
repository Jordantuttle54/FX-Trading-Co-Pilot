# AI FX Co-Pilot

A browser-based FX trading discipline and decision-support platform. The app is designed for market monitoring, news-risk awareness, setup scoring, risk calculation, journaling, paper trading and automation-readiness checks.

## Important safety notice

This project is educational software only. It is not financial advice and it does not place live trades. Live execution is intentionally locked and autonomous execution is disabled.

Do not connect real-money execution until the system has been reviewed, tested, secured, backtested and approved by a suitably qualified person. FX, spread betting and CFDs can result in losses.

## Current status

- Version: 0.5.0-user-accounts
- Mode: paper/manual review only
- Live trading: locked
- Autonomous execution: disabled
- Confidence gate: V4 strict confidence gate applied
- Auth: HMAC session tokens, user-scoped journal and paper-trade records
- Database: SQLite (local dev) / Postgres (production via DATABASE_URL)

## Features

- Market snapshot and watchlist
- Manual/API economic calendar
- News guard
- Setup scanner
- Conservative confidence scoring
- Risk calculator
- Journal (per-user)
- Paper trade log with 7-day sprint dashboard (per-user)
- Automation-readiness gate
- User login with HMAC session tokens

## Project structure

    backend/    FastAPI backend and trading logic
    frontend/   Static browser interface
    data/       Safe example calendar data only
    docs/       Security and deployment notes
    api/        Vercel entrypoint

## Local setup

1. Create a virtual environment and activate it.
2. Install dependencies: pip install -r requirements.txt
3. Copy env template: cp .env.example .env
4. Fill in optional API keys in .env. Do not commit .env.
5. Start the app: python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
6. Open: http://127.0.0.1:8000

## Authentication

The app requires a username and passcode to access journal and paper-trade data. Configure via environment variables:

- AUTH_ALLOWED_USERS: comma-separated list of usernames (default: Jake,Jordan)
- AUTH_PASSCODE: shared access code for all users (required; set in Vercel env vars)
- AUTH_TOKEN_SECRET: signing key for session tokens (set a strong random value in production)
- AUTH_TOKEN_TTL_SECONDS: session duration in seconds (default: 86400)

## Database setup

For local development, SQLite is used automatically in data/fx_copilot.sqlite3.

For production (Vercel or other hosted environments), set DATABASE_URL to a Postgres connection string. The app will refuse to start on Vercel without this, because Vercel's filesystem is ephemeral.

Free Postgres options: Neon (neon.tech), Supabase (supabase.com), Railway (railway.app).

## GitHub import checklist

Before pushing this project to GitHub, confirm:

- .env is not present.
- No real API keys are present.
- No OANDA tokens or account IDs are present.
- No .sqlite3, .db, .venv or pycache files are present.
- The repository is private.
- Secrets will be added only through hosting-provider environment variables.

## Vercel environment variables

Set the following in your Vercel project before deploying:

- DATABASE_URL: hosted Postgres connection string (required)
- AUTH_PASSCODE: shared access code
- AUTH_TOKEN_SECRET: random signing key
- AUTH_ALLOWED_USERS: e.g. Jake,Jordan

## Next recommended improvements

- Add export/import for journal and paper trades.
- Add structured logging and error monitoring.
- Add automated tests for strategy scoring, risk calculation and provider fallbacks.
- Add a formal backtesting module.
