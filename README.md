# LaundryTrack

A small Render-ready Flask app that polls CSC GO machine links, stores observed machine states in SQLite, and shows when each machine was seen as occupied.

## Local run

```bash
pip install -r requirements.txt
python main.py
```

Open `http://localhost:5000`.

## Render

Create a new Render Blueprint from this folder. `render.yaml` installs Python dependencies and starts the app with Gunicorn. The app polls every 5 minutes by default.

Useful environment variables:

- `POLL_INTERVAL_SECONDS`: polling cadence, default `300`
- `DATABASE_PATH`: SQLite database path, default `laundrytrack.sqlite3`
- `CHROME_BINARY`: optional path to Chrome/Chromium if auto-detection fails
- `DISABLE_POLLER=1`: disables background polling for tests/debugging

## Files

- `links.py`: machine IDs and CSC GO URLs
- `main.py`: Flask app, Selenium scraper, SQLite persistence, and background poller
- `templates/dashboard.html`: dashboard markup
- `static/styles.css`: dashboard styling
- `static/app.js`: refresh and live UI updates
