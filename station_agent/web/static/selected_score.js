"use strict";

// Rozhodovací logika horního indikátoru skóre vybraného kandidáta (viz
// index.html #selected-score-status a app.js renderSelectedScore). Je
// oddělená od DOM stejně jako autotune_controls.js, aby ji šlo spustit
// v regresním testu pod Node.js (tests/test_web_api.py).
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StationSelectedScore = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  // Vrací null, když žádný kandidát vybraný není (indikátor se skryje),
  // jinak {callsign, scoreTotal}. scoreTotal je průběžně přepočítávané
  // `score.total` téhož kandidáta z aktuálního seznamu /api/candidates --
  // žádný vlastní výpočet, jen stejný zdroj dat jako sloupec Skóre v
  // tabulce Kandidáti; null znamená, že kandidát skóre (zatím) nemá.
  function resolve(selected, candidates, sameCandidateKey) {
    if (!selected) return null;
    const match = (candidates || []).find((c) => sameCandidateKey(c, selected));
    const scoreTotal = match && match.score && match.score.total != null ? match.score.total : null;
    return { callsign: selected.callsign, scoreTotal: scoreTotal };
  }

  return { resolve: resolve };
});
