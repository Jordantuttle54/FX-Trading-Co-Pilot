# AI FX Co-Pilot

A browser-based FX trading discipline and decision-support platform. The app is designed for market monitoring, news-risk awareness, setup scoring, risk calculation, journaling, paper trading and automation-readiness checks.

## Important safety notice

This project is educational software only. It is not financial advice and it does not place live trades. Live execution is intentionally locked and autonomous execution is disabled.

Do not connect real-money execution until the system has been reviewed, tested, secured, backtested and approved by a suitably qualified person. FX, spread betting and CFDs can result in losses.

## Current status

- Version: `0.4.0-github-ready`
- Mode: paper/manual review only
- Live trading: locked
- Autonomous execution: disabled
- Confidence gate: V4 strict confidence gate applied
- Database: local SQLite for development only
- Recommended online database: hosted Postgres before production use

## Features

- Market snapshot and watchlist
- Manual/API economic calendar
- News guard
- Setup scanner
- Conservative confidence scoring
- Risk calculator
- Journal
- Paper trade log
- Automation-readiness gate

## Project structure

```text
backend/      FastAPI backend and trading logic
frontend/     Static browser interface
data/         Safe example calendar data only
docs/         Security and deployment notes
api/          Vercel entrypoint
```

## Local setup

1. Create a virtual environment.

```bash
python -m venv .venv
```

2. Activate it.

Windows:

```bash
.venv\\Scripts\\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

3. Install dependencies.

```bash
pip install -r requirements.txt
```

4. Create your local environment file.

```bash
cp .env.example .env
```

5. Fill in optional API keys in `.env`. Do not commit `.env`.

6. Start the app.

```bash
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

7. Open the app.

```text
http://127.0.0.1:8000
```

## GitHub import checklist

Before pushing this project to GitHub, confirm:

- `.env` is not present.
- No real API keys are present.
- No OANDA tokens or account IDs are present.
- No `.sqlite3`, `.db`, `.venv` or `__pycache__` files are present.
- The repository is private.
- Secrets will be added only through hosting-provider environment variables.

## Vercel notes

A starter `api/index.py` and `vercel.json` are included. This should be treated as a deployment starting point, not a final production architecture.

For online use, replace local SQLite with hosted Postgres. SQLite is acceptable for local testing, but not ideal for serverless deployment or multi-device platform use.

## Next recommended improvements

1. Move persistence from SQLite to hosted Postgres.
2. Add authentication before sharing the online app.
3. Add a formal backtesting module.
4. Add export/import for journal and paper trades.
5. Add structured logging and error monitoring.
6. Add automated tests for strategy scoring, risk calculation and provider fallbacks.
