# Deployment notes

## Current deployment status (v0.5.0)

The app is live on Vercel with:
- FastAPI backend (SQLAlchemy, SQLite/Postgres dual-mode)
- HMAC session token authentication
- User-scoped journal and paper-trade records
- Paper Trading Test Lab (7-day sprint dashboard)

## Required Vercel environment variables

Set these in your Vercel project settings before deploying:

- DATABASE_URL: Postgres connection string (required on Vercel)
- AUTH_PASSCODE: shared access code for all users
- AUTH_TOKEN_SECRET: random signing key (generate a strong random string)
- AUTH_ALLOWED_USERS: comma-separated usernames, e.g. Jake,Jordan (optional, default is Jake,Jordan)
- AUTH_TOKEN_TTL_SECONDS: session lifetime in seconds (optional, default 86400)

Optional API keys (all fall back gracefully if not set):
- OANDA_ACCESS_TOKEN and OANDA_ACCOUNT_ID: for live market data
- TWELVE_DATA_API_KEY: alternative market data provider
- FMP_API_KEY or FINNHUB_API_KEY: for economic calendar API
- DATA_PROVIDER: auto, oanda, twelvedata, or frankfurter

## Recommended database

For local development, SQLite is used automatically.

For Vercel or any serverless deployment, use hosted Postgres. Free options:
- Neon (neon.tech)
- Supabase (supabase.com)
- Railway (railway.app)

The app will refuse to start on Vercel without DATABASE_URL set, to prevent silent data loss on the ephemeral filesystem.

## Basic GitHub import

    git init
    git add .
    git commit -m "Initial GitHub-ready AI FX Co-Pilot package"
    git branch -M main
    git remote add origin <your-private-github-repo-url>
    git push -u origin main

## Vercel entrypoint

This package includes api/index.py and vercel.json.
The entrypoint imports the FastAPI app from backend.main.

## Deployment checklist

- DATABASE_URL is set to hosted Postgres
- AUTH_PASSCODE is set
- AUTH_TOKEN_SECRET is set to a strong random value
- AUTH_ALLOWED_USERS is set to your usernames
- /api/health returns status ok
- Login screen appears on first visit
- Journal and paper-trade data is separated by user
- Data providers show clear warnings when fallback data is active

## Security reminder

Keep the repository private. Do not commit .env files or API keys.
All sensitive configuration must go through Vercel environment variables.
