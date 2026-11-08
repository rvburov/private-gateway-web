(function () {
  'use strict';

  const PG = window.PG;
  const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  const authIcons = {
    lock: 'M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1zM8 11V7a4 4 0 0 1 8 0v4',
    shield: 'M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6zM9 12l2 2 4-4',
    info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01',
    alert: 'M12 4 2.5 20h19zM12 10v4M12 17h.01',
    bell: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4',
    history: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2',
    chevron: 'M9 5l7 7-7 7',
    down: 'M5 9l7 7 7-7',
  };
  const icon = (name) => authIcons[name] ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="${authIcons[name]}"/></svg>` : PG.icon(name);
  const link = (route, label, extra = '') => `<button type="button" class="auth-link login-link ${extra}" data-auth-route="${escape(route)}">${label}</button>`;
  const field = (id, label, value, options = {}) => `<div class="auth-field field">${options.aside ? `<div class="login-label-row"><label class="field-label" for="${id}">${label}</label>${options.aside}</div>` : `<label class="field-label" for="${id}">${label}</label>`}<div class="auth-input-wrap input-wrap ${options.type === 'password' ? 'login-pw' : ''}"><input class="input" id="${id}" name="${id}" ${id === 'auth-name' ? 'data-i18n-default' : ''} type="${options.type || 'text'}" value="${escape(value)}" autocomplete="off" ${options.placeholder ? `placeholder="${escape(options.placeholder)}"` : ''} ${options.required === false ? '' : 'required'} ${options.readOnly ? 'readonly aria-readonly="true"' : ''} ${options.type === 'email' ? 'inputmode="email" spellcheck="false" autocapitalize="off"' : ''} ${options.type === 'password' && options.minLength !== false ? 'minlength="8"' : ''}>${options.type === 'password' ? `<button type="button" class="auth-eye login-eye" data-auth-eye="${id}" aria-label="Показать пароль">${icon('eye')}</button>` : ''}</div>${options.hint ? `<small class="field-hint">${options.hint}</small>` : ''}</div>`;
  const heading = (eyebrow, title, description) => `<div class="auth-heading login-head"><div class="eyebrow">${eyebrow}</div><h1 class="login-title">${title}</h1><p class="login-sub">${description}</p></div>`;
  const steps = (first, second, active) => `<ol class="auth-steps stepper line" aria-label="Шаги входа"><li class="stepper-item ${active === 0 ? 'current' : 'done'}" ${active === 0 ? 'aria-current="step"' : ''}><span class="stepper-n">${active === 1 ? icon('check') : '1'}</span><span class="stepper-label">${first}</span></li><li class="stepper-item ${active === 1 ? 'current' : ''}" ${active === 1 ? 'aria-current="step"' : ''}><span class="stepper-n">2</span><span class="stepper-label">${second}</span></li></ol>`;
  const error = '<div class="auth-error" role="alert" hidden></div>';
  const submit = (label, name = 'arrow') => `<button class="btn primary lg block auth-submit" type="submit">${label}${icon(name)}</button>`;
  const otp = () => `<div class="auth-field field"><span class="field-label" id="auth-otp-label">Код из приложения</span><div class="auth-otp login-otp" role="group" aria-labelledby="auth-otp-label">${Array.from({ length: 6 }, (_, index) => `${index === 3 ? '<span class="login-otp-sep" aria-hidden="true"></span>' : ''}<input class="login-otp-box" type="text" inputmode="numeric" pattern="[0-9]" maxlength="1" aria-label="Цифра ${index + 1} из 6" ${index === 0 ? 'autocomplete="one-time-code"' : 'autocomplete="off"'} data-auth-digit="${index}">`).join('')}</div><small class="field-hint">В макете используйте <b class="auth-mono">123456</b>. ${link('2fa', 'Подставить код', 'auth-fill-code')}</small></div>`;

  function login() {
    return `<form class="auth-form" data-auth-form="login">
        ${steps('Пароль', 'Код 2FA', 0)}
        ${heading('Личный кабинет', 'Вход в Private Gateway', 'Email и пароль, затем 6-значный код из приложения-аутентификатора.')}
        ${error}
        ${field('auth-email', 'Email', '', { type: 'email' })}
        ${field('auth-password', 'Пароль', '', { type: 'password', minLength: false, aside: link('reset', 'Забыли пароль?') })}
        <label class="auth-check check login-check"><input type="checkbox" id="auth-remember"><span class="check-text"><span>Запомнить это устройство на 30 дней</span><small class="field-hint">Код 2FA здесь не спросим 30 дней. Не отмечайте на чужом компьютере.</small></span></label>
        ${submit('Войти')}
        <div class="login-alt"><span class="muted">Нет аккаунта?</span>${link('invite', `Регистрация только по приглашению${icon('chevron')}`)}</div>
      </form>`;
  }

  function invitationFor(code) {
    const normalized = String(code).trim().toUpperCase();
    if (normalized === 'PG-DEMO') return { id: null, code: 'PG-DEMO', email: 'new.member@example.test', role: 'member', status: 'active' };
    return (PG.state.demoInvites || []).find((item) => String(item.code).trim().toUpperCase() === normalized) || null;
  }

  function invite() {
    const initialCode = PG.state.invitation?.code || 'PG-DEMO';
    const invitation = invitationFor(initialCode);
    return `${steps('Аккаунт', 'Приложение 2FA', 0)}${heading('По приглашению', 'Добро пожаловать', 'Создайте демонстрационный аккаунт по приглашению.')}
      <form class="auth-form" data-auth-form="invite">${error}
        ${field('auth-invite', 'Код приглашения', initialCode, { hint: 'Используйте созданное приглашение или демонстрационный код PG-DEMO.' })}
        ${field('auth-name', 'Ваше имя', 'Новый участник')}
        ${field('auth-email', 'Email из приглашения', invitation?.email || '', { type: 'email', readOnly: true, required: false, hint: 'Email и роль заданы администратором в приглашении.' })}
        <p class="auth-mini-label" data-auth-invite-role>Роль: ${invitation?.role === 'admin' ? 'администратор' : 'участник'}</p>
        ${field('auth-password', 'Пароль', 'demo-password', { type: 'password', hint: 'Это макет. Используйте только вымышленные данные.' })}
        ${submit('Создать аккаунт')}
      </form><p class="auth-alt">Уже есть аккаунт? ${link('login', 'Войти')}</p>`;
  }

  function twoFactor() {
    return `${steps('Пароль', 'Код 2FA', 1)}${heading('Второй шаг', 'Подтвердите вход', 'Введите шесть цифр из приложения-аутентификатора.')}
      <div class="auth-account login-acct">${icon('user')}<div><strong>Подтверждение входа</strong><span>${escape(PG.state.loginEmail || 'demo@example.test')}</span></div>${link('login', 'Не вы?')}</div>
      <form class="auth-form" data-auth-form="2fa">${error}${otp()}${submit('Войти в кабинет', 'shield')}</form>
      <div class="auth-bottom-links">${link('login', `${icon('arrow')}Назад`, 'auth-back')}${link('reset', 'Не получается войти?')}</div>`;
  }

  function setup() {
    return `${steps('Аккаунт', 'Приложение 2FA', 1)}${heading('Настройка входа', 'Добавьте второй шаг', 'Так будет выглядеть подключение приложения-аутентификатора.')}
      <div class="auth-setup"><div class="auth-qr" aria-label="Заглушка QR-кода, не для сканирования">${icon('monitor')}<strong>QR · макет</strong><span>Не сканировать</span></div><div class="auth-setup-text"><strong>1. Добавьте аккаунт</strong><p>В рабочей версии здесь появится QR-код для приложения.</p><span class="auth-mini-label">Вымышленный ключ</span><code>PG-DEMO-NO-SECRET</code><button class="auth-link" type="button" data-auth-copy="key">${icon('copy')}Скопировать</button></div></div>
      <form class="auth-form" data-auth-form="setup">${error}<strong class="auth-section-title">2. Введите проверочный код</strong>${otp()}${submit('Продолжить', 'shield')}</form>
      <p class="auth-footnote">${icon('eye')}В этом макете двухфакторная защита не включается.</p>`;
  }

  const backupCodes = Array.from({ length: 8 }, (_, index) => `DEMO-${String(index + 1).padStart(4, '0')}`);
  function backup() {
    return `${heading('Последний шаг', 'Резервные коды', 'Так будет выглядеть сохранение кодов на случай потери телефона.')}
      <div class="auth-backup-note">${icon('key')}Все коды ниже вымышлены и не дают доступа к аккаунту.</div>
      <ol class="auth-backup-codes">${backupCodes.map((code) => `<li>${code}</li>`).join('')}</ol>
      <div class="auth-code-actions"><button class="btn" type="button" data-auth-copy="codes">${icon('copy')}Скопировать</button><button class="btn" type="button" data-auth-download>${icon('download')}Скачать .txt</button></div>
      <form class="auth-form" data-auth-form="backup">${error}<label class="auth-check"><input type="checkbox" id="auth-saved"><span>Я посмотрел, как сохраняются резервные коды</span></label>${submit('Перейти в кабинет', 'check')}</form>
      <p class="auth-footnote">В рабочем сервисе настоящие коды нужно хранить отдельно от пароля.</p>`;
  }

  function reset() {
    return `${heading('Восстановление', 'Верните доступ', 'Введите код, который в рабочем сервисе выдаст администратор.')}
      <form class="auth-form" data-auth-form="reset">${error}
        ${field('auth-email', 'Email', 'member@example.test', { type: 'email' })}
        ${field('auth-reset', 'Код администратора', 'RESET-DEMO', { hint: 'Код для просмотра макета: RESET-DEMO' })}
        ${field('auth-password', 'Новый пароль', 'demo-password', { type: 'password', hint: 'Введите вымышленный пароль — не менее 8 символов.' })}
        ${submit('Обновить демо-пароль', 'key')}
      </form><p class="auth-alt">${link('login', 'Вернуться ко входу')}</p><p class="auth-footnote">Данные аккаунтов в макете не изменяются.</p>`;
  }

  // Декоративные линии компьютерной сети: без подписей и состояния подключения.
  function networkBackground() {
    return `<svg class="auth-network-background" viewBox="0 0 700 800" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false"><g class="auth-network-lines"><path d="M430 80h98q20 0 20 20v66q0 20 20 20h132M610 0v86q0 20-20 20H430q-20 0-20 20v106q0 20-20 20h-94M700 336H582q-20 0-20-20v-44q0-20-20-20H410M700 508h-78q-20 0-20-20v-56q0-20-20-20H470q-20 0-20 20v76q0 20-20 20H302M700 668H520q-20 0-20-20v-60q0-20-20-20h-78M264 800v-86q0-20 20-20h146q20 0 20-20V528"/></g><g class="auth-network-junctions"><circle cx="430" cy="80" r="5"/><circle cx="548" cy="166" r="4"/><circle cx="410" cy="232" r="4"/><circle cx="296" cy="252" r="5"/><circle cx="562" cy="292" r="4"/><circle cx="582" cy="412" r="4"/><circle cx="470" cy="412" r="4"/><circle cx="302" cy="528" r="5"/><circle cx="450" cy="612" r="4"/><circle cx="520" cy="668" r="4"/><circle cx="284" cy="694" r="5"/></g></svg>`;
  }
  const authBrand = () => `<a class="login-brandrow" href="#home" aria-label="Private Gateway — главная"><svg class="brand-mark" viewBox="0 0 512 512" aria-hidden="true"><rect width="512" height="512" rx="112" fill="var(--accent)"/><path d="M256 96 374 144v101c0 81-49 132-118 171-69-39-118-90-118-171V144Z" fill="none" stroke="var(--accent-fg)" stroke-width="25" stroke-linejoin="round"/><path d="m202 253 36 36 75-82" fill="none" stroke="var(--accent-fg)" stroke-width="27" stroke-linecap="round" stroke-linejoin="round"/></svg><div class="login-brandrow-text"><div class="brand-name">Private Gateway</div><div class="brand-sub">приватный доступ к приложению</div></div></a>`;
  const themeButton = () => `<button type="button" class="btn ghost sm icon-only auth-theme" aria-label="${document.documentElement.dataset.theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}">${icon('appearance')}</button>`;
  PG.auth = function (route) {
    const render = { login, invite, '2fa': twoFactor, setup, backup, reset }[route] || login;
    return `<div class="auth-shell login-page"><aside class="login-brand" aria-label="Личный кабинет Private Gateway">${networkBackground()}${authBrand()}<div class="login-hero"><div class="eyebrow">Личный кабинет</div><p class="login-hero-h">Приватная работа в сети с контролем трафика</p><p class="login-hero-p">Войдите по email и паролю, затем введите код из приложения-аутентификатора.</p><p class="login-hero-note">Регистрация — только по приглашению.</p></div><div class="login-brandfoot"><span>© 2026 Private Gateway</span><span>Приложение для компьютера и телефона</span></div></aside><div class="login-m-hero">${networkBackground()}<div class="login-m-top">${authBrand()}${themeButton()}</div><p class="login-m-lead">Вход по email и паролю, затем код из аутентификатора.</p><p class="login-m-invite">Регистрация — по приглашению.</p></div><section class="auth-content login-main"><div class="login-topline">${themeButton()}</div><div class="login-center"><div class="auth-panel login-form ${route === 'setup' ? 'wide' : ''}">${render()}</div></div></section><footer class="login-m-foot"><span>© 2026 Private Gateway</span></footer></div>`;
  };

  PG.bindAuth = function () {
    const container = document.querySelector('.auth-shell');
    if (!container) return;
    const showError = (text) => {
      const element = container.querySelector('.auth-error');
      element.textContent = text;
      element.hidden = false;
    };
    const clearPassword = () => container.querySelectorAll('input[type="password"], #auth-password').forEach((input) => { input.value = ''; });
    const navigate = (route) => { clearPassword(); PG.navigate(route); };
    container.querySelectorAll('[data-auth-route]').forEach((button) => button.addEventListener('click', () => {
      if (button.classList.contains('auth-fill-code')) {
        container.querySelectorAll('[data-auth-digit]').forEach((input, index) => { input.value = String(index + 1); });
        container.querySelector('.auth-submit')?.focus();
        return;
      }
      navigate(button.dataset.authRoute);
    }));
    container.querySelectorAll('[data-auth-eye]').forEach((button) => button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.authEye);
      input.type = input.type === 'password' ? 'text' : 'password';
      button.setAttribute('aria-label', input.type === 'password' ? 'Показать демо-пароль' : 'Скрыть демо-пароль');
    }));
    container.querySelectorAll('.auth-theme').forEach((button) => button.addEventListener('click', () => {
      document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      container.querySelectorAll('.auth-theme').forEach((item) => {
        item.innerHTML = icon('appearance');
        item.setAttribute('aria-label', document.documentElement.dataset.theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему');
      });
    }));
    container.querySelector('#auth-invite')?.addEventListener('input', (event) => {
      const invitation = invitationFor(event.currentTarget.value);
      document.getElementById('auth-email').value = invitation?.email || '';
      container.querySelector('[data-auth-invite-role]').textContent = invitation ? `Роль: ${invitation.role === 'admin' ? 'администратор' : 'участник'}` : 'Введите действующий демонстрационный код приглашения.';
      const errorElement = container.querySelector('.auth-error');
      errorElement.hidden = true;
    });
    const digits = [...container.querySelectorAll('[data-auth-digit]')];
    digits.forEach((input, index) => {
      input.addEventListener('input', () => {
        input.value = input.value.replace(/\D/g, '').slice(-1);
        input.removeAttribute('aria-invalid');
        if (input.value) digits[index + 1]?.focus();
      });
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Backspace' && !input.value) digits[index - 1]?.focus();
        if (event.key === 'ArrowLeft') digits[index - 1]?.focus();
        if (event.key === 'ArrowRight') digits[index + 1]?.focus();
      });
      input.addEventListener('paste', (event) => {
        event.preventDefault();
        const value = event.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
        [...value].forEach((character, position) => { if (digits[index + position]) digits[index + position].value = character; });
        digits[Math.min(index + value.length, 5)]?.focus();
      });
    });
    container.querySelectorAll('[data-auth-copy]').forEach((button) => button.addEventListener('click', async () => {
      const value = button.dataset.authCopy === 'key' ? 'PG-DEMO-NO-SECRET' : backupCodes.join('\n');
      try {
        await navigator.clipboard.writeText(value);
        PG.toast('Демонстрационные данные скопированы');
      } catch {
        PG.toast(button.dataset.authCopy === 'key' ? 'Демо-ключ: PG-DEMO-NO-SECRET' : 'Копирование недоступно. Используйте «Скачать .txt».');
      }
    }));
    container.querySelector('[data-auth-download]')?.addEventListener('click', () => {
      const url = URL.createObjectURL(new Blob([PG.t('Private Gateway · макет') + '\n' + PG.t('Это вымышленные коды. Они не дают доступа к аккаунту.') + '\n\n', backupCodes.join('\n')], { type: 'text/plain;charset=utf-8' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'private-gateway-demo-codes.txt';
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      PG.toast('Демо-коды скачаны');
    });
    container.querySelector('form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      const route = event.currentTarget.dataset.authForm;
      if (route === 'login') {
        PG.state.role = 'member';
        PG.state.loginEmail = document.getElementById('auth-email').value.trim();
        navigate('2fa');
        return;
      }
      if (route === 'invite') {
        const invitation = invitationFor(document.getElementById('auth-invite').value);
        if (!invitation) { showError('Приглашение не найдено. Используйте созданный демо-код или PG-DEMO.'); return; }
        if (invitation.status === 'used') { showError('Это приглашение уже использовано в макете. Создайте новое или используйте PG-DEMO.'); return; }
        if (invitation.status !== 'active') { showError('Это приглашение отозвано или больше не действует в макете.'); return; }
        PG.state.pendingRole = invitation.role === 'admin' ? 'admin' : 'member';
        PG.state.pendingInviteId = invitation.id;
        navigate('setup');
        return;
      }
      if (route === '2fa' || route === 'setup') {
        if (digits.map((input) => input.value).join('') !== '123456') {
          showError('В макете подходит только демонстрационный код 123456.');
          digits.forEach((input) => input.setAttribute('aria-invalid', 'true'));
          digits[0]?.focus();
          return;
        }
        if (route === 'setup') { navigate('backup'); }
        else { PG.toast('Демонстрационный вход выполнен'); navigate(PG.state.role === 'admin' ? 'admin-members' : 'downloads'); }
        return;
      }
      if (route === 'backup') {
        if (!document.getElementById('auth-saved').checked) { showError('Отметьте, что вы посмотрели резервные коды.'); document.getElementById('auth-saved').focus(); return; }
        PG.state.role = PG.state.pendingRole === 'admin' ? 'admin' : 'member';
        if (PG.state.pendingInviteId != null) {
          const invitation = (PG.state.demoInvites || []).find((item) => String(item.id) === String(PG.state.pendingInviteId));
          if (invitation) invitation.status = 'used';
        }
        delete PG.state.invitation;
        delete PG.state.pendingRole;
        delete PG.state.pendingInviteId;
        PG.toast('Демонстрационный аккаунт создан');
        navigate(PG.state.role === 'admin' ? 'admin-members' : 'downloads');
        return;
      }
      if (route === 'reset') {
        if (document.getElementById('auth-reset').value.trim().toUpperCase() !== 'RESET-DEMO') { showError('Используйте демонстрационный код RESET-DEMO.'); return; }
        PG.toast('Демо-пароль обновлён. Можно посмотреть вход.');
        navigate('login');
      }
    });
  };
}());
