import atexit
import json
import os
import shutil
import threading
from dataclasses import asdict
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
OBSERVATIONS_PATH = Path(
    os.environ.get("OBSERVATIONS_PATH", str(BASE_DIR / "laundrytrack-observations.jsonl"))
)
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
SELENIUM_TIMEOUT_SECONDS = int(os.environ.get("SELENIUM_TIMEOUT_SECONDS", "20"))
storage_lock = threading.Lock()


@dataclass(frozen=True)
class MachineReading:
    machine_id: int
    status: str
    minutes_remaining: Optional[int]
    observed_at: str
    error: Optional[str] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_storage() -> None:
    OBSERVATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OBSERVATIONS_PATH.touch(exist_ok=True)


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

    free_nodes = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'machine-price__total__value') and normalize-space()='FREE']",
    )
    if free_nodes:
        return ("available", None)

    done_nodes = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'machine-state')]//h1[normalize-space()='Done']",
    )
    if done_nodes:
        return ("available", None)

    ready_nodes = driver.find_elements(
        By.XPATH,
        "//*[contains(normalize-space(), 'Available') or contains(normalize-space(), 'Start') or normalize-space()='FREE']",
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
    with storage_lock:
        with OBSERVATIONS_PATH.open("a", encoding="utf-8") as handle:
            for reading in readings:
                record = asdict(reading)
                record["url"] = machines[reading.machine_id]
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_observations() -> list[dict]:
    if not OBSERVATIONS_PATH.exists():
        return []

    records = []
    with storage_lock:
        with OBSERVATIONS_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


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
    latest = {}
    for row in read_observations():
        current = latest.get(row["machine_id"])
        if current is None or row["observed_at"] > current["observed_at"]:
            latest[row["machine_id"]] = row

    return [latest[machine_id] for machine_id in sorted(latest)]


def observation_history(limit: int = 500) -> list[dict]:
    rows = sorted(
        read_observations(),
        key=lambda row: (row["observed_at"], row["machine_id"]),
        reverse=True,
    )
    return rows[:limit]


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
