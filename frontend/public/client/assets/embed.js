/* Presentation-only adapter. No authentication, persistent storage or VPN actions.
   Source boards are design sheets with several snapshots. This adapter mounts
   one native device and turns the diagnostic snapshots into an in-app flow. */
(function () {
  "use strict";
  var params = new URLSearchParams(location.search);
  if (params.get("embed") !== "1") { return; }
  document.documentElement.classList.add("pg-embed");
  document.title += " — демонстрация";
  var device = params.get("device") || "windows";
  var path = window.PG_DEMO_PATH || location.pathname;
  var board = path.split("/").pop();
  // Platform comparisons, design tokens and notification sheets are references,
  // not app routes. Reuse their real app destinations in embedded presentations.
  var referenceRoutes = {
    "08-tray.html": "01-main.html", "09-states.html": "01-main.html",
    "18-dialogs.html": "05-protection.html", "19-notifications.html": "01-main.html",
    "20-platforms.html": "01-main.html", "21-platform-specifics.html": "04-settings.html",
    "22-notify-os.html": "01-main.html", "23-ds-foundations.html": "15-about.html",
    "24-ds-components.html": "04-settings.html", "25-mobile-main.html": "01-main.html",
    "26-mobile-system.html": "01-main.html"
  };
  var memoryPrefix = "pg-client-demo:";
  var states = ["connected", "connecting", "off", "blocked", "strict", "proxy", "paused", "error", "leak", "reconnecting"];
  var memory = { protection: "connected" };
  try {
    if (window.name.indexOf(memoryPrefix) === 0) {
      var saved = JSON.parse(window.name.slice(memoryPrefix.length));
      if (states.indexOf(saved.protection) >= 0) { memory.protection = saved.protection; }
    }
  } catch (_) { /* The iframe name is transient presentation state only. */ }
  // A document navigation ends the old connection animation, not its success.
  if (memory.protection === "connecting" || memory.protection === "reconnecting") { memory.protection = "connected"; }
  var templates = [];
  var holder = null;
  var active = null;
  var observer = null;
  var checking = false;
  var checkTimer = null;

  function remember() {
    if (!active || checking) { return; }
    var app = active.querySelector(".pg-app");
    if (app && states.indexOf(app.dataset.state) >= 0) { memory.protection = app.dataset.state; }
    window.name = memoryPrefix + JSON.stringify(memory);
    updateHomeLabels();
  }

  function navigate(file) {
    if (window.PG_DEMO_PATH) {
      parent.postMessage({ type: "pg-demo-nav", board: file, device: device }, "*");
    } else {
      location.replace(file + "?device=" + device + "&thumb=1&embed=1");
    }
  }

  function updateHomeLabels() {
    if (board !== "01-main.html" || !active) { return; }
    var app = active.querySelector(".pg-app");
    var state = app.dataset.state;
    var title = app.querySelector('[data-home-fallback="title"]');
    var description = app.querySelector('[data-home-fallback="description"]');
    var labels = {
      off: ["IP открыт", "Без шифрования"],
      blocked: ["Блокировка", "Сервер не отвечает"],
      strict: ["Блокировка", "Строгий режим"],
      proxy: ["Только прокси", "VPN всей системы выключен"],
      paused: ["Защита на паузе", "Вход в Wi-Fi"],
      error: ["Ошибка", "Проверьте состояние подключения"],
      leak: ["Утечка IP", "Проверьте защиту"]
    };
    if (title && description && labels[state]) {
      title.textContent = labels[state][0]; description.textContent = labels[state][1];
    }
  }

  function mount(wrap, protection) {
    if (observer) { observer.disconnect(); }
    if (active) { active.remove(); }
    active = wrap;
    holder.appendChild(active);
    var app = active.querySelector(".pg-app");
    if (protection && app) { window.PG.applyState(app, protection); }
    if (board === "01-main.html") {
      var title = app.querySelector('.t-status[data-show-state="off"]');
      var description = app.querySelector('.t-small[data-show-state="off"]');
      if (title && description) {
        title.dataset.homeFallback = "title"; description.dataset.homeFallback = "description";
        title.dataset.showState = description.dataset.showState = "off blocked strict proxy paused error leak";
        window.PG.applyState(app, app.dataset.state);
      }
    }
    updateHomeLabels();
    fitFrames();
    observer = new MutationObserver(remember);
    if (app) { observer.observe(app, { attributes: true, attributeFilter: ["data-state"] }); }
  }

  function caption(wrap) {
    var label = wrap.querySelector(".pg-frame-caption");
    return label ? label.textContent : "";
  }

  function diagnosticResult() {
    if (["blocked", "strict", "error", "leak"].indexOf(memory.protection) >= 0) {
      return templates.find(function (wrap) { return caption(wrap).indexOf("Блокировка:") === 0; }) || templates[0];
    }
    if (["off", "paused"].indexOf(memory.protection) >= 0) {
      return templates.find(function (wrap) { return caption(wrap).indexOf("Защита выключена") === 0; }) || templates[0];
    }
    return templates[0];
  }

  function runDiagnostics() {
    if (checking) { return; }
    var progress = templates.find(function (wrap) { return caption(wrap) === "Идет проверка"; });
    if (!progress) { return; }
    remember();
    checking = true;
    progress.dataset.demoView = "checking";
    mount(progress, memory.protection);
    var button = active.querySelector('.check-actions .btn-primary');
    if (button) { button.setAttribute("aria-busy", "true"); button.setAttribute("aria-disabled", "true"); }
    clearTimeout(checkTimer);
    checkTimer = setTimeout(function () {
      var result = diagnosticResult();
      result.dataset.demoView = "result";
      mount(result, memory.protection);
      checking = false;
      remember();
    }, 1400);
  }

  function init() {
    if (referenceRoutes[board]) {
      document.querySelectorAll(".pg-frame-wrap").forEach(function (wrap) { wrap.remove(); });
      navigate(referenceRoutes[board]); return;
    }
    templates = Array.from(document.querySelectorAll(".pg-frame-wrap")).filter(function (wrap) {
      var frame = wrap.querySelector(".pg-frame");
      return frame && frame.dataset.device === device;
    });
    var first = board === "10-onboarding.html"
      ? templates.find(function (wrap) { return wrap.querySelector('[data-page="a-greet"]'); })
      : templates[0];
    if (!first) { navigate("01-main.html"); return; }
    holder = first.parentElement;
    // Detach snapshot alternatives instead of laying them out below the device.
    // Their existing DOM, source controls, dialogs and per-board CSS are retained.
    document.querySelectorAll(".pg-frame-wrap").forEach(function (wrap) { wrap.remove(); });
    if (board === "07-diagnostics.html") { first = diagnosticResult(); first.dataset.demoView = "result"; }
    mount(first, memory.protection);
    remember();
    document.addEventListener("click", function (event) {
      var target = event.target.closest("button, a, [data-nav]");
      if (!target || !active.contains(target)) { return; }
      if (target.hasAttribute("data-nav")) { remember(); }
      if (board === "07-diagnostics.html" && target.matches('.check-actions .btn-primary')) {
        event.preventDefault(); event.stopImmediatePropagation(); runDiagnostics();
      }
    }, true);
    document.documentElement.dataset.demoBoard = board;
  }

  function fitFrames() {
    var width = Math.max(1, document.documentElement.clientWidth);
    var height = Math.max(1, window.innerHeight);
    var wraps = Array.from(document.querySelectorAll(".pg-frame-wrap"));
    // Fractional CSS zoom may rasterize the faint shadow one pixel farther
    // than the unscaled artwork. Keep 2 physical CSS pixels around a reduced
    // presentation; native-size presentations retain their exact dimensions.
    var inset = wraps.some(function (wrap) { return width < wrap.offsetWidth || height < wrap.offsetHeight; }) ? 2 : 0;
    document.documentElement.style.setProperty("--pg-embed-viewport-inset", inset + "px");
    wraps.forEach(function (wrap) {
      var frame = wrap.querySelector(".pg-frame");
      if (!frame) { return; }
      // Fit the native frame AND transparent shadow gutters as one unit.
      // offsetWidth/Height retain unscaled CSS dimensions under CSS zoom.
      // No second parent scale or substitute window/phone frame is required.
      var scale = Math.min(1, (width - inset * 2) / wrap.offsetWidth, (height - inset * 2) / wrap.offsetHeight);
      wrap.style.zoom = String(scale);
    });
  }

  // app.js registers its DOMContentLoaded handler before this deferred adapter.
  // Run afterward, once it has replaced source sections with platform frames.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  window.addEventListener("resize", fitFrames);
}());
