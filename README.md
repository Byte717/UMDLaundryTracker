# UMD LaundryTrack

A small Render-ready Flask app that polls CSC GO machine links, stores observed machine states, and shows when each machine was seen as occupied.

When Supabase is configured, readings persist across Render restarts and deploys. Without it, the app falls back to a local JSONL file for development.

## Local run

```bash
pip install -r requirements.txt
python main.py
```

Open `http://localhost:5000`.

## Render

Create a new Render Blueprint from this folder. `render.yaml` installs Python dependencies and starts the app with Gunicorn. The app polls every 60 seconds by default.

Useful environment variables:

- `POLL_INTERVAL_SECONDS`: polling cadence, default `60`; Render uses `30`
- `POLL_BATCH_SIZE`: number of machines checked per poll, default `2`; Render uses `1`
- `OCCUPIED_RECHECK_GRACE_SECONDS`: delay after predicted finish before rechecking an occupied machine, default `120`
- `SELENIUM_TIMEOUT_SECONDS`: Selenium wait timeout, default `12`
- `MAX_OBSERVATIONS_IN_MEMORY`: recent JSONL rows loaded into memory, default `1000`
- `OBSERVATIONS_PATH`: JSONL storage path, default `laundrytrack-observations.jsonl`
- `SUPABASE_URL`: Supabase project URL; enables persistent storage with `SUPABASE_SECRET_KEY`
- `SUPABASE_SECRET_KEY`: server-only Supabase secret key; never commit this value
- `CHROME_BINARY`: optional path to Chrome/Chromium if auto-detection fails
- `DISABLE_POLLER=1`: disables background polling for tests/debugging

## Files

- `links.py`: machine IDs and CSC GO URLs
- `main.py`: Flask app, Selenium scraper, persistence, and background poller
- `templates/dashboard.html`: dashboard markup
- `static/styles.css`: dashboard styling
- `static/app.js`: refresh and live UI updates
- `supabase-schema.sql`: one-time Supabase table setup

## Persistent Supabase storage

The app uses Supabase automatically when both of these Render environment variables are set:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=sb_secret_...
```

Before deploying with those variables, open Supabase's SQL Editor and run
[`supabase-schema.sql`](supabase-schema.sql). The app keeps using the local
JSONL file only when these variables are absent, which is useful for local
development. The script enables Row Level Security and grants the server-only
Supabase role access to the observations table.
