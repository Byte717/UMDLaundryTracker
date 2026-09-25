const grid = document.querySelector("#machine-grid");
const timeline = document.querySelector("#timeline");
const refresh = document.querySelector("#refresh");

function statusText(row) {
  if (!row) return "No checks recorded yet";
  if (row.minutes_remaining !== null && row.minutes_remaining !== undefined) {
    return `${row.minutes_remaining} min remaining`;
  }
  return row.error ? "Could not read status" : "No countdown observed";
}

function render(data) {
  document.querySelector("#occupied-count").textContent = data.summary.occupied_count;
  document.querySelector("#available-count").textContent = data.summary.available_count;
  document.querySelector("#error-count").textContent = data.summary.error_count;
  document.querySelector("#last-seen").textContent = data.summary.last_observed_at
    ? `Last checked ${data.summary.last_observed_at}`
    : "Waiting for first check";

  const byMachine = new Map(data.machines.map((row) => [row.machine_id, row]));
  grid.querySelectorAll(".machine-card").forEach((card) => {
    const id = Number(card.querySelector("h3").textContent.replace("Machine ", ""));
    const row = byMachine.get(id);
    card.className = `machine-card ${row ? row.status : "pending"}`;
    card.querySelector("strong").textContent = row ? row.status : "pending";
    card.querySelector("p").textContent = statusText(row);
  });

  const occupiedRows = data.history.filter((row) => row.status === "occupied");
  timeline.innerHTML = occupiedRows.length
    ? occupiedRows.map((row) => `
        <article>
          <time>${row.observed_at}</time>
          <span>Machine ${row.machine_id}</span>
          <strong>${row.minutes_remaining} min left</strong>
        </article>
      `).join("")
    : '<p class="empty">No occupied readings saved yet.</p>';
}

async function loadStatus() {
  const response = await fetch("/api/status");
  render(await response.json());
}

async function runPoll() {
  refresh.disabled = true;
  refresh.textContent = "Checking...";
  try {
    await fetch("/api/poll", { method: "POST" });
    await loadStatus();
  } finally {
    refresh.disabled = false;
    refresh.textContent = "Refresh";
  }
}

refresh.addEventListener("click", runPoll);
setInterval(loadStatus, 30000);
