"use strict";

const MODE_LABELS = {
  SSB: "SSB",
  FT8: "FT8",
  FT4: "FT4",
  CW: "CW",
  RTTY: "RTTY",
  PSK31: "PSK31",
  PSK63: "PSK63",
  OTHER_DIGITAL: "Other Digital",
};
const MODE_ORDER = ["SSB", "FT8", "FT4", "CW", "RTTY", "PSK31", "PSK63", "OTHER_DIGITAL"];
const BAND_ORDER = ["80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"];

const state = {
  modes: new Set(MODE_ORDER),
  bands: new Set(BAND_ORDER),
  candidates: [],
};

function buildFilterCheckboxes(containerId, items, labels, activeSet, onChange) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  for (const item of items) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = activeSet.has(item);
    input.addEventListener("change", () => {
      if (input.checked) activeSet.add(item);
      else activeSet.delete(item);
      onChange();
    });
    label.appendChild(input);
    label.append(" " + (labels ? labels[item] : item));
    container.appendChild(label);
  }
}

function scoreClass(total) {
  if (total >= 70) return "score-high";
  if (total >= 40) return "score-mid";
  return "score-low";
}

function fmtAge(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds % 60);
  return `${minutes} min ${rem} s`;
}

function renderCandidates() {
  const tbody = document.getElementById("candidates-body");
  tbody.innerHTML = "";
  const filtered = state.candidates.filter(
    (c) => state.modes.has(c.mode) && state.bands.has(c.band)
  );

  if (filtered.length === 0) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    tr.innerHTML = `<td colspan="8">Žádní kandidáti pro aktuální filtry.</td>`;
    tbody.appendChild(tr);
    return;
  }

  for (const c of filtered) {
    const row = document.createElement("tr");
    row.className = "candidate-row";
    const dxcc = c.dxcc ? `${c.dxcc.name} (${c.dxcc.continent})` : "?";
    const bearing = c.bearing_deg != null ? `${c.bearing_deg}° / ${c.distance_km ?? "?"} km` : "-";
    const sources = c.confirming_sources.join(", ");
    const scoreTotal = c.score ? c.score.total : 0;

    row.innerHTML = `
      <td>${c.callsign}</td>
      <td>${dxcc}</td>
      <td>${c.freq_mhz.toFixed(3)} MHz</td>
      <td>${MODE_LABELS[c.mode] ?? c.mode}</td>
      <td>${fmtAge(c.age_seconds)}</td>
      <td>${sources}</td>
      <td><span class="score-badge ${scoreClass(scoreTotal)}">${scoreTotal}</span></td>
      <td>${bearing}</td>
    `;
    tbody.appendChild(row);

    const reasonsRow = document.createElement("tr");
    reasonsRow.className = "reasons-row";
    const reasons = c.score
      ? c.score.reasons
          .map((r) => `<li><strong>${r.factor}</strong>: ${r.points}/${r.max_points} -- ${r.detail}</li>`)
          .join("")
      : "";
    reasonsRow.innerHTML = `<td colspan="8"><ul class="reasons-list" style="display:none">${reasons}</ul></td>`;
    tbody.appendChild(reasonsRow);

    row.addEventListener("click", () => {
      const list = reasonsRow.querySelector("ul");
      list.style.display = list.style.display === "none" ? "block" : "none";
    });
  }
}

async function postFilters() {
  try {
    const payload = {
      bands: BAND_ORDER.filter((b) => state.bands.has(b)),
      modes: MODE_ORDER.filter((m) => state.modes.has(m)),
    };
    await fetch("/api/filters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.error("postFilters selhalo", err);
  }
}

function onFilterChange() {
  renderCandidates();
  postFilters();
}

async function refreshCandidates() {
  try {
    const res = await fetch("/api/candidates");
    const data = await res.json();
    state.candidates = data.candidates;
    renderCandidates();
  } catch (err) {
    console.error("refreshCandidates selhalo", err);
  }
}

function renderRigStatus(status) {
  const el = document.getElementById("rig-status");
  const rig = status.rig;
  if (!rig) {
    el.textContent = `rig (${status.rig_mode}): nenaladěno`;
    return;
  }
  const call = rig.callsign ? ` -- ${rig.callsign}` : "";
  el.textContent = `rig (${status.rig_mode}): ${(rig.freq_hz / 1e6).toFixed(3)} MHz ${rig.mode}${call}`;
}

function renderDecision(status) {
  const el = document.getElementById("autotune-decision");
  const d = status.last_decision;
  el.textContent = d ? `Poslední rozhodnutí AUTO TUNE: [${d.action}] ${d.reason}` : "";
}

function fillAutotuneForm(status) {
  document.getElementById("at-enabled").checked = status.autotune.enabled;
  document.getElementById("at-hold").checked = status.autotune.hold;
  document.getElementById("at-min-score").value = status.min_score;
  document.getElementById("at-min-hold").value = status.autotune.min_hold_seconds;
  document.getElementById("at-min-delta").value = status.autotune.min_score_delta;
}

let statusLoaded = false;

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();
    renderRigStatus(status);
    renderDecision(status);
    if (!statusLoaded) {
      state.modes = new Set(status.modes);
      state.bands = new Set(status.bands);
      buildFilterCheckboxes("mode-filters", MODE_ORDER, MODE_LABELS, state.modes, onFilterChange);
      buildFilterCheckboxes("band-filters", BAND_ORDER, null, state.bands, onFilterChange);
      fillAutotuneForm(status);
      statusLoaded = true;
      renderCandidates();
    }
  } catch (err) {
    console.error("refreshStatus selhalo", err);
  }
}

document.getElementById("autotune-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const payload = {
    enabled: document.getElementById("at-enabled").checked,
    hold: document.getElementById("at-hold").checked,
    min_score: Number(document.getElementById("at-min-score").value),
    min_hold_seconds: Number(document.getElementById("at-min-hold").value),
    min_score_delta: Number(document.getElementById("at-min-delta").value),
  };
  const res = await fetch("/api/autotune", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const status = await res.json();
  renderRigStatus(status);
  renderDecision(status);
});

refreshStatus();
refreshCandidates();
setInterval(refreshStatus, 5000);
setInterval(refreshCandidates, 5000);
