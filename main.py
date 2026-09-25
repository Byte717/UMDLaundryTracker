import atexit
import json
import os
import shutil
import threading
from collections import deque
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, render_template
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from links import machines


BASE_DIR = Path(__file__).resolve().parent
OBSERVATIONS_PATH = Path(
    os.environ.get("OBSERVATIONS_PATH", str(BASE_DIR / "laundrytrack-observations.jsonl"))
)
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
SELENIUM_TIMEOUT_SECONDS = int(os.environ.get("SELENIUM_TIMEOUT_SECONDS", "12"))
MAX_OBSERVATIONS_IN_MEMORY = int(os.environ.get("MAX_OBSERVATIONS_IN_MEMORY", "1000"))
POLL_BATCH_SIZE = int(os.environ.get("POLL_BATCH_SIZE", "2"))
OCCUPIED_RECHECK_GRACE_SECONDS = int(
    os.environ.get("OCCUPIED_RECHECK_GRACE_SECONDS", "120")
)
DISPLAY_TIMEZONE_NAME = os.environ.get("DISPLAY_TIMEZONE", "America/New_York")
DISPLAY_TIMEZONE = ZoneInfo(DISPLAY_TIMEZONE_NAME)
storage_lock = threading.Lock()
poll_lock = threading.Lock()
poll_cursor = 0


@dataclass(frozen=True)
class MachineReading:
    machine_id: int
    status: str
    minutes_remaining: Optional[int]
    observed_at: str
    error: Optional[str] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_observed_at(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def init_storage() -> None:
    OBSERVATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OBSERVATIONS_PATH.touch(exist_ok=True)


def create_driver() -> webdriver.Chrome:
    options = Options()
    options.page_load_strategy = "eager"
    chromium_path = (
        os.environ.get("CHROME_BINARY")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
    )
    if chromium_path:
        options.binary_location = chromium_path
    options.add_argument("--headless=new")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-features=BackForwardCache,Translate")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-site-isolation-trials")
    options.add_argument("--disable-sync")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--js-flags=--max-old-space-size=64")
    options.add_argument("--mute-audio")
    options.add_argument("--no-first-run")
    options.add_argument("--renderer-process-limit=1")
    options.add_argument("--window-size=420,720")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_experimental_option(
        "prefs",
        {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.fonts": 2,
            "profile.managed_default_content_settings.geolocation": 2,
            "profile.managed_default_content_settings.media_stream": 2,
        },
    )
    return webdriver.Chrome(options=options)


def page_rendered(driver) -> bool:
    return driver.execute_script(
        "return document.querySelector('main.container')?.children.length > 0"
    )


def get_machine_status(driver):
    time_nodes = driver.find_elements(By.CSS_SELECTOR, ".machine-state .time .value")

    if time_nodes and time_nodes[0].text.strip():
        return ("occupied", int(time_nodes[0].text.strip()))

    page_text = driver.execute_script("return document.body?.innerText || ''")
    page_text_upper = page_text.upper()
    if "MACHINE OFFLINE" in page_text_upper or "CURRENTLY OFFLINE" in page_text_upper:
        return ("out_of_order", None)

    if "FREE" in page_text_upper:
        return ("available", None)

    done_nodes = driver.find_elements(
        By.XPATH,
        "//*[contains(@class,'machine-state')]//*[translate(normalize-space(), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')='DONE']",
    )
    if done_nodes:
        return ("available", None)

    ready_nodes = driver.find_elements(
        By.XPATH,
        "//*[contains(translate(normalize-space(), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'AVAILABLE') or contains(translate(normalize-space(), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'START')]",
    )
    if ready_nodes:
        return ("available", None)

    return False


def read_machine(driver, machine_id: int, url: str) -> MachineReading:
    observed_at = utc_now()
    try:
        driver.get(url)
        WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(page_rendered)
        status, minutes = WebDriverWait(driver, SELENIUM_TIMEOUT_SECONDS).until(
            get_machine_status
        )
        return MachineReading(machine_id, status, minutes, observed_at)
    except (TimeoutException, WebDriverException, ValueError) as exc:
        return MachineReading(machine_id, "out_of_order", None, observed_at, str(exc)[:500])


def save_readings(readings: list[MachineReading]) -> None:
    with storage_lock:
        with OBSERVATIONS_PATH.open("a", encoding="utf-8") as handle:
            for reading in readings:
                record = asdict(reading)
                record["url"] = machines[reading.machine_id]
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_observations() -> list[dict]:
    if not OBSERVATIONS_PATH.exists():
        return []

    lines = deque(maxlen=MAX_OBSERVATIONS_IN_MEMORY)
    with storage_lock:
        with OBSERVATIONS_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                lines.append(line)

    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if record.get("status") == "unknown":
                record["status"] = "out_of_order"
            records.append(record)
        except json.JSONDecodeError:
            continue
    return records


def failed_poll_readings(error: Exception) -> list[MachineReading]:
    observed_at = utc_now()
    message = str(error)[:500]
    return [
        MachineReading(machine_id, "out_of_order", None, observed_at, message)
        for machine_id in sorted(machines)
    ]


def poll_machine(machine_id: int, url: str) -> MachineReading:
    driver = create_driver()
    try:
        return read_machine(driver, machine_id, url)
    finally:
        driver.quit()


def poll_once() -> list[MachineReading]:
    global poll_cursor

    if not poll_lock.acquire(blocking=False):
        return []

    readings = []
    try:
        machine_items = sorted(machines.items())
        batch_size = max(1, min(POLL_BATCH_SIZE, len(machine_items)))
        latest_by_id = {row["machine_id"]: row for row in latest_observations(adjust=False)}
        now = datetime.now(timezone.utc)
        due_items = []

        for offset in range(len(machine_items)):
            machine_id, url = machine_items[(poll_cursor + offset) % len(machine_items)]
            row = latest_by_id.get(machine_id)
            if should_poll_machine(row, now):
                due_items.append((machine_id, url))
            if len(due_items) >= batch_size:
                break

        if not due_items:
            poll_cursor = (poll_cursor + 1) % len(machine_items)
            return []

        last_polled_id = due_items[-1][0]
        last_index = [machine_id for machine_id, _ in machine_items].index(last_polled_id)
        poll_cursor = (last_index + 1) % len(machine_items)

        for machine_id, url in due_items:
            try:
                readings.append(poll_machine(machine_id, url))
            except Exception as exc:
                readings.append(
                    MachineReading(
                        machine_id,
                        "out_of_order",
                        None,
                        utc_now(),
                        str(exc)[:500],
                    )
                )
    except Exception as exc:
        readings = failed_poll_readings(exc)
    finally:
        poll_lock.release()

    save_readings(readings)
    return readings


def should_poll_machine(row: Optional[dict], now: datetime) -> bool:
    if row is None:
        return True

    if row["status"] != "occupied":
        return True

    minutes_remaining = row.get("minutes_remaining")
    if minutes_remaining is None:
        return True

    observed_at = parse_observed_at(row["observed_at"])
    done_at = observed_at + timedelta(minutes=int(minutes_remaining))
    recheck_at = done_at + timedelta(seconds=OCCUPIED_RECHECK_GRACE_SECONDS)
    return now >= recheck_at


def adjusted_observation(row: dict, now: Optional[datetime] = None) -> dict:
    adjusted = dict(row)
    if adjusted["status"] != "occupied" or adjusted.get("minutes_remaining") is None:
        return adjusted

    now = now or datetime.now(timezone.utc)
    observed_at = parse_observed_at(adjusted["observed_at"])
    elapsed_seconds = max(0, (now - observed_at).total_seconds())
    remaining_seconds = int(adjusted["minutes_remaining"]) * 60 - elapsed_seconds

    if remaining_seconds <= 0:
        adjusted["status"] = "available"
        adjusted["minutes_remaining"] = None
        adjusted["predicted"] = True
        return adjusted

    adjusted["minutes_remaining"] = max(1, int((remaining_seconds + 59) // 60))
    adjusted["predicted"] = True
    return adjusted


def latest_observations(adjust: bool = True) -> list[dict]:
    latest = {}
    for row in read_observations():
        current = latest.get(row["machine_id"])
        if current is None or row["observed_at"] > current["observed_at"]:
            latest[row["machine_id"]] = row

    rows = [latest[machine_id] for machine_id in sorted(latest)]
    if adjust:
        now = datetime.now(timezone.utc)
        return [adjusted_observation(row, now) for row in rows]
    return rows


def observation_history(limit: int = 500) -> list[dict]:
    rows = sorted(
        read_observations(),
        key=lambda row: (row["observed_at"], row["machine_id"]),
        reverse=True,
    )
    return rows[:limit]


def weekly_machine_usage(machine_id: int, now: Optional[datetime] = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(DISPLAY_TIMEZONE)
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)
    intervals = []

    if OBSERVATIONS_PATH.exists():
        with storage_lock:
            with OBSERVATIONS_PATH.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                        if (
                            row.get("machine_id") != machine_id
                            or row.get("status") != "occupied"
                            or row.get("minutes_remaining") is None
                        ):
                            continue
                        start = parse_observed_at(row["observed_at"]).astimezone(
                            DISPLAY_TIMEZONE
                        )
                        end = start + timedelta(minutes=int(row["minutes_remaining"]))
                        if end > week_start and start < week_end:
                            intervals.append((max(start, week_start), min(end, week_end)))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        continue

    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + timedelta(minutes=5):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    days = []
    total_minutes = 0
    for day_offset in range(7):
        day_start = week_start + timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        segments = []
        for start, end in merged:
            segment_start = max(start, day_start)
            segment_end = min(end, day_end)
            if segment_end <= segment_start:
                continue
            start_minute = round((segment_start - day_start).total_seconds() / 60)
            end_minute = round((segment_end - day_start).total_seconds() / 60)
            duration = max(1, end_minute - start_minute)
            total_minutes += duration
            segments.append(
                {
                    "start_minute": start_minute,
                    "duration_minutes": duration,
                    "start_label": segment_start.strftime("%-I:%M %p"),
                    "end_label": segment_end.strftime("%-I:%M %p"),
                    "estimated": segment_end > now,
                }
            )
        days.append(
            {
                "label": day_start.strftime("%a"),
                "date": f"{day_start.month}/{day_start.day}",
                "segments": segments,
            }
        )

    return {
        "machine_id": machine_id,
        "week_start": f"{week_start.month}/{week_start.day}",
        "week_end": f"{(week_end - timedelta(days=1)).month}/{(week_end - timedelta(days=1)).day}",
        "total_minutes": total_minutes,
        "days": days,
    }


def machine_summary() -> dict:
    latest = latest_observations()
    occupied = [row for row in latest if row["status"] == "occupied"]
    errors = [row for row in latest if row["status"] == "out_of_order"]
    return {
        "machine_count": len(machines),
        "latest_count": len(latest),
        "occupied_count": len(occupied),
        "available_count": len(latest) - len(occupied) - len(errors),
        "error_count": len(errors),
        "last_observed_at": max((row["observed_at"] for row in latest), default=None),
    }


def create_app() -> Flask:
    init_storage()
    app = Flask(__name__)

    @app.get("/")
    def dashboard():
        return render_template(
            "dashboard.html",
            machines=machines,
            latest=latest_observations(),
            history=observation_history(),
            summary=machine_summary(),
            poll_interval=POLL_INTERVAL_SECONDS,
        )

    @app.get("/api/status")
    def api_status():
        return jsonify(
            {
                "summary": machine_summary(),
                "machines": latest_observations(),
                "history": observation_history(),
            }
        )

    @app.get("/api/machines/<int:machine_id>/usage")
    def api_machine_usage(machine_id: int):
        if machine_id not in machines:
            abort(404)
        return jsonify(weekly_machine_usage(machine_id))

    @app.post("/api/poll")
    def api_poll():
        return jsonify({"machines": [reading.__dict__ for reading in poll_once()]})

    return app


class Poller:
    def __init__(self, interval_seconds: int):
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                poll_once()
            except Exception as exc:
                print(f"poll failed: {exc}", flush=True)
            self.stop_event.wait(self.interval_seconds)


app = create_app()
poller = Poller(POLL_INTERVAL_SECONDS)

if os.environ.get("DISABLE_POLLER") != "1":
    poller.start()
    atexit.register(poller.stop)


def main(argc: int, *argv: str) -> int:
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    argv = __import__("sys").argv
    exit(main(len(argv), *argv))
