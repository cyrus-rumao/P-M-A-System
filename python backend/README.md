# Python FastAPI backend

This is a FastAPI replica of the Node/Express backend in `backend`. It keeps
the same `/api` route paths, MongoDB collections, signed cookie session
behavior, local bcrypt authentication, and Google OAuth flow.

Copy `.env.example` to `.env`, provide the same values used by the Node
backend, and install dependencies with `pip install -r requirements.txt`.

Run with:

```powershell
uvicorn main:app --reload --port 8000
```

`REDIS_URL` is supported as an optional connection hook. The original
Express backend does not currently use Redis for any endpoint or session.
