# Security checklist

## Critical rules

- Do not commit `.env`.
- Do not commit real API keys.
- Do not commit OANDA tokens or account IDs.
- Do not commit SQLite runtime databases.
- Keep the GitHub repository private.
- Keep live trading disabled.
- Keep autonomous execution disabled.

## Key rotation

If any API key, broker token or account ID has ever been stored in a synced folder, ZIP file, email, ChatGPT conversation or committed repository, treat it as exposed and rotate it.

## Environment variables

Use `.env.example` only as a template. Add real values through:

- local `.env` during local development;
- Vercel environment variables for hosted deployment;
- a managed secret store for future production use.

## Broker connection

Use OANDA practice/demo mode during development. Do not enable live endpoints or order execution until the system has separate security controls, access control, audit logging, backtesting evidence and manual approval.

## Access control

Before deploying beyond personal use, add login protection. For early testing, use hosting-provider deployment protection. For a proper platform, add user authentication and role-based access.
