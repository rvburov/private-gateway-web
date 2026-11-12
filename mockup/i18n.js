/* Language changes update the existing DOM. Inputs, dialogs and the client iframe
   keep their identity and state; no page or component is remounted. */
(function () {
  'use strict';
  const PG = window.PG;
  const dictionary = window.PG_TRANSLATIONS || {};
  const originalText = new WeakMap();
  const originalAttributes = new WeakMap();
  const inputDefaults = new WeakMap();
  const attributes = ['aria-label', 'title', 'placeholder', 'alt', 'data-label'];
  const ignored = 'script,style,noscript,code,textarea,[data-no-translate]';
  let translating = false;
  let observer;
  PG.lang = 'en';

  function english(core) {
    if (Object.prototype.hasOwnProperty.call(dictionary, core)) return dictionary[core];
    let match;
    if ((match = core.match(/^Цифра (\d+) из 6$/))) return `Digit ${match[1]} of 6`;
    if ((match = core.match(/^Скачать для (.+)$/))) return `Download for ${match[1]}`;
    if ((match = core.match(/^Private Gateway для (.+)$/))) return `Private Gateway for ${match[1]}`;
    if ((match = core.match(/^Карточка участника (.+)$/))) return `Member details: ${english(match[1])}`;
    if ((match = core.match(/^Скопировать демо-код для (.+)$/))) return `Copy demo code for ${match[1]}`;
    if ((match = core.match(/^Срок действия: (.+)$/))) return `Expires after: ${english(match[1])}`;
    if ((match = core.match(/^Private Gateway Web · (.+)$/))) return `Private Gateway Web · ${english(match[1])}`;
    if ((match = core.match(/^(\d+) из (\d+) занято$/))) return `${match[1]} of ${match[2]} in use`;
    if ((match = core.match(/^(\d+) из (\d+) · лимит по умолчанию$/))) return `${match[1]} of ${match[2]} · default limit`;
    if ((match = core.match(/^Последняя активность: (.+?) · Сеть (.+)$/))) return `Last active: ${english(match[1])} · Network ${match[2]}`;
    if ((match = core.match(/^(.+) · Приложение (.+) · Последняя активность: (.+?) · Сеть (.+)$/))) return `${match[1]} · App ${match[2]} · Last active: ${english(match[3])} · Network ${match[4]}`;
    return core;
  }

  function translateValue(source, language = PG.lang) {
    if (language === 'ru') return source;
    const match = String(source).match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!match) return source;
    return match[1] + english(match[2].replace(/\s+/g, ' ')) + match[3];
  }

  PG.t = (text) => translateValue(String(text));

  function translateText(node) {
    if (!node.parentElement || node.parentElement.closest(ignored)) return;
    const current = node.nodeValue;
    const record = originalText.get(node);
    const source = record && current === record.output ? record.source : current;
    const output = translateValue(source);
    originalText.set(node, { source, output });
    if (current !== output) node.nodeValue = output;
  }

  function translateElement(element) {
    if (element.matches(ignored) || element.closest('[data-no-translate]')) return;
    // Native option values must remain stable when the displayed label changes.
    if (element.tagName === 'OPTION' && !element.hasAttribute('value')) element.setAttribute('value', element.textContent);
    let records = originalAttributes.get(element);
    if (!records) { records = {}; originalAttributes.set(element, records); }
    attributes.forEach(name => {
      if (!element.hasAttribute(name)) return;
      const current = element.getAttribute(name);
      const record = records[name];
      const source = record && current === record.output ? record.source : current;
      const output = translateValue(source);
      records[name] = { source, output };
      if (current !== output) element.setAttribute(name, output);
    });
    if (element.matches('input[data-i18n-default]')) {
      const previous = inputDefaults.get(element);
      if (!previous || (!previous.dirty && element.value === previous.output)) {
        const source = previous ? previous.source : element.value;
        const output = translateValue(source);
        element.value = output;
        inputDefaults.set(element, {source, output, dirty:false});
      }
    }
  }

  function process(root) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) { translateText(root); return; }
    if (root.nodeType === Node.ELEMENT_NODE) translateElement(root);
    if (root.querySelectorAll) root.querySelectorAll('*').forEach(translateElement);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) translateText(node);
  }

  function observe() {
    observer.observe(document.documentElement, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:attributes});
  }

  PG.translate = function (root = document.documentElement) {
    if (translating) return;
    translating = true;
    observer?.disconnect();
    try {
      process(root);
      document.documentElement.lang = PG.lang;
      document.querySelectorAll('button[data-language]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.language === PG.lang)));
    } finally {
      translating = false;
      if (observer) observe();
    }
  };

  PG.setLanguage = function (language) {
    if (!['en', 'ru'].includes(language)) return;
    PG.lang = language;
    PG.translate();
    PG.setClientLanguage?.(language);
    window.dispatchEvent(new CustomEvent('pg:languagechange', {detail:{language}}));
  };

  observer = new MutationObserver(() => PG.translate());
  document.addEventListener('input', event => {
    const record = inputDefaults.get(event.target);
    if (record) record.dirty = true;
  });
  PG.translate();
}());
