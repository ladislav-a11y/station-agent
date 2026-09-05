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
const BAND_ORDER = ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"];

const state = {
  modes: new Set(MODE_ORDER),
  bands: new Set(BAND_ORDER),
  candidates: [],
  selected: null, // {callsign, freq_hz, mode} vybraného kandidáta pro NALADIT
  presets: [],
};

function sameCandidateKey(a, b) {
  return !!a && !!b && a.callsign === b.callsign && a.freq_hz === b.freq_hz && a.mode === b.mode;
}

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

function renderTuneControls() {
  const button = document.getElementById("tune-button");
  const qsoButton = document.getElementById("qso-button");
  const selectedEl = document.getElementById("tune-selected");
  if (state.selected) {
    button.disabled = false;
    qsoButton.disabled = false;
    selectedEl.textContent = `Vybráno: ${state.selected.callsign} -- ${(state.selected.freq_hz / 1e6).toFixed(3)} MHz ${state.selected.mode}`;
  } else {
    button.disabled = true;
    qsoButton.disabled = true;
    selectedEl.textContent = "Nevybrán žádný kandidát.";
  }
}

function selectCandidate(c) {
  state.selected = sameCandidateKey(state.selected, c)
    ? null
    : { callsign: c.callsign, freq_hz: c.freq_hz, mode: c.mode, band: c.band, bearing_deg: c.bearing_deg };
  renderCandidates();
  renderTuneControls();
}

function clearCandidateSelection() {
  if (!state.selected) return;
  state.selected = null;
  renderCandidates();
  renderTuneControls();
}

function renderCandidates() {
  const tbody = document.getElementById("candidates-body");
  tbody.innerHTML = "";
  const filtered = state.candidates.filter(
    (c) => state.modes.has(c.mode) && state.bands.has(c.band)
  );

  // Pokud vybraný kandidát mezi aktuálně zobrazenými (např. po refreshi
  // nebo změně filtrů) už není, výběr zrušíme -- tlačítko NALADIT nesmí
  // zůstat aktivní pro kandidáta, který v seznamu už neexistuje.
  if (state.selected && !filtered.some((c) => sameCandidateKey(c, state.selected))) {
    state.selected = null;
  }

  if (filtered.length === 0) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    tr.innerHTML = `<td colspan="8">Žádní kandidáti pro aktuální filtry.</td>`;
    tbody.appendChild(tr);
    renderTuneControls();
    return;
  }

  for (const c of filtered) {
    const row = document.createElement("tr");
    const isSelected = sameCandidateKey(state.selected, c);
    row.className = "candidate-row" + (isSelected ? " selected" : "");
    const country = c.country || (c.dxcc && c.dxcc.name) || "?";
    const dxcc = c.dxcc && c.dxcc.continent ? `${country} (${c.dxcc.continent})` : country;
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
    const reasonsDisplay = isSelected ? "block" : "none";
    reasonsRow.innerHTML = `<td colspan="8"><ul class="reasons-list" style="display:${reasonsDisplay}">${reasons}</ul></td>`;
    tbody.appendChild(reasonsRow);

    row.addEventListener("click", () => selectCandidate(c));
  }

  renderTuneControls();
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
  document.getElementById("filter-preset").value = "";
  renderCandidates();
  postFilters();
}

function buildPresetSelect(presets) {
  state.presets = presets || [];
  const select = document.getElementById("filter-preset");
  for (const preset of state.presets) {
    const option = document.createElement("option");
    option.value = preset.key;
    option.textContent = preset.label;
    select.appendChild(option);
  }
  select.addEventListener("change", () => {
    const preset = state.presets.find((p) => p.key === select.value);
    if (!preset) return;
    state.bands = new Set(preset.bands);
    state.modes = new Set(preset.modes);
    buildFilterCheckboxes("mode-filters", MODE_ORDER, MODE_LABELS, state.modes, onFilterChange);
    buildFilterCheckboxes("band-filters", BAND_ORDER, null, state.bands, onFilterChange);
    renderCandidates();
    postFilters();
  });
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
  // Stanice je naladěná (callsign známý), ale ani offline tabulka, ani
  // QRZ fallback zemi nedohledaly -- nic se nevymýšlí, jasně se to označí
  // "?" stejně jako u řádku kandidáta (viz `country` výše), místo aby se
  // celý údaj o zemi mlčky vynechal.
  const country = rig.callsign ? ` -- ${rig.country || "?"}` : "";
  const path = rig.bearing_deg == null ? "" : ` -- ${rig.bearing_deg.toFixed(0)}° / ${rig.distance_km == null ? "?" : rig.distance_km.toFixed(0)} km`;
  el.textContent = `rig (${status.rig_mode}): ${(rig.freq_hz / 1e6).toFixed(3)} MHz ${rig.mode}${call}${country}${path}`;
}

function renderPropagation(status) {
  const el = document.getElementById("propagation-status");
  const p = status.propagation || {};
  el.textContent = p.kp == null ? "Kp: nedostupné" : `Kp: ${p.kp.toFixed(1)} (${p.source || "zdroj"})`;

  const summary = document.getElementById("propagation-summary");
  const bands = document.getElementById("propagation-bands");
  const detail = document.getElementById("propagation-detail");
  if (p.kp == null || p.solar_flux == null) {
    summary.textContent = "Aktuální Kp a SFI nejsou dostupné; scoring používá pozorovanou aktivitu spotů.";
    bands.replaceChildren();
    detail.textContent = "";
    return;
  }

  const observed = p.observed_at == null
    ? "čas neznámý"
    : new Date(p.observed_at * 1000).toLocaleString("cs-CZ");
  summary.textContent = `Kp ${p.kp.toFixed(1)} • SFI ${p.solar_flux.toFixed(1)} • ${p.source || "zdroj neznámý"} • ${observed}`;
  bands.replaceChildren();
  Object.entries(p.band_quality || {}).forEach(([band, quality]) => {
    const item = document.createElement("span");
    item.className = "propagation-band";
    const percent = Math.round(Number(quality) * 100);
    item.textContent = `${band}: ${percent} %`;
    item.title = `Transparentní hodinový výhled pro ${band}: ${percent} %`;
    bands.appendChild(item);
  });
  detail.textContent = p.explanation || "";
}

const SOURCE_STATUS_LABELS = {
  ok: "OK",
  pending: "pending",
  error: "chyba",
  backoff: "backoff (429)",
};

function renderSourcesStatus(status) {
  const el = document.getElementById("sources-status");
  const sources = status.sources || [];
  if (sources.length === 0) {
    el.textContent = "";
    return;
  }
  el.innerHTML = sources
    .map((s) => {
      const label = SOURCE_STATUS_LABELS[s.status] ?? s.status;
      const parts = [`${s.name}: ${label}`];
      if (s.last_success_age_seconds != null) {
        parts.push(`data stará ${fmtAge(s.last_success_age_seconds)}`);
      }
      if (s.backoff_remaining_seconds != null) {
        parts.push(`další pokus za ${fmtAge(s.backoff_remaining_seconds)}`);
      }
      if (s.last_error && (s.status === "error" || s.status === "backoff")) {
        parts.push(s.last_error);
      }
      const cls = "source-badge source-" + s.status;
      return `<span class="${cls}" title="${parts.join(" -- ")}">${parts.join(" -- ")}</span>`;
    })
    .join(" ");
}

function renderDecision(status) {
  const el = document.getElementById("autotune-decision");
  const d = status.last_decision;
  el.textContent = d ? `Poslední rozhodnutí AUTO TUNE: [${d.action}] ${d.reason}` : "";
}

function fillAutotuneForm(status) {
  document.getElementById("at-min-score").value = status.min_score;
  document.getElementById("at-min-hold").value = status.autotune.min_hold_seconds;
  document.getElementById("at-min-delta").value = status.autotune.min_score_delta;
}

// AUTO TUNE a HOLD jsou vzájemně výlučné (backend to vynucuje taky, viz
// POST /api/autotune) -- checkboxy i odpočet AUTO TUNE se synchronizují se
// stavem backendu při každém refreshi statusu i hned po NALADIT/uložení
// formuláře, aby GUI nikdy neukazovalo stav, který neodpovídá backendu
// (viz BUG P4/P5 -- ruční NALADIT vypíná AUTO TUNE a zapíná HOLD).
let autotuneCountdownBase = null; // {remainingSeconds, capturedAtMs}

function renderAutotuneState(status) {
  document.getElementById("at-enabled").checked = status.autotune.enabled;
  document.getElementById("at-hold").checked = status.autotune.hold;
  if (status.autotune.enabled && status.autotune.autotune_remaining_seconds != null) {
    autotuneCountdownBase = { remainingSeconds: status.autotune.autotune_remaining_seconds, capturedAtMs: Date.now() };
  } else {
    autotuneCountdownBase = null;
  }
  renderHoldCountdown();
}

function renderHoldCountdown() {
  const el = document.getElementById("at-hold-countdown");
  if (document.getElementById("at-hold").checked) {
    el.textContent = "HOLD aktivní";
    return;
  }
  if (!document.getElementById("at-enabled").checked) {
    // Ani AUTO TUNE, ani HOLD nejsou zapnuté -- rocker switch samotný to
    // nemusí být na první pohled zřejmé (žádný přepínač nemá "checked"),
    // takže stav musí být vyjádřen i textem.
    el.textContent = "AUTO TUNE vypnuto";
    return;
  }
  if (!autotuneCountdownBase) {
    el.textContent = "AUTO TUNE aktivní";
    return;
  }
  const elapsedSeconds = (Date.now() - autotuneCountdownBase.capturedAtMs) / 1000;
  const remaining = Math.max(0, autotuneCountdownBase.remainingSeconds - elapsedSeconds);
  el.textContent = `AUTO TUNE aktivní -- další ladění za ${fmtAge(remaining)}`;
}

let statusLoaded = false;

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();
    renderRigStatus(status);
    renderSourcesStatus(status);
    renderPropagation(status);
    renderDecision(status);
    renderAutotuneState(status);
    if (!statusLoaded) {
      state.modes = new Set(status.modes);
      state.bands = new Set(status.bands);
      buildFilterCheckboxes("mode-filters", MODE_ORDER, MODE_LABELS, state.modes, onFilterChange);
      buildFilterCheckboxes("band-filters", BAND_ORDER, null, state.bands, onFilterChange);
      fillAutotuneForm(status);
      buildPresetSelect(status.presets);
      statusLoaded = true;
      renderCandidates();
    }
  } catch (err) {
    console.error("refreshStatus selhalo", err);
  }
}

function renderTuneResult(text, isError) {
  const el = document.getElementById("tune-result");
  el.textContent = text;
  el.className = "tune-result" + (isError ? " tune-error" : " tune-ok");
}

document.getElementById("tune-button").addEventListener("click", async () => {
  const candidate = state.selected;
  if (!candidate) return; // obrana navíc -- tlačítko je bez výběru disabled

  const button = document.getElementById("tune-button");
  button.disabled = true;
  renderTuneResult(`Ladím na ${candidate.callsign}...`, false);
  try {
    const res = await fetch("/api/tune", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(candidate),
    });
    const status = await res.json();
    renderRigStatus(status);
    renderDecision(status);
    renderAutotuneState(status);
    state.selected = null;
    renderCandidates();
    const reason = status.last_decision ? status.last_decision.reason : status.error;
    renderTuneResult(reason || (res.ok ? "Naladěno." : "Naladění selhalo."), !res.ok);
  } catch (err) {
    console.error("NALADIT selhalo", err);
    renderTuneResult(`Naladění selhalo: ${err}`, true);
  } finally {
    renderTuneControls();
  }
});

document.getElementById("qso-button").addEventListener("click", async () => {
  const candidate = state.selected;
  if (!candidate) return;
  const res = await fetch("/api/qso/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(candidate),
  });
  renderTuneResult(res.ok ? `QSO ${candidate.callsign} bylo zapsáno do lokální historie.` : "Zápis QSO selhal.", !res.ok);
  if (res.ok) refreshQsoHistory();
});

function formatTimestamp(ts) {
  return new Date(ts * 1000).toLocaleString("cs-CZ");
}

async function refreshNotifications() {
  try {
    const data = await (await fetch("/api/notifications")).json();
    const el = document.getElementById("notifications");
    el.replaceChildren();
    if (!data.band_openings.length) {
      el.textContent = "Žádné notifikace.";
      return;
    }
    for (const event of data.band_openings) {
      const item = document.createElement("div");
      item.textContent = `${formatTimestamp(event.ts)} -- ${event.band}: ${event.reason || `nárůst o ${event.station_count_change} na ${event.station_count} odlišných stanic`}`;
      el.appendChild(item);
    }
  } catch (err) { console.error("refreshNotifications selhalo", err); }
}

async function refreshQsoHistory() {
  try {
    const data = await (await fetch("/api/qso/history")).json();
    const el = document.getElementById("qso-history");
    el.replaceChildren();
    if (!data.history.length) {
      el.textContent = "Historie je prázdná.";
      return;
    }
    for (const qso of data.history) {
      const item = document.createElement("div");
      const bearing = qso.bearing_deg == null ? "bearing neznámý" : `bearing ${qso.bearing_deg.toFixed(1)}°`;
      item.textContent = `${formatTimestamp(qso.ts)} -- ${qso.callsign}, ${(qso.freq_hz / 1e6).toFixed(3)} MHz ${qso.mode}, ${qso.band}, ${bearing}`;
      el.appendChild(item);
    }
  } catch (err) { console.error("refreshQsoHistory selhalo", err); }
}

async function updateAutotune() {
  const payload = {
    enabled: document.getElementById("at-enabled").checked,
    hold: document.getElementById("at-hold").checked,
    min_score: Number(document.getElementById("at-min-score").value),
    min_hold_seconds: Number(document.getElementById("at-min-hold").value),
    min_score_delta: Number(document.getElementById("at-min-delta").value),
  };
  const res = await fetch("/api/autotune", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const status = await res.json();
  renderRigStatus(status); renderDecision(status); renderAutotuneState(status);
}

document.getElementById("autotune-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await updateAutotune();
});

// Klient navíc vynucuje výlučnost hned při klikání (backend viz
// web/server.py POST /api/autotune je vynucuje taky, defense-in-depth) --
// zaškrtnutí jednoho přepínače hned v prohlížeči odškrtne ten druhý, ať
// operátor nikdy neodešle formulář s oběma zapnutými.
document.getElementById("at-enabled").addEventListener("change", (ev) => {
  if (!ev.target.checked) return;
  document.getElementById("at-hold").checked = false;
  // Návrat k automatickému režimu zároveň obnoví výchozí rozložení
  // seznamu: ruční výběr ani jeho rozbalené bodové detaily už nejsou aktivní.
  clearCandidateSelection();
  updateAutotune();
});
document.getElementById("at-hold").addEventListener("change", (ev) => {
  if (!ev.target.checked) return;
  document.getElementById("at-enabled").checked = false;
  renderHoldCountdown();
  updateAutotune();
});
for (const id of ["at-min-score", "at-min-hold", "at-min-delta"]) {
  document.getElementById(id).addEventListener("change", updateAutotune);
}

// Ukončit: zastaví polling i webový server a vyčistí obsah databáze (viz
// web/server.py POST /api/shutdown a _perform_shutdown). Potvrzovací dialog
// chrání před nechtěným kliknutím -- akce je nevratná (smaže historii spotů,
// AUTO TUNE log i QSO historii).
document.getElementById("shutdown-button").addEventListener("click", async () => {
  const confirmed = window.confirm(
    "Opravdu ukončit Station Agenta? Zastaví se polling i webové GUI a vyčistí se obsah databáze station_agent.sqlite3."
  );
  if (!confirmed) return;

  const button = document.getElementById("shutdown-button");
  button.disabled = true;
  button.textContent = "Ukončuji...";
  try {
    await fetch("/api/shutdown", { method: "POST" });
  } catch (err) {
    // Server může spojení zavřít dřív, než se odpověď stihne doručit --
    // to je po odeslání potvrzení očekávané, ne chyba.
    console.debug("Ukončení: spojení se serverem skončilo", err);
  }
  for (const intervalId of refreshIntervalIds) {
    clearInterval(intervalId);
  }
  document.body.innerHTML = '<p class="shutdown-message">Station Agent byl ukončen. Toto okno můžeš zavřít.</p>';
});

refreshStatus();
refreshCandidates();
refreshNotifications();
refreshQsoHistory();
const refreshIntervalIds = [
  setInterval(refreshStatus, 5000),
  setInterval(refreshCandidates, 5000),
  setInterval(refreshNotifications, 15000),
  setInterval(refreshQsoHistory, 15000),
  setInterval(renderHoldCountdown, 1000),
];
