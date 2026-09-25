# LaundryTrack

A small Render-ready Flask app that polls CSC GO machine links, stores observed machine states in a plain JSONL file, and shows when each machine was seen as occupied.

On Render's normal web service filesystem, the JSONL file is useful for live tracking but may be lost on restart or redeploy. For permanent history without a database, use a persistent disk and point `OBSERVATIONS_PATH` at that disk.

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
- `CHROME_BINARY`: optional path to Chrome/Chromium if auto-detection fails
- `DISABLE_POLLER=1`: disables background polling for tests/debugging

## Files

- `links.py`: machine IDs and CSC GO URLs
- `main.py`: Flask app, Selenium scraper, file persistence, and background poller
- `templates/dashboard.html`: dashboard markup
- `static/styles.css`: dashboard styling
- `static/app.js`: refresh and live UI updates
