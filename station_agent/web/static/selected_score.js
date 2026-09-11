"use strict";

// Rozhodovací logika horního indikátoru skóre (viz index.html
// #selected-score-status a app.js renderSelectedScore). Je oddělená od DOM
// stejně jako autotune_controls.js, aby ji šlo spustit v regresním testu
// pod Node.js (tests/test_web_api.py).
//
// Indikátor pokrývá dva stavy "vybraný kandidát", které v aplikaci existují:
//   1. kandidát, na kterého je rig právě naladěný -- vybral ho AUTO TUNE
//      (AutoTuneEngine.decide -> apply_decision) nebo operátor tlačítkem
//      NALADIT. Jeho skóre backend průběžně přepočítává
//      (app_state._sync_current_score -- tatáž hodnota, se kterou AUTO TUNE
//      porovnává ostatní kandidáty) a GUI ho dostává jako `rig.score`
//      z /api/status;
//   2. kandidát ručně označený kliknutím v tabulce Kandidáti (app.js
//      state.selected), jehož skóre je `score.total` z /api/candidates.
// Nic se nepočítá znovu -- jen se přebírají hodnoty, které už GUI má.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StationSelectedScore = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  // Vrací null, když žádný kandidát v tabulce označený není, jinak
  // {callsign, scoreTotal}. scoreTotal je průběžně přepočítávané
  // `score.total` téhož kandidáta z aktuálního seznamu /api/candidates --
  // stejný zdroj dat jako sloupec Skóre; null znamená, že kandidát skóre
  // (zatím) nemá.
  function resolve(selected, candidates, sameCandidateKey) {
    if (!selected) return null;
    const match = (candidates || []).find((c) => sameCandidateKey(c, selected));
    const scoreTotal = match && match.score && match.score.total != null ? match.score.total : null;
    return { callsign: selected.callsign, scoreTotal: scoreTotal };
  }

  // Vrací null, když rig není naladěný na žádného kandidáta (rig neznámý,
  // nebo jen frekvence/mód bez callsignu -- např. stav přečtený z hardwaru
  // při startu), jinak {callsign, scoreTotal, autotune}. scoreTotal je
  // `rig.score` z /api/status (průběžně přepočítávané backendem), autotune
  // říká, zda je režim AUTO TUNE právě zapnutý (jen pro popisek).
  function resolveTuned(rig, autotune) {
    if (!rig || !rig.callsign) return null;
    return {
      callsign: rig.callsign,
      scoreTotal: rig.score != null ? rig.score : null,
      autotune: !!(autotune && autotune.enabled),
    };
  }

  // Sestaví položky horního indikátoru v pořadí zobrazení. Prázdné pole
  // znamená "nic není vybráno" -> indikátor se skryje. Pokud je ručně
  // označený kandidát totožný s naladěnou stanicí, zobrazí se jen jednou
  // (jako naladěný), aby se v headeru neopakoval stejný callsign.
  function resolveHeader(input) {
    const entries = [];
    const tuned = resolveTuned(input.rig, input.autotune);
    if (tuned) entries.push({ kind: "tuned", ...tuned });
    const selected = resolve(input.selected, input.candidates, input.sameCandidateKey);
    if (selected && !(tuned && input.sameCandidateKey(input.rig, input.selected))) {
      entries.push({ kind: "selected", ...selected });
    }
    return entries;
  }

  return { resolve: resolve, resolveTuned: resolveTuned, resolveHeader: resolveHeader };
});
