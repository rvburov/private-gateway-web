/* One browser document, one native device frame, one delegated source UI.
   All content and data are bundled demonstrations. No network/VPN/account API. */
(function () {
  "use strict";
  var boards = window.PG_CLIENT_BOARDS || {};
  var devices = ["windows", "macos", "linux", "android", "ios"];
  var protections = ["connected", "connecting", "off", "blocked", "strict", "proxy", "paused", "error", "leak", "reconnecting"];
  var references = {
    "08-tray.html": "01-main.html", "09-states.html": "01-main.html",
    "18-dialogs.html": "05-protection.html", "19-notifications.html": "01-main.html",
    "20-platforms.html": "01-main.html", "21-platform-specifics.html": "04-settings.html",
    "22-notify-os.html": "01-main.html", "23-ds-foundations.html": "15-about.html",
    "24-ds-components.html": "04-settings.html", "25-mobile-main.html": "01-main.html",
    "26-mobile-system.html": "01-main.html"
  };
  var state = { board: "01-main.html", device: "windows", language: "en", protection: "connected" };
  var documentId = "client-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  var wrap, slot, frame, app, style, observer;
  var checking = false;
  var timer = null;
  var requestId = 0;
  var sections = [];

  function validBoard(value) {
    return typeof value === "string" && value.indexOf("/") < 0 && Object.prototype.hasOwnProperty.call(boards, value);
  }
  function canonical(value) { return references[value] || value; }
  function getState() {
    return { board: state.board, device: state.device, language: state.language, requestId: requestId,
      protection: state.protection, checking: checking, documentId: documentId };
  }
  function notify() {
    document.documentElement.dataset.demoBoard = state.board;
    document.documentElement.dataset.demoDevice = state.device;
    document.documentElement.dataset.demoLanguage = state.language;
    parent.postMessage(Object.assign({ type: "pg-client-state" }, getState()), "*");
  }
  function translate() {
    if (window.PGClientLanguage) { window.PGClientLanguage.translate(app); }
  }
  function resolveAsset(reference) {
    var resources = window.PG_CLIENT_RESOURCES || {};
    if (Object.prototype.hasOwnProperty.call(resources, reference)) { return resources[reference]; }
    return new URL(reference, new URL("boards/", document.baseURI)).href;
  }
  function allowed(section) {
    if (!section.dataset.os) { return !section.dataset.device || section.dataset.device === state.device; }
    var values = section.dataset.os.split(/\s+/);
    return values.some(function (value) {
      return value === state.device || value === "desktop" && devices.indexOf(state.device) < 3 ||
        value === "phone" && devices.indexOf(state.device) >= 3;
    });
  }
  function parseBoard() {
    var source = document.createElement("template");
    source.innerHTML = boards[state.board].body;
    return Array.from(source.content.querySelectorAll(".pg-screen")).filter(allowed);
  }
  function resultSection() {
    if (["blocked", "strict", "error", "leak"].indexOf(state.protection) >= 0) {
      return sections.find(function (item) { return (item.dataset.caption || "").indexOf("Блокировка:") === 0; }) || sections[0];
    }
    if (["off", "paused"].indexOf(state.protection) >= 0) {
      return sections.find(function (item) { return (item.dataset.caption || "").indexOf("Защита выключена") === 0; }) || sections[0];
    }
    return sections[0];
  }
  function firstSection() {
    if (state.board === "07-diagnostics.html") { return resultSection(); }
    if (state.board === "10-onboarding.html") {
      return sections.find(function (item) { return item.querySelector('[data-page="a-greet"]'); }) || sections[0];
    }
    return sections[0];
  }
  function homeLabels() {
    if (state.board !== "01-main.html") { return; }
    var title = app.querySelector('[data-home-fallback="title"]');
    var detail = app.querySelector('[data-home-fallback="description"]');
    var labels = {
      off: ["IP открыт", "Без шифрования"], blocked: ["Блокировка", "Сервер не отвечает"],
      strict: ["Блокировка", "Строгий режим"], proxy: ["Только прокси", "VPN всей системы выключен"],
      paused: ["Защита на паузе", "Вход в Wi-Fi"], error: ["Ошибка", "Проверьте состояние подключения"],
      leak: ["Утечка IP", "Проверьте защиту"]
    };
    var values = labels[app.dataset.state];
    if (title && detail && values) { title.textContent = values[0]; detail.textContent = values[1]; }
  }
  function remember() {
    if (protections.indexOf(app.dataset.state) >= 0) { state.protection = app.dataset.state; }
    homeLabels();
    translate();
    notify();
  }
  function captureView() {
    var visible = Array.from(app.querySelectorAll("[data-page]")).find(function (item) { return !item.hidden; });
    var tab = app.querySelector(".tab.on[data-panel]");
    return { page: visible && visible.dataset.page, tab: tab && tab.dataset.panel };
  }
  function restoreView(view) {
    if (!view) { return; }
    if (view.page && app.querySelector('[data-page="' + CSS.escape(view.page) + '"]')) {
      app.querySelectorAll("[data-page]").forEach(function (item) { item.hidden = item.dataset.page !== view.page; });
    }
    if (view.tab) {
      var tab = app.querySelector('.tab[data-panel="' + CSS.escape(view.tab) + '"]');
      if (tab) { tab.click(); }
    }
  }

  function renderSection(source, view) {
    observer.disconnect();
    // The app element survives navigation. Its in-memory connection timer must
    // survive as well, so changing sections cannot leave it stuck connecting.
    window.PG.dispose(app, { keepConnection: true });
    var screen = source.cloneNode(true);
    screen.dataset.device = state.device;
    screen.removeAttribute("style");
    screen.querySelectorAll("[src]").forEach(function (node) {
      node.setAttribute("src", resolveAsset(node.getAttribute("src")));
    });
    window.PG.renderIcons(screen);
    var generated = window.PG.frameFor(screen).querySelector(".pg-frame");
    var generatedApp = generated.querySelector(".pg-app");
    // Keep both actual frame and app elements. Only their source content/chrome
    // changes; navigation never replaces the iframe, document or native shell.
    frame.className = generated.className;
    frame.dataset.device = state.device;
    Array.from(frame.children).forEach(function (node) { if (node !== app) { node.remove(); } });
    Array.from(generated.children).forEach(function (node) {
      if (node === generatedApp) { return; }
      if (node.classList.contains("pg-titlebar")) { frame.insertBefore(node, app); }
      else { frame.appendChild(node); }
    });
    app.replaceChildren.apply(app, Array.from(generatedApp.childNodes));
    app.removeAttribute("style");
    app.dataset.stateRoot = "";
    if (state.board === "01-main.html") {
      var title = app.querySelector('.t-status[data-show-state="off"]');
      var detail = app.querySelector('.t-small[data-show-state="off"]');
      if (title && detail) {
        title.dataset.homeFallback = "title"; detail.dataset.homeFallback = "description";
        title.dataset.showState = detail.dataset.showState = "off blocked strict proxy paused error leak";
      }
    }
    window.PG.applyState(app, state.protection);
    app.dataset.demoView = checking ? "checking" : "result";
    homeLabels();
    restoreView(view);
    translate();
    observer.observe(app, { attributes: true, attributeFilter: ["data-state"] });
    fit();
    notify();
  }
  function renderBoard(view) {
    sections = parseBoard();
    if (!sections.length) { state.board = "01-main.html"; sections = parseBoard(); }
    style.textContent = boards[state.board].style;
    renderSection(firstSection(), view);
  }
  function stopCheck() { clearTimeout(timer); checking = false; }
  function navigate(board) {
    if (!validBoard(board)) { return; }
    var next = canonical(board);
    if (next === state.board) { return; }
    stopCheck();
    state.board = next;
    renderBoard();
  }
  function setLanguage(language) {
    state.language = language === "ru" ? "ru" : "en";
    document.documentElement.lang = state.language;
    if (window.PGClientLanguage) { window.PGClientLanguage.setLanguage(state.language); }
    translate();
    notify();
  }
  function setDevice(device) {
    if (devices.indexOf(device) < 0 || device === state.device) { return; }
    var view = captureView();
    stopCheck();
    state.device = device;
    renderBoard(view);
  }
  function command(message) {
    if (!message || message.type !== "pg-client-command") { return; }
    if (!Number.isSafeInteger(message.requestId) || message.requestId < requestId) { return; }
    requestId = message.requestId;
    var nextDevice = devices.indexOf(message.device) >= 0 ? message.device : state.device;
    var nextBoard = validBoard(message.board) ? canonical(message.board) : state.board;
    var rerender = nextDevice !== state.device || nextBoard !== state.board;
    var view = nextBoard === state.board ? captureView() : null;
    if (rerender) { stopCheck(); state.device = nextDevice; state.board = nextBoard; }
    if (message.language === "en" || message.language === "ru") { setLanguage(message.language); }
    if (rerender) {
      renderBoard(view);
    }
  }
  function runCheck() {
    if (checking) { return; }
    var progress = sections.find(function (item) { return item.dataset.caption === "Идет проверка"; });
    if (!progress) { return; }
    checking = true;
    renderSection(progress);
    var button = app.querySelector(".check-actions .btn-primary");
    if (button) { button.setAttribute("aria-busy", "true"); button.setAttribute("aria-disabled", "true"); }
    timer = setTimeout(function () { checking = false; renderSection(resultSection()); }, 1400);
  }
  function fit() {
    if (!wrap) { return; }
    var width = Math.max(1, document.documentElement.clientWidth);
    var height = Math.max(1, innerHeight);
    var reduced = width < 550 || height < 1000;
    var inset = reduced ? 2 : 0;
    document.documentElement.style.setProperty("--pg-embed-viewport-inset", inset + "px");
    wrap.style.zoom = String(Math.min(1, (width - inset * 2) / 550, (height - inset * 2) / 1000));
  }
  function boot() {
    var query = new URLSearchParams(location.search);
    var initial = { device: query.get("device"), board: query.get("board"), language: query.get("language") };
    try {
      if (window.name.indexOf("pg-client-initial:") === 0) {
        initial = JSON.parse(window.name.slice("pg-client-initial:".length));
        window.name = "pg-client-runtime";
      }
    } catch (_) { /* Invalid presentation state falls back to the safe defaults. */ }
    if (devices.indexOf(initial.device) >= 0) { state.device = initial.device; }
    if (validBoard(initial.board)) { state.board = canonical(initial.board); }
    if (initial.language === "ru") { state.language = "ru"; }
    wrap = document.getElementById("client-runtime-wrap");
    slot = document.getElementById("client-device-slot");
    frame = document.createElement("div"); frame.className = "pg-frame";
    app = document.createElement("div"); app.className = "pg-app";
    frame.appendChild(app); slot.appendChild(frame);
    style = document.createElement("style"); style.id = "client-active-board-style"; document.head.appendChild(style);
    observer = new MutationObserver(remember);
    window.PG.resolveAsset = resolveAsset;
    window.PGClientEngine = { navigate: navigate, setDevice: setDevice, setLanguage: setLanguage, getState: getState };
    document.addEventListener("click", function (event) {
      var target = event.target.closest("button, a, [data-nav]");
      if (!target || !app.contains(target) || target.disabled) { return; }
      if (target.hasAttribute("data-nav")) {
        event.preventDefault(); event.stopImmediatePropagation(); navigate(target.dataset.nav);
      } else if (state.board === "07-diagnostics.html" && target.matches(".check-actions .btn-primary")) {
        event.preventDefault(); event.stopImmediatePropagation(); runCheck();
      }
    }, true);
    window.addEventListener("message", function (event) { if (event.source === parent) { command(event.data); } });
    document.addEventListener("pg-client-language-change", function (event) {
      state.language = event.detail === "ru" ? "ru" : "en";
      notify();
    });
    window.addEventListener("resize", fit);
    setLanguage(state.language);
    renderBoard();
    parent.postMessage({ type: "pg-client-ready", documentId: documentId }, "*");
    notify();
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", boot); } else { boot(); }
}());
