/* Parent bridge for a single, persistent client-preview document.
   Source and offline exports use this exact controller and message contract. */
(function () {
  "use strict";
  var PG = window.PG;
  var records = new WeakMap();
  var elements = new Set();
  var devices = ["windows", "macos", "linux", "android", "ios"];
  function send(element, record) {
    if (record.ready && element.contentWindow) { element.contentWindow.postMessage(record.pending, "*"); }
  }
  PG.mountClient = function (element, device, board) {
    if (!element || devices.indexOf(device) < 0) { return; }
    var record = records.get(element);
    var pending = { type: "pg-client-command", device: device, board: board || "01-main.html",
      requestId: record ? record.pending.requestId + 1 : 1,
      language: record ? record.pending.language : PG.lang === "ru" ? "ru" : "en" };
    if (record) { record.pending = pending; send(element, record); return; }
    record = { ready: false, pending: pending };
    records.set(element, record); elements.add(element);
    element.setAttribute("sandbox", "allow-scripts allow-same-origin");
    element.name = "pg-client-initial:" + JSON.stringify(pending);
    if (window.PG_CLIENT_RUNTIME_SRCDOC) { element.srcdoc = window.PG_CLIENT_RUNTIME_SRCDOC; }
    else {
      element.src = "client/runtime.html?device=" + encodeURIComponent(pending.device) + "&board=" + encodeURIComponent(pending.board) +
        "&language=" + pending.language + "&thumb=1&embed=1";
    }
  };
  PG.setClientLanguage = function (language) {
    elements.forEach(function (element) {
      if (!element.isConnected) { elements.delete(element); return; }
      var record = records.get(element);
      record.pending.language = language === "ru" ? "ru" : "en";
      record.pending.requestId += 1;
      send(element, record);
    });
  };
  window.addEventListener("message", function (event) {
    elements.forEach(function (element) {
      if (!element.isConnected) { elements.delete(element); return; }
      if (event.source !== element.contentWindow) { return; }
      var record = records.get(element);
      var message = event.data;
      if (!message || typeof message !== "object") { return; }
      if (message.type === "pg-client-ready") { record.ready = true; send(element, record); }
      if (message.type === "pg-client-state") {
        // Initial and older replies must not replace the user's latest selection.
        if (!record.ready || message.requestId !== record.pending.requestId) { return; }
        if (typeof message.board === "string" && /^[\w-]+\.html$/.test(message.board)) {
          element.dataset.board = message.board; record.pending.board = message.board;
        }
        if (devices.indexOf(message.device) >= 0) { element.dataset.device = message.device; record.pending.device = message.device; }
        if (message.language === "en" || message.language === "ru") {
          element.dataset.language = message.language; record.pending.language = message.language;
        }
        if (typeof message.documentId === "string") { element.dataset.documentId = message.documentId; }
        element.dataset.protection = message.protection || "connected";
        element.dataset.ready = "true";
      }
    });
  });
}());
