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
  // Klíče kandidátů (callsign|freq_hz|mode), u kterých operátor tlačítkem
  // "Důvody skóre" rozbalil detail; nezávislé na výběru pro NALADIT.
  expandedDetails: new Set(),
  presets: [],
  // Poslední `rig` a `autotune` z /api/status -- stanice, na kterou rig
  // naladil AUTO TUNE nebo NALADIT, včetně jejího průběžně přepočítávaného
  // skóre (rig.score). Zdroj dat pro horní indikátor, viz renderSelectedScore.
  rig: null,
  autotune: null,
};

function sameCandidateKey(a, b) {
  return !!a && !!b && a.callsign === b.callsign && a.freq_hz === b.freq_hz && a.mode === b.mode;
}

function candidateKey(c) {
  return `${c.callsign}|${c.freq_hz}|${c.mode}`;
}

function fmtFreqMhz(freqHz) {
  return `${(freqHz / 1e6).toFixed(3)} MHz`;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

function fmtAgeDetailed(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} sekund`;
  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes} minut`;
  }
  const hours = Math.floor(seconds / 3600);
  return `${hours} hodin`;
}

function renderTuneControls() {
  const button = document.getElementById("tune-button");
  const qsoButton = document.getElementById("qso-button");
  const selectedEl = document.getElementById("tune-selected");
  // Pevný pruh nad tabulkou: vždy říká, s čím budou akce pracovat.
  if (state.selected) {
    button.disabled = false;
    qsoButton.disabled = false;
    selectedEl.innerHTML = `Vybraný: <strong>${state.selected.callsign}</strong> · ${fmtFreqMhz(state.selected.freq_hz)} · ${MODE_LABELS[state.selected.mode] ?? state.selected.mode}`;
    selectedEl.classList.add("has-selection");
  } else {
    button.disabled = true;
    qsoButton.disabled = true;
    selectedEl.textContent = "Vybraný kandidát: žádný";
    selectedEl.classList.remove("has-selection");
  }
}

function toggleCandidateDetail(c) {
  const key = candidateKey(c);
  if (state.expandedDetails.has(key)) state.expandedDetails.delete(key);
  else state.expandedDetails.add(key);
  renderCandidates();
}

// Souhrn nad rychlými filtry: kolik kandidátů je právě vidět a kolik
// pásem/módů je aktivních -- bez rozbalování pokročilých filtrů.
function renderFilterSummary(shownCount) {
  const el = document.getElementById("filter-summary");
  const bandsActive = BAND_ORDER.filter((b) => state.bands.has(b)).length;
  const modesActive = MODE_ORDER.filter((m) => state.modes.has(m)).length;
  el.textContent = `Zobrazeno ${shownCount} z ${state.candidates.length} kandidátů · pásma ${bandsActive}/${BAND_ORDER.length} · módy ${modesActive}/${MODE_ORDER.length}`;
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

// Zobrazí průběžně přepočítávané skóre vybraného kandidáta i v horní
// části GUI (header), ne jen v tabulce Kandidáti -- operátor tak vidí
// aktuální skóre bez scrollování, dokud je nějaký kandidát vybraný.
// "Vybraný" je jednak stanice, na kterou rig naladil AUTO TUNE nebo
// NALADIT (state.rig z /api/status, skóre rig.score přepočítává backend
// při každé obnově kandidátů), jednak kandidát označený kliknutím v
// tabulce (state.selected + state.candidates z /api/candidates).
// Volá se z renderRigStatus() (každý refresh /api/status i odpověď na
// NALADIT/AUTO TUNE) a z renderCandidates() (každý refresh /api/candidates
// i změna výběru); rozhodnutí "co zobrazit" dělá
// StationSelectedScore.resolveHeader (selected_score.js), aby bylo testovatelné.
function renderSelectedScore() {
  const el = document.getElementById("selected-score-status");
  const entries = StationSelectedScore.resolveHeader({
    rig: state.rig,
    autotune: state.autotune,
    selected: state.selected,
    candidates: state.candidates,
    sameCandidateKey,
  });
  el.hidden = entries.length === 0;
  if (entries.length === 0) {
    el.textContent = "";
    return;
  }
  el.innerHTML = entries
    .map((entry) => {
      const label = entry.kind === "tuned"
        ? (entry.autotune ? "AUTO TUNE" : "Naladěno")
        : "Vybraný kandidát";
      const score = entry.scoreTotal == null
        ? ""
        : ` <span class="score-badge ${scoreClass(entry.scoreTotal)}">${entry.scoreTotal}</span>`;
      return `<span class="selected-score-entry selected-score-${entry.kind}">${label}: <strong>${entry.callsign}</strong>${score}</span>`;
    })
    .join("");
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
  renderSelectedScore();
  renderFilterSummary(filtered.length);

  if (filtered.length === 0) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    tr.innerHTML = `<td colspan="9">Žádní kandidáti pro aktuální filtry.</td>`;
    tbody.appendChild(tr);
    renderTuneControls();
    return;
  }

  for (const c of filtered) {
    const row = document.createElement("tr");
    const isSelected = sameCandidateKey(state.selected, c);
    const isExpanded = state.expandedDetails.has(candidateKey(c));
    row.className = "candidate-row" + (isSelected ? " selected" : "");
    const country = c.country || (c.dxcc && c.dxcc.name) || "?";
    const dxcc = c.dxcc && c.dxcc.continent ? `${country} (${c.dxcc.continent})` : country;
    const bearing = c.bearing_deg != null
      ? `${c.bearing_deg}° / ${c.distance_km ?? "?"} km`
      : "-";
    // V buňce jen zkratky zdrojů; plná uživatelská jména (i technické ID)
    // zůstávají v tooltipu, aby řádek nevytlačovaly.
    const sourcesShort = c.confirming_sources.map(shortSourceName).join(", ");
    const sourcesFull = c.confirming_sources
      .map((name) => `${friendlySourceName(name)} (${name})`)
      .join(", ");
    const scoreTotal = c.score ? c.score.total : 0;
    const ageTooltip = `Spotting je staré ${fmtAgeDetailed(c.age_seconds)}`;
    const bearingTooltip = c.bearing_deg != null
      ? `Azimuth: ${c.bearing_deg}°, Vzdálenost: ${c.distance_km ?? "?"} km`
      : "Bearing není dostupný (QTH není nastaveno)";

    row.innerHTML = `
      <td><strong>${c.callsign}</strong></td>
      <td>${dxcc}</td>
      <td title="Pracovní frekvence">${c.freq_mhz.toFixed(3)} MHz</td>
      <td title="Druh modulace">${MODE_LABELS[c.mode] ?? c.mode}</td>
      <td title="${ageTooltip}">${fmtAge(c.age_seconds)}</td>
      <td title="Zdroje: ${sourcesFull}">${sourcesShort}</td>
      <td><span class="score-badge ${scoreClass(scoreTotal)}" title="Skóre: ${scoreTotal}/100">${scoreTotal}</span></td>
      <td title="${bearingTooltip}">${bearing}</td>
      <td><button type="button" class="detail-toggle" aria-expanded="${isExpanded}" title="Zobrazit důvody skóre a reliabilitu zdroje">${isExpanded ? "Skrýt důvody" : "Důvody skóre"}</button></td>
    `;
    tbody.appendChild(row);

    const reasonsRow = document.createElement("tr");
    reasonsRow.className = "reasons-row";
    const reasons = c.score
      ? c.score.reasons
          .map((r) => `<li><strong>${r.factor}</strong>: ${r.points}/${r.max_points} -- ${r.detail}</li>`)
          .join("")
      : "";
    const reliabilityPercent = c.reliability_percent != null
      ? `${c.reliability_percent.toFixed(1)} %`
      : "neznámá (provider ji neposkytl)";
    const reasonsDisplay = isExpanded ? "block" : "none";
    reasonsRow.innerHTML = `<td colspan="9"><div class="candidate-detail" style="display:${reasonsDisplay}">
      <div class="candidate-detail-reliability">Reliabilita DX clusteru: ${reliabilityPercent} (procento správnosti spotů ze zdroje)</div>
      <div class="candidate-detail-sources">Zdroje: ${sourcesFull}</div>
      <div style="font-size: 0.85rem; margin-top: 0.3rem;"><strong>Rozpad skóre:</strong></div>
      <ul class="reasons-list">${reasons}</ul>
    </div></td>`;
    tbody.appendChild(reasonsRow);

    // Klik na řádek = výběr pro akce; tlačítko v řádku = detail skóre.
    // Klik na tlačítko nesmí zároveň měnit výběr.
    row.querySelector(".detail-toggle").addEventListener("click", (ev) => {
      ev.stopPropagation();
      toggleCandidateDetail(c);
    });
    row.addEventListener("click", () => selectCandidate(c));
  }

  renderTuneControls();
}

async function postFilters() {
  try {
    const payload = {
      bands: BAND_ORDER.filter((b) => state.bands.has(b)),
      modes: MODE_ORDER.filter((m) => state.modes.has(m)),
      exclude_worked_qsos: document.getElementById("exclude-worked-qsos").checked,
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
  // Stejná odpověď /api/status (i z /api/tune a /api/autotune) krmí horní
  // indikátor skóre naladěné stanice -- žádný další dotaz ani výpočet.
  state.rig = rig || null;
  state.autotune = status.autotune || null;
  renderSelectedScore();
  const liveBadge = status.rig_mode === "live" ? `<span class="live-badge">LIVE</span>` : "";
  if (!rig) {
    el.innerHTML = `<span class="rig-primary">nenaladěno</span> ${liveBadge}`;
    return;
  }
  const freqMode = `${(rig.freq_hz / 1e6).toFixed(3)} MHz · ${rig.mode}`;
  const call = rig.callsign ? ` · ${rig.callsign}` : "";
  // Stanice je naladěná (callsign known), ale ani offline tabulka, ani
  // QRZ fallback zemi nedohledaly -- nic se nevymýšlí, jasně se to označí
  // "?" stejně jako u řádku kandidáta (viz `country` výše), místo aby se
  // celý údaj o zemi mlčky vynechal.
  const country = rig.callsign ? (rig.country || "?") : "";
  const path = rig.bearing_deg == null
    ? ""
    : ` · ${rig.bearing_deg.toFixed(0)}° · ${rig.distance_km == null ? "?" : rig.distance_km.toFixed(0)} km`;
  const secondary = rig.callsign ? `${country}${path}` : "";
  el.innerHTML = `<span class="rig-primary">${freqMode}${call}</span> ${liveBadge}`
    + (secondary ? `<span class="rig-secondary">${secondary}</span>` : "");
}

// Slovní závěr z hodinového výhledu pásma (0..1) -- stejné hranice jako
// barvy skóre, aby operátor četl jednu stupnici.
function propagationVerdict(quality) {
  if (quality == null || Number.isNaN(Number(quality))) return null;
  const q = Number(quality);
  if (q >= 0.7) return "dobré";
  if (q >= 0.4) return "střední";
  return "slabé";
}

function fmtObservedAge(observedAt) {
  if (observedAt == null) return "čas měření neznámý";
  const ageSeconds = Math.max(0, Date.now() / 1000 - observedAt);
  return `měřeno před ${fmtAgeDetailed(ageSeconds)}`;
}

function renderPropagation(status) {
  const el = document.getElementById("propagation-status");
  const p = status.propagation || {};
  // Hlavička: krátký kontrolní indikátor se stavem a stářím ověření.
  if (!p.verified || p.kp == null) {
    el.textContent = "! Kp: neověřeno";
    el.title = p.error ? `Zdroj selhal: ${p.error}` : "Propagační data nejsou ověřena; model se nepoužívá.";
  } else {
    el.textContent = "● " + `Kp: ${p.kp.toFixed(1)}`
      + (p.solar_flux == null ? "" : ` · SFI ${p.solar_flux.toFixed(1)}`)
      + ` · ${fmtObservedAge(p.observed_at)}`;
    el.title = `Zdroj: ${p.source || "neznámý"}`;
  }

  const summary = document.getElementById("propagation-summary");
  const bands = document.getElementById("propagation-bands");
  const detail = document.getElementById("propagation-detail");
  if (!p.verified || p.kp == null || p.solar_flux == null) {
    summary.textContent = "Propagační data nejsou ověřena; model se nepoužívá.";
    bands.replaceChildren();
    detail.textContent = p.error ? `Zdroj selhal: ${p.error}` : "Zdroj není dostupný.";
    return;
  }

  // Výchozí pohled: závěr pro pásmo, na kterém je rig právě naladěný
  // (rig.band z /api/status); bez naladěného pásma se ukáže jen Kp/SFI.
  const currentBand = state.rig && state.rig.band ? state.rig.band : null;
  const quality = currentBand && p.band_quality ? p.band_quality[currentBand] : null;
  const verdict = propagationVerdict(quality);
  const conditions = currentBand && verdict
    ? `Podmínky (${currentBand}): ${verdict} (${Math.round(Number(quality) * 100)} %)`
    : currentBand
      ? `Podmínky (${currentBand}): výhled není k dispozici`
      : "Podmínky: rig není naladěn na známé pásmo";
  summary.textContent = `${conditions} · Kp ${p.kp.toFixed(1)} · SFI ${p.solar_flux.toFixed(1)} · ${fmtObservedAge(p.observed_at)} · ${p.source || "zdroj neznámý"}`;
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

// Stav vždy jako ikona + text (barva je jen doplněk, ne jediný nosič
// informace). Významy `ok`/`pending`/`backoff`/`error` z API se nemění.
const SOURCE_STATUS_LABELS = {
  ok: "● V pořádku",
  pending: "◌ Inicializuji",
  error: "! Vyžaduje pozornost",
  backoff: "◐ Opakuji",
};

function sourceStatusLabel(s) {
  const base = SOURCE_STATUS_LABELS[s.status] ?? s.status;
  if (s.status === "backoff" && s.backoff_remaining_seconds != null) {
    return `${base} za ${fmtAge(s.backoff_remaining_seconds)}`;
  }
  return base;
}

function shortSourceName(name) {
  if (name === "rbn") return "RBN";
  if (name === "pskreporter") return "PSK";
  if (name === "dx_cluster") return "DXC";
  if (name.startsWith("dx_cluster_")) {
    return `DXC·${name.slice("dx_cluster_".length).toUpperCase()}`;
  }
  return name;
}

const SOURCE_STATUS_DESCRIPTIONS = {
  ok: "Zdroj funguje a poskytuje data",
  pending: "Zdroj se inicializuje (první spuštění)",
  error: "Zdroj momentálně nefunguje (byl pokus o opětovné připojení)",
  backoff: "Zdroj je dočasně vypnutý, čeká na další pokus",
};

// Technická jména z config.yaml (klíč v `sources:`) přeložená na jméno
// srozumitelné operátorovi; technické ID zůstává jen v tooltipu/detailu.
// Neznámý prefix (vlastní/exotický zdroj) se zobrazí beze změny.
function friendlySourceName(name) {
  if (name === "rbn") return "Reverse Beacon Network";
  if (name === "pskreporter") return "PSK Reporter";
  if (name === "dx_cluster") return "DX Cluster";
  if (name.startsWith("dx_cluster_")) {
    const suffix = name.slice("dx_cluster_".length);
    return `DX Cluster (${suffix.toUpperCase()})`;
  }
  return name;
}

function renderSourcesStatus(status) {
  const el = document.getElementById("sources-status");
  const summaryEl = document.getElementById("sources-summary");
  const sources = status.sources || [];
  if (sources.length === 0) {
    el.textContent = "";
    summaryEl.textContent = "žádné zdroje";
    return;
  }
  const okCount = sources.filter((s) => s.status === "ok").length;
  const worstOrder = ["error", "backoff", "pending", "ok"];
  const worst = sources.reduce(
    (acc, s) => (worstOrder.indexOf(s.status) < worstOrder.indexOf(acc) ? s.status : acc),
    "ok"
  );
  // Souhrn ukazuje nejhorší stav; konkrétní chyba se nikdy neskrývá --
  // je v rozbaleném detailu i v tooltipu každého zdroje.
  const summaryIcon = worst === "ok" ? "●" : worst === "pending" ? "◌" : worst === "backoff" ? "◐" : "!";
  summaryEl.textContent = `${summaryIcon} ${okCount}/${sources.length} v pořádku`;
  summaryEl.className = "sources-worst-" + worst;
  summaryEl.title = sources
    .map((s) => `${friendlySourceName(s.name)}: ${sourceStatusLabel(s)}${s.last_error && s.status !== "ok" ? ` (${s.last_error})` : ""}`)
    .join("\n");
  el.innerHTML = sources
    .map((s) => {
      const label = sourceStatusLabel(s);
      const desc = SOURCE_STATUS_DESCRIPTIONS[s.status] || "";
      const displayName = friendlySourceName(s.name);
      const parts = [`${displayName} (${s.name}): ${label}`];
      if (s.last_success_age_seconds != null) {
        parts.push(`poslední data před ${fmtAgeDetailed(s.last_success_age_seconds)}`);
      }
      if (s.backoff_remaining_seconds != null) {
        parts.push(`pokus za ${fmtAge(s.backoff_remaining_seconds)}`);
      }
      if (s.last_error && (s.status === "error" || s.status === "backoff")) {
        parts.push(`chyba: ${s.last_error}`);
      }
      const fullTooltip = desc + (parts.length > 1 ? " -- " + parts.slice(1).join(" -- ") : "");
      const cls = "source-badge source-" + s.status;
      const errorNote = s.last_error && (s.status === "error" || s.status === "backoff")
        ? `<span class="source-error-note">${escapeHtml(s.last_error)}</span>`
        : "";
      return `<span class="${cls}" title="${escapeHtml(fullTooltip)}">${displayName}: ${label}${errorNote}</span>`;
    })
    .join(" ");
}

function renderLog4OMStatus(status) {
  const el = document.getElementById("log4om-status");
  const verification = status.log4om_verification || {};
  if (!verification.configured) {
    el.textContent = "";
    return;
  }
  if (!verification.filter_enabled) {
    el.textContent = "◌ Vypnuta (filtr nepracuje)";
    el.title = "Vypnuté filtrování znamená, že již hotové QSO nejsou skrývána v seznamu kandidátů";
    return;
  }
  if (verification.verified) {
    el.textContent = "● Zapnuta";
    el.title = `Připojení Log4OM2: ${verification.diagnostic}`;
    return;
  }
  el.textContent = `! Vyžaduje pozornost -- ${verification.diagnostic}`;
  el.title = "Filtrování již hotových QSO momentálně nefunguje. Ostatní funkce pokračují normálně.";
}

function renderDecision(status) {
  const el = document.getElementById("autotune-decision");
  const d = status.last_decision;
  if (!d) {
    el.textContent = "";
    return;
  }
  // Titulek podle výsledku (TuneDecision.action: "TUNE" | "NONE" | "ERROR"):
  // naladění vs. důvod, proč se právě neladí; chyba ladění se pojmenuje zvlášť.
  const action = String(d.action || "").toUpperCase();
  const title = action === "TUNE"
    ? "Poslední naladění"
    : action === "ERROR" ? "Naladění selhalo" : "Proč se nyní neladí";
  el.replaceChildren();
  el.className = "decision decision-" + action.toLowerCase();
  const titleEl = document.createElement("strong");
  titleEl.className = "decision-title";
  titleEl.textContent = title;
  const reasonEl = document.createElement("span");
  reasonEl.className = "decision-reason";
  reasonEl.textContent = d.reason;
  el.append(titleEl, reasonEl);
  el.title = `Poslední rozhodnutí AUTO TUNE (${d.action}), zobrazeno ${new Date().toLocaleTimeString("cs-CZ")}`;
}

function fillAutotuneForm(status) {
  document.getElementById("at-min-score").value = status.min_score;
  document.getElementById("at-min-hold").value = status.autotune.min_hold_seconds;
  document.getElementById("at-min-delta").value = status.autotune.min_score_delta;
}

// AUTO TUNE a HOLD jsou vzájemně výlučné (backend to vynucuje taky, viz
// POST /api/autotune) -- ovládací prvky i odpočet AUTO TUNE se synchronizují se
// stavem backendu při každém refreshi statusu i hned po NALADIT/uložení
// formuláře, aby GUI nikdy neukazovalo stav, který neodpovídá backendu
// (viz BUG P4/P5 -- ruční NALADIT vypíná AUTO TUNE a zapíná HOLD).
let autotuneCountdownBase = null; // {remainingSeconds, capturedAtMs}
let autotuneModeState = { enabled: false, hold: false };

function renderAutotuneState(status) {
  autotuneModeState = {
    enabled: status.autotune.enabled,
    hold: status.autotune.hold,
  };
  document.getElementById("at-enabled-control").classList.toggle("active", autotuneModeState.enabled);
  document.getElementById("at-hold-control").classList.toggle("active", autotuneModeState.hold);
  if (status.autotune.enabled && status.autotune.autotune_remaining_seconds != null) {
    autotuneCountdownBase = { remainingSeconds: status.autotune.autotune_remaining_seconds, capturedAtMs: Date.now() };
  } else {
    autotuneCountdownBase = null;
  }
  renderHoldCountdown();
}

// Jeden dominantní stavový pruh v sekci AUTO TUNE + zrcadlo v hlavičce
// (karta AUTO TUNE), aby byl režim vidět i bez scrollování.
function renderHoldCountdown() {
  const el = document.getElementById("at-hold-countdown");
  const headerEl = document.getElementById("autotune-status");
  const setHeader = (icon, text, mode) => {
    headerEl.textContent = `${icon} ${text}`;
    headerEl.className = "autotune-status autotune-status-" + mode;
  };
  if (autotuneModeState.hold) {
    el.textContent = "HOLD aktivní — ruční ladění";
    el.className = "hold-countdown hold-countdown-hold";
    setHeader("◐", "HOLD · ruční ladění", "hold");
    return;
  }
  if (!autotuneModeState.enabled) {
    el.textContent = "AUTO TUNE vypnuto";
    el.className = "hold-countdown hold-countdown-off";
    setHeader("◌", "Vypnuto", "off");
    return;
  }
  el.className = "hold-countdown hold-countdown-on";
  if (!autotuneCountdownBase) {
    el.textContent = "AUTO TUNE aktivní";
    setHeader("●", "Aktivní", "on");
    return;
  }
  const elapsedSeconds = (Date.now() - autotuneCountdownBase.capturedAtMs) / 1000;
  const remaining = Math.max(0, autotuneCountdownBase.remainingSeconds - elapsedSeconds);
  el.textContent = `AUTO TUNE aktivní -- další vyhodnocení za ${fmtAge(remaining)}`;
  setHeader("●", `Aktivní · další za ${fmtAge(remaining)}`, "on");
}

// Připnuté záhlaví tabulky kandidátů musí sedět pod připnutou hlavičkou
// aplikace, jejíž výška závisí na šířce okna -- proměnnou drží JS.
function syncHeaderHeight() {
  const header = document.getElementById("app-header");
  if (!header) return; // po "Ukončit" je hlavička odstraněná
  document.documentElement.style.setProperty("--app-header-height", `${header.offsetHeight}px`);
}

let statusLoaded = false;

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();
    renderRigStatus(status);
    renderSourcesStatus(status);
    renderLog4OMStatus(status);
    renderPropagation(status);
    renderDecision(status);
    renderAutotuneState(status);
    const log4omFilter = document.getElementById("exclude-worked-qsos");
    log4omFilter.checked = Boolean(status.log4om_verification.filter_enabled);
    log4omFilter.disabled = !status.log4om_verification.configured;
    document.getElementById("log4om-filter-group").hidden = !status.log4om_verification.configured;
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

document.getElementById("exclude-worked-qsos").addEventListener("change", async () => {
  await postFilters();
  await refreshCandidates();
  await refreshStatus();
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
      item.textContent = `Pásmo: ${event.band} | Čas: ${formatTimestamp(event.ts)} | Odlišné stanice: ${event.station_count} | Změna: ${event.station_count_change >= 0 ? "+" : ""}${event.station_count_change} | Použitý práh: ${event.threshold} | Důvod: ${event.reason}`;
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

async function updateAutotune(modeOverride = {}) {
  const payload = {
    enabled: autotuneModeState.enabled,
    hold: autotuneModeState.hold,
    min_score: Number(document.getElementById("at-min-score").value),
    min_hold_seconds: Number(document.getElementById("at-min-hold").value),
    min_score_delta: Number(document.getElementById("at-min-delta").value),
    ...modeOverride,
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

// Každé OK aktivuje zvolený režim a současně vypne druhý. Samostatný binder
// umožňuje tentýž skutečný click-handler spustit i v regresním testu.
StationAutotuneControls.bind({ document, clearCandidateSelection, updateAutotune });
for (const id of ["at-min-score", "at-min-hold", "at-min-delta"]) {
  document.getElementById(id).addEventListener("change", () => updateAutotune());
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

syncHeaderHeight();
window.addEventListener("resize", syncHeaderHeight);
if (typeof ResizeObserver !== "undefined") {
  new ResizeObserver(syncHeaderHeight).observe(document.getElementById("app-header"));
}

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
