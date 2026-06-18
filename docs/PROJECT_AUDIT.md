# GitHub readiness audit

## Included

- Backend source files
- Frontend source files
- Sanitised `.env.example`
- Example economic calendar data
- GitHub `.gitignore`
- Vercel starter entrypoint/config
- Security and deployment documentation
- V4 confidence gate code applied through `backend/config.py` and `backend/strategy.py`

## Excluded intentionally

- `.env`
- `.env api codes.txt`
- `.venv`
- `__pycache__`
- SQLite runtime database files
- Local Windows batch files
- PowerShell patch files
- Raw patch folder
- Any file that appears to contain real secrets

## Notes

The source folder that this package was created from had local/synced runtime items. Those have not been included in this clean package.

If real API keys existed in the original working folder, rotate them before using this package online.
