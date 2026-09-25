const grid = document.querySelector("#machine-grid");
const timeline = document.querySelector("#timeline");
const refresh = document.querySelector("#refresh");
const lastSeen = document.querySelector("#last-seen");
const usageDialog = document.querySelector("#usage-dialog");
const usageTitle = document.querySelector("#usage-title");
const usageWeek = document.querySelector("#usage-week");
const usageSummary = document.querySelector("#usage-summary");
const usageChart = document.querySelector("#usage-chart");

let lastObservedAt = lastSeen.dataset.observedAt || null;

function statusText(row) {
  if (!row) return "No checks recorded yet";
  if (row.minutes_remaining !== null && row.minutes_remaining !== undefined) {
    return `remaining${row.predicted ? " · estimated" : ""}`;
  }
  return row.error ? "Could not read machine page" : "No countdown observed";
}

function formatLastChecked(value) {
  if (!value) return "Awaiting first check";
  const checkedAt = new Date(value);
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - checkedAt.getTime()) / 1000));

  lastSeen.title = `Last checked ${checkedAt.toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  })}`;

  if (elapsedSeconds < 45) return "Checked just now";
  if (elapsedSeconds < 3600) return `Checked ${Math.floor(elapsedSeconds / 60)} min ago`;
  if (elapsedSeconds < 86400) {
    const hours = Math.floor(elapsedSeconds / 3600);
    return `Checked ${hours} hr${hours === 1 ? "" : "s"} ago`;
  }
  return `Checked ${checkedAt.toLocaleDateString([], { month: "short", day: "numeric" })}`;
}

function updateLastChecked() {
  lastSeen.textContent = formatLastChecked(lastObservedAt);
}

function formatSavedTimestamps() {
  document.querySelectorAll("time[data-timestamp]").forEach((element) => {
    element.textContent = new Date(element.dataset.timestamp).toLocaleString([], {
      dateStyle: "short",
      timeStyle: "short",
    });
  });
}

function updateHistoryCountdowns() {
  document.querySelectorAll(".history-remaining").forEach((element) => {
    const observedAt = new Date(element.dataset.observedAt).getTime();
    const reportedMinutes = Number(element.dataset.minutes);
    if (!Number.isFinite(observedAt) || !Number.isFinite(reportedMinutes)) {
      element.textContent = "No estimate";
      return;
    }
    const endAt = observedAt + reportedMinutes * 60000;
    const remaining = Math.max(0, Math.ceil((endAt - Date.now()) / 60000));
    element.textContent = remaining > 0 ? `${remaining} min left` : "Complete";
    element.classList.toggle("complete", remaining === 0);
  });
}

function render(data) {
  document.querySelector("#occupied-count").textContent = data.summary.occupied_count;
  document.querySelector("#available-count").textContent = data.summary.available_count;
  document.querySelector("#error-count").textContent = data.summary.error_count;
  lastObservedAt = data.summary.last_observed_at || null;
  updateLastChecked();

  const byMachine = new Map(data.machines.map((row) => [row.machine_id, row]));
  grid.querySelectorAll(".machine-card").forEach((card) => {
    const id = Number(card.dataset.machineId);
    const row = byMachine.get(id);
    const status = row ? row.status : "pending";
    card.className = `machine-card ${status}`;
    card.querySelector("strong").textContent = status.replaceAll("_", " ");
    const time = card.querySelector(".machine-time");
    const detail = card.querySelector(".machine-detail");
    if (row && row.minutes_remaining !== null && row.minutes_remaining !== undefined) {
      time.className = "machine-time";
      time.innerHTML = `${row.minutes_remaining}<span>min</span>`;
    } else {
      time.className = "machine-time no-time";
      time.textContent = "—";
    }
    detail.textContent = statusText(row);
  });

  const occupiedRows = data.history.filter((row) => row.status === "occupied");
  timeline.innerHTML = occupiedRows.length
    ? occupiedRows.map((row) => `
        <article>
          <time>${new Date(row.observed_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</time>
          <span>Machine <b>${row.machine_id}</b> was occupied</span>
          <strong class="history-remaining" data-observed-at="${row.observed_at}" data-minutes="${row.minutes_remaining}">${row.minutes_remaining} min left</strong>
        </article>
      `).join("")
    : '<p class="empty">No occupied readings saved yet.</p>';
  updateHistoryCountdowns();
}

function formatUsageDuration(minutes) {
  if (!minutes) return "No occupied time recorded this week";
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (!hours) return `${remainder} min recorded this week`;
  return `${hours} hr${hours === 1 ? "" : "s"}${remainder ? ` ${remainder} min` : ""} recorded this week`;
}

function renderUsage(data) {
  usageTitle.textContent = `Machine ${data.machine_id}`;
  usageWeek.textContent = `Week of ${data.week_start}–${data.week_end}`;
  usageSummary.textContent = formatUsageDuration(data.total_minutes);

  const rows = data.days.map((day) => {
    const segments = day.segments.map((segment) => {
      const left = (segment.start_minute / 1440) * 100;
      const width = Math.max((segment.duration_minutes / 1440) * 100, 0.45);
      const label = `${segment.start_label}–${segment.end_label}${segment.estimated ? " (estimated end)" : ""}`;
      return `<span class="usage-segment${segment.estimated ? " estimated" : ""}" style="left:${left}%;width:${width}%" title="${label}" aria-label="${label}"></span>`;
    }).join("");
    return `
      <div class="usage-row">
        <div class="usage-day"><b>${day.label}</b><span>${day.date}</span></div>
        <div class="usage-track">${segments}</div>
      </div>
    `;
  }).join("");

  usageChart.innerHTML = `
    <div class="usage-axis-row" aria-hidden="true">
      <span></span>
      <div class="usage-axis"><span>12a</span><span>6a</span><span>12p</span><span>6p</span><span>12a</span></div>
    </div>
    ${rows}
  `;
}

async function openUsage(machineId) {
  usageTitle.textContent = `Machine ${machineId}`;
  usageWeek.textContent = "Loading this week…";
  usageSummary.textContent = "";
  usageChart.innerHTML = '<p class="usage-loading">Loading usage history…</p>';
  usageDialog.showModal();

  try {
    const response = await fetch(`/api/machines/${machineId}/usage`);
    if (!response.ok) throw new Error("Could not load usage history");
    renderUsage(await response.json());
  } catch (error) {
    usageChart.innerHTML = '<p class="usage-loading error">Usage history could not be loaded.</p>';
  }
}

async function loadStatus() {
  const response = await fetch("/api/status");
  render(await response.json());
}

async function runPoll() {
  refresh.disabled = true;
  refresh.innerHTML = '<span aria-hidden="true">↻</span> Checking';
  try {
    await fetch("/api/poll", { method: "POST" });
    await loadStatus();
  } finally {
    refresh.disabled = false;
    refresh.innerHTML = '<span aria-hidden="true">↻</span> Refresh';
  }
}

grid.addEventListener("click", (event) => {
  const card = event.target.closest(".machine-card");
  if (card) openUsage(card.dataset.machineId);
});

grid.addEventListener("keydown", (event) => {
  const card = event.target.closest(".machine-card");
  if (card && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    openUsage(card.dataset.machineId);
  }
});

document.querySelector("#usage-close").addEventListener("click", () => usageDialog.close());
usageDialog.addEventListener("click", (event) => {
  if (event.target === usageDialog) usageDialog.close();
});
refresh.addEventListener("click", runPoll);

updateLastChecked();
formatSavedTimestamps();
updateHistoryCountdowns();
setInterval(updateLastChecked, 30000);
setInterval(updateHistoryCountdowns, 15000);
setInterval(loadStatus, 15000);
