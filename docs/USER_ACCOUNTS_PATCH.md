# User Accounts Patch

This patch adds a simple private-user layer for the current MVP.

## Files included

- `backend/main.py` — replaces the existing backend entrypoint.
- `frontend/auth.js` — login overlay and API session header.
- `frontend/auth.css` — login overlay styling.

The repo already has these two helper files from the direct commit attempt:

- `backend/auth.py`
- `backend/user_records.py`

## Manual index.html edit required

Open `frontend/index.html`.

In the `<head>`, directly after the existing styles link:

```html
<link rel="stylesheet" href="/static/styles.css"/>
```

add:

```html
<link rel="stylesheet" href="/static/auth.css"/>
```

Near the bottom, directly before:

```html
<script src="/static/app.js"></script>
```

add:

```html
<script src="/static/auth.js"></script>
```

## Vercel environment variables

Add these in Vercel Project Settings → Environment Variables:

```text
AUTH_ALLOWED_USERS=Jake,Jordan
AUTH_PASSCODE=<the shared access code you chose>
AUTH_TOKEN_SECRET=Yl_TI6MjF5JbnRCHPRU6MtFl0y2HJCzHy5aD36uWx-g
AUTH_TOKEN_TTL_SECONDS=86400
```

Do not put the real access code in GitHub.

## After upload

1. Upload the files to GitHub.
2. Commit the changes.
3. Let Vercel redeploy.
4. Test `/api/health`.
5. Open the app in a private/incognito browser window.
6. Sign in as Jordan and add a test journal entry.
7. Log out.
8. Sign in as Jake and confirm Jordan's entry is not visible.
