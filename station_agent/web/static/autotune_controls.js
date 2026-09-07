"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StationAutotuneControls = api;
})(typeof globalThis === "undefined" ? this : globalThis, function () {
  function bind(options) {
    const autoTuneButton = options.document.getElementById("at-enabled-ok");
    const holdButton = options.document.getElementById("at-hold-ok");

    autoTuneButton.addEventListener("click", function () {
      options.clearCandidateSelection();
      options.updateAutotune({ enabled: true, hold: false });
    });
    holdButton.addEventListener("click", function () {
      options.updateAutotune({ enabled: false, hold: true });
    });
  }

  return { bind: bind };
});
