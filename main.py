import atexit
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from links import machines


BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_PATH", str(BASE_DIR / "laundrytrack.sqlite3"))
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
SELENIUM_TIMEOUT_SECONDS = int(os.environ.get("SELENIUM_TIMEOUT_SECONDS", "20"))


@dataclass(frozen=True)
class MachineReading:
    machine_id: int
    status: str
    minutes_remaining: Optional[int]
    observed_at: str
    error: Optional[str] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect_db():
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                minutes_remaining INTEGER,
                observed_at TEXT NOT NULL,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_observations_machine_time
            ON observations(machine_id, observed_at DESC)
            """
        )


def create_driver() -> webdriver.Chrome:
    options = Options()
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
    options.add_argument("--window-size=1280,900")
    return webdriver.Chrome(options=options)


def page_rendered(driver) -> bool:
    return driver.execute_script(
        "return document.querySelector('main.container')?.children.length > 0"
    )


def get_machine_status(driver):
    time_nodes = driver.find_elements(By.CSS_SELECTOR, ".machine-state .time .value")

    if time_nodes and time_nodes[0].text.strip():
        return ("occupied", int(time_nodes[0].text.strip()))

    done_nodes = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'machine-state')]//h1[normalize-space()='Done']",
    )
    if done_nodes:
        return ("done", None)

    ready_nodes = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'machine-state')]//*[contains(normalize-space(), 'Available') or contains(normalize-space(), 'Start')]",
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
        return MachineReading(machine_id, "unknown", None, observed_at, str(exc)[:500])


def save_readings(readings: list[MachineReading]) -> None:
    with connect_db() as conn:
        conn.executemany(
            """
            INSERT INTO observations (
                machine_id, url, status, minutes_remaining, observed_at, error
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    reading.machine_id,
                    machines[reading.machine_id],
                    reading.status,
                    reading.minutes_remaining,
                    reading.observed_at,
                    reading.error,
                )
                for reading in readings
            ],
        )


def poll_once() -> list[MachineReading]:
    driver = create_driver()
    try:
        readings = [
            read_machine(driver, machine_id, url)
            for machine_id, url in sorted(machines.items())
        ]
    finally:
        driver.quit()

    save_readings(readings)
    return readings


def latest_observations() -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT o.*
            FROM observations o
            JOIN (
                SELECT machine_id, MAX(observed_at) AS observed_at
                FROM observations
                GROUP BY machine_id
            ) latest
              ON latest.machine_id = o.machine_id
             AND latest.observed_at = o.observed_at
            ORDER BY o.machine_id
            """
        ).fetchall()

    return [dict(row) for row in rows]


def observation_history(limit: int = 500) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM observations
            ORDER BY observed_at DESC, machine_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def machine_summary() -> dict:
    latest = latest_observations()
    occupied = [row for row in latest if row["status"] == "occupied"]
    errors = [row for row in latest if row["status"] == "unknown"]
    return {
        "machine_count": len(machines),
        "latest_count": len(latest),
        "occupied_count": len(occupied),
        "available_count": len(latest) - len(occupied) - len(errors),
        "error_count": len(errors),
        "last_observed_at": max((row["observed_at"] for row in latest), default=None),
    }


def create_app() -> Flask:
    init_db()
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
