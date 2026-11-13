/* Визуальный макет: участники и приглашения существуют только в памяти вкладки. */
(() => {
  const PG = window.PG;
  const esc = (value) => PG.escape(String(value));
  const icon = (name) => PG.icon(name);
  let architecture = 'Apple Silicon';
  let search = '';
  let filter = 'all';
  let inviteFilter = 'all';
  let sequence = 3;
  // Система посетителя для страницы скачивания: auto — по User-Agent, как в рабочем сайте
  let previewSystem = 'auto';
  const members = [
    { id: 'm1', name: 'Александр Соколов', email: 'alex@example.test', role: 'admin', active: true, twoFactor: true, joined: 'Демонстрационный участник' },
    { id: 'm2', name: 'Мария Орлова', email: 'maria@example.test', role: 'member', active: true, twoFactor: false, joined: 'Демонстрационный участник' },
    { id: 'm3', name: 'Дмитрий Волков', email: 'dmitry@example.test', role: 'admin', active: true, twoFactor: false, joined: 'Демонстрационный участник' },
    { id: 'm4', name: 'Анна Лебедева', email: 'anna@example.test', role: 'member', active: false, twoFactor: false, joined: 'Демонстрационный участник' },
  ];
  const invites = [
    { id: 'i1', email: 'elena@example.test', role: 'member', validity: '7 дней', status: 'active', code: 'PG-DEMO-MEMBER' },
    { id: 'i2', email: 'nikita@example.test', role: 'member', validity: '24 часа', status: 'used', code: 'PG-DEMO-USED' },
    { id: 'i3', email: 'olga@example.test', role: 'admin', validity: '3 дня', status: 'revoked', code: 'PG-DEMO-REVOKED' },
  ];
  PG.state.demoInvites = invites;
  const roleName = (role) => role === 'admin' ? 'Администратор' : 'Участник';
  const navButton = (route, current, name, label) => `<button class="ac-nav-link ${route === current ? 'is-active' : ''}" data-account-route="${route}" ${route === current ? 'aria-current="page"' : ''}>${icon(name)}<span>${label}</span>${route === 'admin-members' ? `<span class="ac-nav-count">${members.length}</span>` : ''}</button>`;
  const initials = (name) => esc(name.split(' ').map(part => part[0]).slice(0, 2).join(''));
  const memberBadge = (member) => `<span class="ac-status ${member.active ? 'is-good' : 'is-muted'}"><i></i>${member.active ? 'Доступ открыт' : 'Доступ отозван'}</span>`;
  const inviteBadge = (status) => `<span class="ac-status ${status === 'active' ? 'is-good' : 'is-muted'}"><i></i>${({ active: 'Активно', used: 'Использовано', revoked: 'Отозвано' })[status]}</span>`;
  const demoNotice = `<div class="ac-demo-note">${icon('eye')}<span>Демонстрационные данные. Все изменения действуют до обновления страницы.</span></div>`;
  // 2FA только у администратора (2026-11-13): участник входит по паролю
  const protection = (member) => member.role !== 'admin' ? `<span class="ac-2fa is-password">${icon('lock')}Вход по паролю</span>` : `<span class="ac-2fa ${member.twoFactor ? '' : 'is-off'}">${icon(member.twoFactor ? 'shield' : 'key')}${member.twoFactor ? '2FA включена' : '2FA не настроена'}</span>`;
  // Та же проверка, что frontend/src/account/platform.ts: Android раньше Linux, Mac с касаниями — iPad
  function detectSystem() {
    const agent = navigator.userAgent || '';
    if (/Android/i.test(agent)) return 'android';
    if (/iPhone|iPad|iPod/i.test(agent)) return 'ios';
    if (/Macintosh|Mac OS X/i.test(agent)) return (navigator.maxTouchPoints || 0) > 1 ? 'ios' : 'macos';
    if (/Windows/i.test(agent)) return 'windows';
    if (/CrOS/i.test(agent)) return null;
    if (/Linux|X11/i.test(agent)) return 'linux';
    return null;
  }
  const systemNames = { windows: 'Windows', macos: 'macOS', linux: 'Linux', android: 'Android', ios: 'iOS' };

  function shell(route, content) {
    return `<section class="ac-shell" id="pg-account"><aside class="ac-sidebar"><div class="ac-sidebar-head"><span class="eyebrow">PRIVATE GATEWAY WEB</span><h2>Личный кабинет</h2></div><nav aria-label="Меню личного кабинета">${navButton('downloads', route, 'download', 'Скачать клиент')}${navButton('devices', route, 'monitor', 'Устройства')}${PG.state.role === 'admin' ? `<div class="ac-nav-caption">Администрирование</div>${navButton('admin-members', route, 'users', 'Участники')}${navButton('admin-invites', route, 'mail', 'Приглашения')}${navButton('admin-downloads', route, 'history', 'Журнал скачиваний')}` : ''}</nav><div class="ac-sidebar-bottom"><div class="ac-session"><span class="ac-avatar small">${icon('user')}</span><div><strong>Демо-профиль</strong><span>${roleName(PG.state.role)}</span></div></div><button class="ac-nav-link ac-logout" data-account-route="login">${icon('logout')}<span>Выйти из кабинета</span></button></div></aside><div class="ac-main">${content}</div></section>`;
  }
  function heading(kicker, title, description, action = '') {
    return `<div class="ac-heading"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p>${description}</p></div>${action}</div>`;
  }
  function osIcon(platform) {
    return icon(({ Windows: 'windows', macOS: 'apple', iOS: 'apple', Linux: 'linux', Android: 'android' })[platform]);
  }
  function downloadCard(platform, subtitle, isFeatured, tag) {
    return `<article class="ac-download-card ${isFeatured ? 'is-featured' : ''}" data-platform="${platform.toLowerCase()}"><div class="ac-os-icon">${osIcon(platform)}</div><div class="ac-download-title"><h2>${platform}</h2>${isFeatured ? `<span class="ac-tag">${tag}</span>` : ''}</div><p>${subtitle}</p>${platform === 'macOS' ? `<div class="ac-architecture" role="group" aria-label="Архитектура macOS"><button data-ac-arch="Apple Silicon" aria-pressed="${architecture === 'Apple Silicon'}" class="${architecture === 'Apple Silicon' ? 'selected' : ''}">Apple Silicon</button><button data-ac-arch="Intel" aria-pressed="${architecture === 'Intel'}" class="${architecture === 'Intel' ? 'selected' : ''}">Intel</button></div>` : '<div class="ac-platform-space"></div>'}<button class="btn ${isFeatured ? 'primary' : ''} ac-download-btn" data-ac-download="${platform}">${icon('download')} Скачать для ${platform}</button><div class="ac-file-label">Макет · файл не подключен</div>${platform === 'Android' ? `<p class="ac-install-hint">${icon('info')}<span>После скачивания откройте файл и разрешите установку из этого источника.</span></p>` : ''}</article>`;
  }
  function downloads() {
    // 2026-11-13: карточка системы посетителя первая и с основной кнопкой; неизвестная — Windows
    const detected = previewSystem === 'auto' ? detectSystem() : previewSystem;
    const featured = detected || 'windows';
    const tag = detected ? 'Ваша система' : 'Десктоп';
    const leads = { windows: 'Клиент для вашего компьютера', macos: 'Для Mac с Apple Silicon и Intel', linux: 'Для вашей рабочей среды', android: 'Приватный маршрут всегда с собой' };
    const order = ['windows', 'macos', 'linux', 'android'];
    if (detected && detected !== 'ios') order.unshift(...order.splice(order.indexOf(detected), 1));
    const iosFirst = featured === 'ios';
    const ios = `<div class="ac-ios card ${iosFirst ? 'is-featured is-first' : ''}" data-platform="ios"><div class="ac-os-icon">${osIcon('iOS')}</div><div><h3>А что с iPhone?${iosFirst ? `<span class="ac-tag">${tag}</span>` : ''}</h3><p>Когда появится публикация в App Store, ссылка будет здесь.</p></div><span class="ac-status is-muted">App Store · пока недоступно</span></div>`;
    const choices = [['auto', `Авто${previewSystem === 'auto' ? ` (${detected ? systemNames[detected] : 'не определена'})` : ''}`], ['windows', 'Windows'], ['macos', 'macOS'], ['linux', 'Linux'], ['android', 'Android'], ['ios', 'iOS']];
    const preview = `<div class="ac-os-preview"><span>Система посетителя в макете:</span><div class="ac-filter" role="group" aria-label="Система посетителя в макете">${choices.map(([value, label]) => `<button data-ac-system="${value}" class="${previewSystem === value ? 'selected' : ''}" aria-pressed="${previewSystem === value}">${esc(label)}</button>`).join('')}</div></div>`;
    return heading('ПРИЛОЖЕНИЕ', 'Ваш Gateway. На любом устройстве.', 'Выберите платформу и познакомьтесь с клиентом Private Gateway.') + `<div class="ac-download-banner"><div class="ac-banner-icon">${icon('shield')}</div><div><strong>Один клиент. Ваш приватный маршрут.</strong><p>Подключения настраиваются в Private Gateway. Здесь — только скачивание приложения.</p></div><span class="ac-tag">Демонстрация</span></div>${preview}${iosFirst ? ios : ''}<div class="ac-download-grid">${order.map(system => downloadCard(systemNames[system], leads[system], system === featured, tag)).join('')}</div>${iosFirst ? '' : ios}<div class="ac-download-foot">${icon('lock')}<p>Все кнопки скачивания демонстрационные. Версии, реальные файлы и ссылка на App Store будут добавлены после согласования.</p></div>`;
  }
  function memberRows() {
    const list = members.filter(member => `${member.name} ${window.PG_TRANSLATIONS?.[member.name] || member.name} ${member.email}`.toLowerCase().includes(search.toLowerCase()) && (filter === 'all' || (filter === 'active' ? member.active : !member.active)));
    if (!list.length) return `<div class="ac-empty">${icon('search')}<h3>Участники не найдены</h3><p>Попробуйте другое имя или измените фильтр.</p></div>`;
    return `<table class="ac-table"><caption class="ac-sr-only">Демонстрационные участники и доступ к кабинету</caption><thead><tr><th>Участник</th><th>Роль</th><th>Защита</th><th>Доступ к кабинету</th><th><span class="ac-sr-only">Действия</span></th></tr></thead><tbody>${list.map(member => `<tr><td><div class="ac-person"><span class="ac-avatar">${initials(member.name)}</span><div><button class="ac-name-link" data-ac-detail="${member.id}">${esc(member.name)}</button><span>${esc(member.email)}</span></div></div></td><td data-label="Роль"><span class="ac-role ${member.role === 'admin' ? 'is-admin' : ''}">${roleName(member.role)}</span></td><td data-label="Защита">${protection(member)}</td><td data-label="Доступ">${memberBadge(member)}</td><td class="ac-table-action"><button class="btn ghost ac-small-btn" data-ac-detail="${member.id}" aria-label="Карточка участника ${esc(member.name)}">Подробнее ${icon('chevron')}</button></td></tr>`).join('')}</tbody></table>`;
  }
  function membersPage() {
    const active = members.filter(member => member.active).length;
    return heading('АДМИНИСТРИРОВАНИЕ', 'Участники', 'Управляйте доступом к личному кабинету и скачиванию клиента.', `<button class="btn primary" data-ac-create-invite>${icon('plus')} Пригласить участника</button>`) + `<div class="ac-stats"><div class="card"><span>Всего участников</span><strong>${members.length}<small>демонстрационных</small></strong></div><div class="card"><span>Доступ открыт</span><strong>${active}<small>к личному кабинету</small></strong></div><div class="card"><span>Приглашения</span><strong>${invites.filter(invite => invite.status === 'active').length}<small>активных в макете</small></strong></div></div>${demoNotice}<section class="card ac-members-card"><div class="ac-table-toolbar"><label class="ac-search">${icon('search')}<input id="ac-member-search" value="${esc(search)}" placeholder="Поиск по имени или почте" aria-label="Поиск участников"></label><div class="ac-filter" role="group" aria-label="Фильтр доступа">${[['all', 'Все'], ['active', 'С доступом'], ['revoked', 'Отозван']].map(([value, label]) => `<button data-ac-filter="${value}" class="${filter === value ? 'selected' : ''}" aria-pressed="${filter === value}">${label}</button>`).join('')}</div></div><div id="ac-member-rows">${memberRows()}</div></section><p class="ac-boundary">${icon('lock')}Отзыв доступа относится только к кабинету сайта. VPN-подключения остаются в Private Gateway.</p>`;
  }
  function invitesList() {
    const list = invites.filter(invite => inviteFilter === 'all' || invite.status === inviteFilter);
    if (!list.length) return '<div class="ac-empty"><h3>Здесь пока нет приглашений</h3><p>Создайте демонстрационное приглашение или измените фильтр.</p></div>';
    return list.map(invite => `<article class="ac-invite-item"><span class="ac-invite-icon">${icon(invite.status === 'used' ? 'check' : 'mail')}</span><div class="ac-invite-info"><div><strong>${esc(invite.email)}</strong>${inviteBadge(invite.status)}</div><p>${roleName(invite.role)}<span>·</span>Срок действия: ${esc(invite.validity)}<span>·</span>Демо</p></div><div class="ac-invite-actions">${invite.status === 'active' ? `<button class="btn ghost ac-small-btn" data-ac-copy-invite="${invite.id}" aria-label="Скопировать демо-код для ${esc(invite.email)}">${icon('copy')} Код</button><button class="btn ghost ac-small-btn" data-ac-revoke-invite="${invite.id}">Отозвать</button>` : ''}<button class="btn ghost ac-small-btn" data-ac-delete-invite="${invite.id}">Удалить</button></div></article>`).join('');
  }
  function invitesPage() {
    return heading('АДМИНИСТРИРОВАНИЕ', 'Приглашения', 'Доступ по приглашению. Только для тех, кого вы хотите видеть здесь.', `<button class="btn primary" data-ac-create-invite>${icon('plus')} Создать приглашение</button>`) + `${demoNotice}<section class="card ac-invites-card"><div class="ac-invites-head"><div><h2>Приглашения в кабинет</h2><p>Почта, роль и срок действия — под вашим контролем.</p></div><label class="ac-select-label"><span class="ac-sr-only">Статус приглашения</span><select id="ac-invite-filter"><option value="all" ${inviteFilter === 'all' ? 'selected' : ''}>Все статусы</option><option value="active" ${inviteFilter === 'active' ? 'selected' : ''}>Активные</option><option value="used" ${inviteFilter === 'used' ? 'selected' : ''}>Использованные</option><option value="revoked" ${inviteFilter === 'revoked' ? 'selected' : ''}>Отозванные</option></select></label></div><div id="ac-invite-list">${invitesList()}</div></section><div class="ac-invite-help"><div class="ac-invite-help-icon">${icon('link')}</div><div><h3>Как это работает</h3><p>Создайте приглашение → передайте код получателю → он зарегистрируется по нему. По приглашению администратора нужно еще настроить 2FA. В макете все шаги демонстрационные, письма не отправляются.</p></div></div>`;
  }
  // Устройства и журнал скачиваний (2026-11-12): вымышленные данные, действия только в странице
  const sessions = [
    { id: 's1', label: 'Chrome · Windows', network: '203.0.113.0/24', seen: 'сейчас', current: true },
    { id: 's2', label: 'Safari · iOS', network: '198.51.100.0/24', seen: 'вчера, 21:40', current: false },
  ];
  const appDevices = [
    { id: 'd1', name: 'Рабочий ноутбук', platform: 'Windows', icon: 'windows', version: '0.2.0', network: '203.0.113.0/24', seen: '10 минут назад' },
    { id: 'd2', name: 'Pixel 8', platform: 'Android', icon: 'android', version: '0.2.0', network: '198.51.100.0/24', seen: 'сегодня, 08:15' },
  ];
  const downloadLog = [
    { when: '12 ноября, 10:04', member: 'Мария Орлова', email: 'maria@example.test', platform: 'Windows', icon: 'windows', version: '0.2.0', device: 'Chrome · Windows', network: '203.0.113.0/24' },
    { when: '11 ноября, 19:22', member: 'Александр Соколов', email: 'alex@example.test', platform: 'Android', icon: 'android', version: '0.2.0', device: 'Chrome · Android', network: '198.51.100.0/24' },
    { when: '9 ноября, 12:47', member: 'Мария Орлова', email: 'maria@example.test', platform: 'macOS', icon: 'apple', version: '0.1.9', device: 'Safari · macOS', network: '203.0.113.0/24' },
  ];
  const sessionLimit = 3;
  const deviceLimit = 3;
  const deviceChanges = 2;
  function devicesBlock() {
    const sessionItems = sessions.map(item => `<li class="ac-device-item"><span class="ac-device-icon">${icon('globe')}</span><div class="ac-device-info"><strong>${esc(item.label)}${item.current ? '<span class="ac-device-current">Этот браузер</span>' : ''}</strong><span>Последняя активность: ${esc(item.seen)} · Сеть ${esc(item.network)}</span></div>${item.current ? '' : `<button class="btn ghost ac-small-btn" data-ac-end-session="${item.id}">Завершить сеанс</button>`}</li>`).join('');
    const deviceItems = appDevices.length ? `<ul class="ac-device-list">${appDevices.map(item => `<li class="ac-device-item"><span class="ac-device-icon">${osIcon(item.platform)}</span><div class="ac-device-info"><strong>${esc(item.name)}</strong><span>${esc(item.platform)} · Приложение ${esc(item.version)} · Последняя активность: ${esc(item.seen)} · Сеть ${esc(item.network)}</span></div><button class="btn ghost ac-small-btn" data-ac-remove-device="${item.id}">Удалить устройство</button></li>`).join('')}</ul>` : '<p class="ac-device-empty">Устройств пока нет. Войдите в приложение этим аккаунтом.</p>';
    return `<div class="ac-devices"><section class="ac-device-group"><div class="ac-device-head"><div><h3>Входы на сайт</h3><p>Новый вход сверх лимита завершает самый давний.</p></div><span class="ac-device-count">${sessions.length} из ${sessionLimit} занято</span></div><ul class="ac-device-list">${sessionItems}</ul></section><section class="ac-device-group"><div class="ac-device-head"><div><h3>Приложение Private Gateway</h3><p>Устройства, где выполнен вход в приложение. Удалите устройство, чтобы освободить место для другого.</p></div><span class="ac-device-count">${appDevices.length} из ${deviceLimit} занято</span></div><p class="ac-device-changes"><strong>Новых устройств за 30 дней: ${deviceChanges} из 3</strong> Новое устройство — первый вход установки приложения. Повторный вход на том же устройстве не считается, удаленные администратором — тоже.</p>${deviceItems}</section></div>`;
  }
  // 2026-11-13: смена пароля и выход на всех устройствах; администратор подтверждает кодом 2FA
  const securityCard = () => `<section class="card ac-security-card"><div><h3>Пароль и вход</h3><p>Смена пароля и выход на всех устройствах завершают остальные входы на сайт и выходят из приложения на всех устройствах. Этот браузер остается в аккаунте.</p></div><div class="ac-security-actions"><button class="btn" data-ac-own="password">${icon('key')}Сменить пароль</button><button class="btn" data-ac-own="everywhere">${icon('logout')}Выйти на всех устройствах</button></div></section>`;
  function devicesPage() {
    return heading('БЕЗОПАСНОСТЬ', 'Ваши устройства', 'Где выполнен вход на этот сайт и в приложение Private Gateway.') + securityCard() + `<section class="card ac-devices-card">${devicesBlock()}</section>` + demoNotice;
  }
  function downloadLogPage() {
    const rows = downloadLog.map(item => `<tr><td data-label="Когда">${esc(item.when)}</td><td data-label="Участник"><div class="ac-person"><span class="ac-avatar">${initials(item.member)}</span><div><strong>${esc(item.member)}</strong><span>${esc(item.email)}</span></div></div></td><td data-label="Платформа"><span class="ac-log-platform">${osIcon(item.platform)}${esc(item.platform)} ${esc(item.version)}</span></td><td data-label="Устройство">${esc(item.device)}</td><td data-label="Сеть">${esc(item.network)}</td></tr>`).join('');
    return heading('АДМИНИСТРИРОВАНИЕ', 'Журнал скачиваний', 'Кто и когда скачивал клиент. Адреса хранятся без последних цифр.') + `<section class="card ac-members-card"><table class="ac-table ac-log-table"><thead><tr><th>Когда</th><th>Участник</th><th>Платформа</th><th>Устройство</th><th>Сеть</th></tr></thead><tbody>${rows}</tbody></table></section>` + demoNotice;
  }
  PG.account = (route) => {
    if (route.startsWith('admin-') && PG.state.role !== 'admin') return shell(route, `<div class="ac-denied"><span class="ac-banner-icon">${icon('lock')}</span><h1>Этот раздел — для администратора</h1><p>В роли участника доступно скачивание приложения.</p><button class="btn primary" data-account-route="downloads">К скачиванию ${icon('arrow')}</button></div>`);
    return shell(route, route === 'downloads' ? downloads() : route === 'devices' ? devicesPage() : route === 'admin-members' ? membersPage() : route === 'admin-downloads' ? downloadLogPage() : invitesPage());
  };
  function refresh(route) {
    const root = document.getElementById('pg-account');
    if (!root) return;
    root.outerHTML = PG.account(route);
    PG.bindAccount(route);
  }
  function closeModal() { document.getElementById('ac-dialog')?.remove(); }
  function modal(title, body, footer = '') {
    closeModal();
    const dialog = document.createElement('dialog');
    dialog.id = 'ac-dialog';
    dialog.className = 'ac-dialog';
    dialog.setAttribute('aria-labelledby', 'ac-dialog-title');
    dialog.innerHTML = `<div class="ac-dialog-head"><div><span class="eyebrow">ДЕМОНСТРАЦИЯ</span><h2 id="ac-dialog-title">${title}</h2></div><button class="ac-close" data-ac-close aria-label="Закрыть">${icon('close')}</button></div><div class="ac-dialog-body">${body}</div>${footer ? `<div class="ac-dialog-footer">${footer}</div>` : ''}`;
    document.getElementById('pg-account').append(dialog);
    dialog.addEventListener('cancel', (event) => { event.preventDefault(); closeModal(); });
    dialog.addEventListener('click', (event) => { if (event.target === dialog || event.target.closest('[data-ac-close]')) closeModal(); });
    dialog.showModal();
    return dialog;
  }
  async function copyCode(code) {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(code);
      else throw new Error('clipboard-unavailable');
      PG.toast('Демонстрационный код скопирован');
    } catch {
      const dialog = modal('Скопируйте демо-код', `<p>Автоматическое копирование недоступно. Выделите и скопируйте код вручную.</p><input class="ac-code-input" value="${esc(code)}" readonly aria-label="Демонстрационный код приглашения">`, '<button class="btn" data-ac-close>Готово</button>');
      const input = dialog.querySelector('input'); input.focus(); input.select();
    }
  }
  function inviteForm(route) {
    const dialog = modal('Пригласить в Private Gateway Web', `<p class="ac-modal-intro">Приглашение дает доступ только к кабинету со скачиванием приложения. Введите вымышленную почту — никаких писем не отправляем.</p><form id="ac-invite-form"><label class="ac-field">Электронная почта<input type="email" name="email" placeholder="name@example.test" required autocomplete="off" maxlength="120"></label><div class="ac-form-grid"><label class="ac-field">Роль<select name="role" id="ac-new-role"><option value="member">Участник</option><option value="admin">Администратор</option></select></label><label class="ac-field">Срок действия<select name="validity"><option>7 дней</option><option>3 дня</option><option>24 часа</option></select></label></div><div class="ac-role-hint" id="ac-role-hint">Участник входит по паролю и скачивает клиент.</div><div id="ac-admin-otp" hidden><label class="ac-field">Код 2FA администратора<input name="otp" inputmode="numeric" autocomplete="off" placeholder="123456" pattern="123456" maxlength="6"></label><p class="ac-otp-hint">Демонстрационный код: <b>123456</b>. Настоящая проверка не выполняется.</p></div><p class="ac-form-error" id="ac-invite-error" role="alert"></p></form>`, '<button class="btn" data-ac-close>Отмена</button><button class="btn primary" type="submit" form="ac-invite-form">Создать демо-приглашение</button>');
    const roleInput = dialog.querySelector('#ac-new-role');
    roleInput.onchange = () => {
      const admin = roleInput.value === 'admin';
      dialog.querySelector('#ac-admin-otp').hidden = !admin;
      dialog.querySelector('[name="otp"]').required = admin;
      dialog.querySelector('#ac-role-hint').textContent = admin ? 'Администратор также управляет участниками и приглашениями и при регистрации настраивает 2FA.' : 'Участник входит по паролю и скачивает клиент.';
    };
    dialog.querySelector('form').onsubmit = (event) => {
      event.preventDefault();
      const data = new FormData(event.target);
      const email = String(data.get('email')).trim().toLowerCase();
      const role = data.get('role') === 'admin' ? 'admin' : 'member';
      if (!event.target.checkValidity()) { event.target.reportValidity(); return; }
      if (members.some(member => member.email === email) || invites.some(invite => invite.email === email && invite.status === 'active')) {
        dialog.querySelector('#ac-invite-error').textContent = 'Для этой почты уже есть участник или активное демо-приглашение.'; return;
      }
      const code = `PG-DEMO-${String(++sequence).padStart(4, '0')}`;
      const invite = { id: `i${sequence + 1}`, email, role, validity: String(data.get('validity')), status: 'active', code };
      invites.unshift(invite);
      closeModal(); refresh(route);
      modal('Демо-приглашение создано', `<div class="ac-success-mark">${icon('check')}</div><p>Демонстрационный код для <strong>${esc(email)}</strong>.</p><div class="ac-code-box"><code>${esc(code)}</code><button class="btn ghost" data-ac-copy-code="${esc(code)}" aria-label="Скопировать демо-код">${icon('copy')}</button></div><dl class="ac-details"><div><dt>Роль</dt><dd>${roleName(role)}</dd></div><div><dt>Срок действия</dt><dd>${esc(invite.validity)}</dd></div></dl><p class="ac-otp-hint">Этот код существует только в макете. Передача письма и реальная регистрация не выполняются.</p>`, `<button class="btn" data-ac-close>Готово</button><button class="btn primary" data-ac-preview-register="${invite.id}">Посмотреть регистрацию ${icon('arrow')}</button>`);
      PG.toast('Демо-приглашение добавлено');
    };
  }
  function memberDetail(member, route) {
    modal('Карточка участника', `<div class="ac-member-profile"><span class="ac-avatar large">${initials(member.name)}</span><div><h3>${esc(member.name)}</h3><p>${esc(member.email)}</p></div></div><dl class="ac-details"><div><dt>Роль</dt><dd>${roleName(member.role)}</dd></div><div><dt>Личный кабинет</dt><dd>${memberBadge(member)}</dd></div><div><dt>Защита входа</dt><dd>${protection(member)}</dd></div><div><dt>Данные</dt><dd>Вымышленный участник</dd></div></dl><dl class="ac-details"><div><dt>Устройства приложения</dt><dd>${appDevices.length} из ${deviceLimit} · лимит по умолчанию</dd></div></dl><div class="ac-member-actions"><button class="btn" data-ac-limit>Изменить лимит устройств</button><button class="btn" data-account-route="admin-downloads">${icon('history')}История скачиваний</button></div><div class="ac-role-hint">Здесь нет VPN-профилей, ссылок подписки и управления соединениями.</div>${member.id === 'm1' ? '' : `<div class="ac-member-actions ac-member-danger"><button class="btn ac-danger-text" data-ac-delete-member="${member.id}">${icon('close')}Удалить участника</button></div>`}`, `<button class="btn" data-ac-close>Закрыть</button>${member.active ? `<button class="btn ac-danger" data-ac-revoke-member="${member.id}">Отозвать доступ к кабинету</button>` : ''}`);
  }
  function revokeMember(member, route, secondStep = false) {
    const dialog = modal(secondStep ? 'Подтвердите действие кодом 2FA' : 'Отозвать доступ к кабинету?', secondStep ? `<p>Подтверждение отзыва для <strong>${esc(member.name)}</strong>.</p><form id="ac-revoke-form"><label class="ac-field">Демонстрационный код 2FA<input name="otp" inputmode="numeric" maxlength="6" pattern="123456" placeholder="123456" autocomplete="off" required></label><p class="ac-otp-hint">Введите <b>123456</b>. Это имитация шага защиты, без проверки на сервере.</p></form>` : `<p><strong>${esc(member.name)}</strong> потеряет доступ к личному кабинету и скачиванию клиента в этой демонстрации.</p><div class="ac-role-hint">VPN-подключения и устройства не затрагиваются. Их управление остается в Private Gateway.</div>`, `<button class="btn" data-ac-close>Отмена</button>${secondStep ? '<button class="btn ac-danger" type="submit" form="ac-revoke-form">Подтвердить отзыв</button>' : '<button class="btn ac-danger" id="ac-revoke-next">Продолжить с 2FA</button>'}`);
    if (!secondStep) dialog.querySelector('#ac-revoke-next').onclick = () => revokeMember(member, route, true);
    else dialog.querySelector('form').onsubmit = (event) => {
      event.preventDefault();
      if (!event.target.checkValidity()) { event.target.reportValidity(); return; }
      member.active = false;
      closeModal(); refresh(route);
      PG.toast('В макете доступ к кабинету отозван. VPN не затронут.');
    };
  }
  // Удаление с кодом 2FA администратора: участник целиком или приглашение в любом состоянии
  function confirmDelete(title, body, onConfirm) {
    const dialog = modal(title, `${body}<form id="ac-delete-form"><label class="ac-field">Демонстрационный код 2FA<input name="otp" inputmode="numeric" maxlength="6" pattern="123456" placeholder="123456" autocomplete="off" required></label><p class="ac-otp-hint">Введите <b>123456</b>. Это имитация шага защиты, без проверки на сервере.</p></form>`, `<button class="btn" data-ac-close>Отмена</button><button class="btn ac-danger" type="submit" form="ac-delete-form">Удалить</button>`);
    dialog.querySelector('form').onsubmit = (event) => {
      event.preventDefault();
      if (!event.target.checkValidity()) { event.target.reportValidity(); return; }
      onConfirm();
    };
  }
  function deleteMember(member, route) {
    confirmDelete('Удалить участника?', `<p><strong>${esc(member.name)}</strong></p><p>Аккаунт и все связанные данные будут удалены: входы, устройства приложения, коды и приглашения на эту почту. Записи журнала скачиваний останутся как «Удаленный участник». Отменить нельзя.</p>`, () => {
      members.splice(members.indexOf(member), 1);
      downloadLog.forEach(item => { if (item.email === member.email) { item.member = 'Удаленный участник'; item.email = ''; } });
      closeModal(); refresh(route); PG.toast('В макете участник удален.');
    });
  }
  function deleteInvite(invite, route) {
    confirmDelete('Удалить приглашение?', `<p><strong>${esc(invite.email)}</strong></p><p>Приглашение исчезнет из списка. Действующее приглашение сразу перестанет работать.</p>`, () => {
      invites.splice(invites.indexOf(invite), 1);
      closeModal(); refresh(route); PG.toast('Демо-приглашение удалено');
    });
  }
  function ownAccess(kind) {
    const admin = PG.state.role === 'admin';
    const password = kind === 'password';
    const fields = `${password ? '<label class="ac-field">Текущий пароль<input type="password" name="current" autocomplete="off" required></label><label class="ac-field">Новый пароль<input type="password" name="next" autocomplete="off" minlength="12" required></label><p class="ac-otp-hint">12–128 символов. Используйте уникальный пароль.</p>' : ''}${admin ? '<label class="ac-field">Демонстрационный код 2FA<input name="otp" inputmode="numeric" maxlength="6" pattern="123456" placeholder="123456" autocomplete="off" required></label><p class="ac-otp-hint">Администратор подтверждает действие кодом 2FA. В макете — <b>123456</b>.</p>' : ''}`;
    const dialog = modal(password ? 'Сменить пароль' : 'Выйти на всех устройствах', `<p>${password ? 'После смены войдите в приложение на своих устройствах с новым паролем.' : 'Все остальные входы на сайт завершатся, приложение выйдет на всех устройствах. Пароль не меняется.'}</p><form id="ac-own-form">${fields}</form>`, `<button class="btn" data-ac-close>Отмена</button><button class="btn ${password ? 'primary' : 'ac-danger'}" type="submit" form="ac-own-form">${password ? 'Сменить пароль' : 'Выйти на всех устройствах'}</button>`);
    dialog.querySelector('form').onsubmit = (event) => {
      event.preventDefault();
      if (!event.target.checkValidity()) { event.target.reportValidity(); return; }
      sessions.splice(0, sessions.length, ...sessions.filter(item => item.current));
      appDevices.splice(0, appDevices.length);
      closeModal(); refresh('devices');
      PG.toast(password ? 'Пароль изменен. Остальные входы завершены.' : 'Остальные входы завершены. Этот браузер остался в аккаунте.');
    };
  }
  function revokeInvite(invite, route) {
    const dialog = modal('Отозвать приглашение?', `<p>Демонстрационное приглашение для <strong>${esc(invite.email)}</strong> больше не будет активно в списке.</p><p class="ac-otp-hint">Действие касается только этого макета и сбросится при обновлении страницы.</p>`, '<button class="btn" data-ac-close>Отмена</button><button class="btn ac-danger" id="ac-confirm-revoke-invite">Отозвать приглашение</button>');
    dialog.querySelector('#ac-confirm-revoke-invite').onclick = () => {
      invite.status = 'revoked'; closeModal(); refresh(route); PG.toast('Демо-приглашение отозвано');
    };
  }
  PG.bindAccount = (route) => {
    const root = document.getElementById('pg-account');
    if (!root) return;
    root.onclick = (event) => {
      const button = event.target.closest('button');
      if (!button || !root.contains(button)) return;
      const data = button.dataset;
      if (data.accountRoute) { closeModal(); PG.navigate(data.accountRoute); return; }
      if (data.acDownload) {
        modal(`Private Gateway для ${esc(data.acDownload)}`, `<div class="ac-download-modal-icon">${osIcon(data.acDownload)}</div><p>Здесь будет скачивание клиента для <strong>${esc(data.acDownload)}${data.acDownload === 'macOS' ? ` · ${esc(architecture)}` : ''}</strong>.</p><div class="ac-role-hint">Макет · файл не подключен. Версия и реальная ссылка не заданы. Никакие файлы не скачиваются.</div>`, '<button class="btn primary" data-ac-close>Понятно</button>'); return;
      }
      if (data.acArch) { architecture = data.acArch; refresh(route); return; }
      if (data.acSystem) { previewSystem = data.acSystem; refresh(route); return; }
      if (data.acOwn) { ownAccess(data.acOwn); return; }
      if (data.acEndSession) { const index = sessions.findIndex(item => item.id === data.acEndSession); if (index >= 0) sessions.splice(index, 1); refresh(route); PG.toast('В макете сеанс завершен.'); return; }
      if (data.acRemoveDevice) { const index = appDevices.findIndex(item => item.id === data.acRemoveDevice); if (index >= 0) appDevices.splice(index, 1); refresh(route); PG.toast('В макете устройство удалено: приложение на нем попросит войти снова.'); return; }
      if (PG.state.role !== 'admin') return;
      if ('acCreateInvite' in data) { inviteForm(route); return; }
      if (data.acFilter) { filter = data.acFilter; refresh(route); return; }
      if ('acLimit' in data) { PG.toast('В макете лимит меняется после кода 2FA: число от 1 до 50 или пусто — лимит по умолчанию.'); return; }
      if (data.acDetail) { const member = members.find(item => item.id === data.acDetail); if (member) memberDetail(member, route); return; }
      if (data.acRevokeMember) { const member = members.find(item => item.id === data.acRevokeMember); if (member) revokeMember(member, route); return; }
      if (data.acRevokeInvite) { const invite = invites.find(item => item.id === data.acRevokeInvite); if (invite) revokeInvite(invite, route); return; }
      if (data.acDeleteInvite) { const invite = invites.find(item => item.id === data.acDeleteInvite); if (invite) deleteInvite(invite, route); return; }
      if (data.acDeleteMember) { const member = members.find(item => item.id === data.acDeleteMember); if (member) deleteMember(member, route); return; }
      if (data.acPreviewRegister) {
        const invite = invites.find(item => item.id === data.acPreviewRegister);
        if (invite && invite.status === 'active') { PG.state.invitation = { code: invite.code, email: invite.email, role: invite.role, id: invite.id }; closeModal(); PG.navigate('invite'); }
        return;
      }
      if (data.acCopyInvite) { const invite = invites.find(item => item.id === data.acCopyInvite); if (invite) copyCode(invite.code); return; }
      if (data.acCopyCode) copyCode(data.acCopyCode);
    };
    root.querySelector('#ac-member-search')?.addEventListener('input', (event) => {
      search = event.target.value;
      root.querySelector('#ac-member-rows').innerHTML = memberRows();
    });
    root.querySelector('#ac-invite-filter')?.addEventListener('change', (event) => {
      inviteFilter = event.target.value;
      root.querySelector('#ac-invite-list').innerHTML = invitesList();
    });
  };
})();
