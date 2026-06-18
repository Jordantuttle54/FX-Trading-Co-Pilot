# Deployment notes

## Recommended initial stack

- GitHub private repository
- Vercel for the web app/API prototype
- Hosted Postgres before serious online use
- Vercel environment variables for secrets

## Basic GitHub import

```bash
git init
git add .
git commit -m "Initial GitHub-ready AI FX Co-Pilot package"
git branch -M main
git remote add origin <your-private-github-repo-url>
git push -u origin main
```

## Vercel starting point

This package includes:

```text
api/index.py
vercel.json
```

The entrypoint imports the FastAPI app from `backend.main`.

## Important database warning

The current backend uses SQLite for local development. SQLite is not recommended as the final hosted database for this platform. Before relying on the online version, migrate the journal, paper trades, settings and calendar data to hosted Postgres.

## Suggested online migration path

1. Deploy the static/paper-only app privately.
2. Add environment variables in Vercel.
3. Confirm `/api/health` works.
4. Confirm all data providers show clear warnings when fallback data is active.
5. Add hosted Postgres.
6. Update `backend/database.py` to use Postgres.
7. Add authentication.
8. Add tests and deployment checks.

## Do not deploy publicly yet

This is still a prototype. Keep access private until authentication, database persistence, logging and security review are complete.
