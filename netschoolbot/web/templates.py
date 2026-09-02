"""HTML-шаблоны веб-панели и мини-приложения NetSchool."""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Вход — Панель управления</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #e6edf3; font-family: 'Segoe UI', sans-serif;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
          padding: 40px; width: 340px; }
  h1 { font-size: 1.5rem; margin-bottom: 8px; }
  p { color: #8b949e; font-size: .85rem; margin-bottom: 28px; }
  label { display: block; font-size: .85rem; color: #8b949e; margin-bottom: 6px; }
  input { width: 100%; padding: 10px 14px; background: #0d1117; border: 1px solid #30363d;
          border-radius: 8px; color: #e6edf3; font-size: .95rem; margin-bottom: 16px; }
  input:focus { outline: none; border-color: #388bfd; }
  button { width: 100%; padding: 10px; background: #238636; border: none; border-radius: 8px;
           color: #fff; font-size: 1rem; cursor: pointer; font-weight: 600; }
  button:hover { background: #2ea043; }
  .err { color: #f85149; font-size: .85rem; margin-top: 12px; text-align: center; }
</style>
</head>
<body>
<div class="card">
  <h1>🖥 Панель управления</h1>
  <p>Терминал &amp; файловый менеджер VDS</p>
  <form method="POST">
    <label>Логин</label>
    <input name="username" type="text" autofocus autocomplete="username">
    <label>Пароль</label>
    <input name="password" type="password" autocomplete="current-password">
    <button type="submit">Войти</button>
    {% if error %}<p class="err">{{ error }}</p>{% endif %}
  </form>
</div>
</body>
</html>"""

MAIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Панель управления</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static_web/xterm.min.css?v={{ static_version }}">
<script src="/static_web/xterm.min.js?v={{ static_version }}"></script>
<script src="/static_web/xterm-addon-fit.min.js?v={{ static_version }}"></script>
<script src="/static_web/socket.io.min.js?v={{ static_version }}"></script>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --accent: #388bfd; --green: #238636; --red: #da3633;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text);
         font-family: 'Segoe UI', sans-serif; height: 100vh;
         display: flex; flex-direction: column; overflow: hidden; }

  /* Header */
  header { background: var(--surface); border-bottom: 1px solid var(--border);
           padding: 0 20px; height: 50px; display: flex; align-items: center;
           gap: 16px; flex-shrink: 0; }
  header h1 { font-size: 1rem; font-weight: 600; }
  header span { color: var(--muted); font-size: .8rem; margin-left: auto; }
  .btn-sm { padding: 5px 12px; border-radius: 6px; border: 1px solid var(--border);
            background: transparent; color: var(--text); cursor: pointer;
            font-size: .85rem; }
  .btn-sm:hover { background: var(--border); }

  /* Tabs */
  .tabs { background: var(--surface); border-bottom: 1px solid var(--border);
          display: flex; padding: 0 12px; flex-shrink: 0; }
  .tab { padding: 10px 18px; cursor: pointer; font-size: .9rem; border-bottom: 2px solid transparent;
         white-space: nowrap; color: var(--muted); transition: all .15s; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }

  /* Panels */
  .panel { flex: 1; overflow: hidden; display: none; flex-direction: column; }
  .panel.active { display: flex; }

  /* Terminal panels */
  .term-toolbar { padding: 8px 12px; background: var(--surface);
                  border-bottom: 1px solid var(--border);
                  display: flex; gap: 8px; align-items: center; flex-shrink: 0; flex-wrap: wrap; }
  .term-toolbar input { flex: 1; background: var(--bg); border: 1px solid var(--border);
                        border-radius: 6px; padding: 4px 10px; color: var(--text);
                        font-size: .9rem; font-family: monospace; height: 32px; }
  .term-toolbar input:focus { outline: none; border-color: var(--accent); }
  .cmd-input { min-width: 220px; max-width: 520px; }
  .btn-run { padding: 0 14px; background: var(--green); border: none; border-radius: 6px;
             color: white; cursor: pointer; font-size: .85rem; height: 32px; line-height: 32px; }
  .btn-run:hover { filter: brightness(1.1); }
  .btn-clear { padding: 0 14px; background: transparent; border: 1px solid var(--border);
               border-radius: 6px; color: var(--muted); cursor: pointer; font-size: .85rem;
               height: 32px; line-height: 32px; }
  .service-controls { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
                      gap: 6px; width: 100%; flex: 1 0 100%; }
  .service-controls button { width: 100%; min-width: 0; white-space: nowrap; }
  #term-netschoolbot, #term-nginx, #term-custom { flex: 1; padding: 4px; overflow: hidden; }

  /* File manager */
  .fm-toolbar { padding: 10px 14px; background: var(--surface);
                border-bottom: 1px solid var(--border);
                display: flex; gap: 8px; align-items: center; flex-shrink: 0; flex-wrap: wrap; }
  .path-display { flex: 1; font-family: monospace; font-size: .85rem;
                  background: var(--bg); border: 1px solid var(--border);
                  border-radius: 6px; padding: 6px 10px; color: var(--muted); min-width: 200px; }
  .fm-btn { padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border);
            background: transparent; color: var(--text); cursor: pointer; font-size: .82rem; }
  .fm-btn:hover { background: var(--border); }
  .fm-btn.danger { border-color: var(--red); color: var(--red); }
  .fm-btn.danger:hover { background: var(--red); color: white; }
  .fm-btn.primary { background: var(--accent); border-color: var(--accent); color: white; }
  .fm-btn.primary:hover { filter: brightness(1.1); }

  .fm-list { flex: 1; overflow-y: auto; }
  table { width: 100%; border-collapse: collapse; }
  th { position: sticky; top: 0; background: var(--surface); padding: 8px 12px;
       text-align: left; font-size: .8rem; color: var(--muted);
       border-bottom: 1px solid var(--border); }
  td { padding: 7px 12px; border-bottom: 1px solid #21262d; font-size: .88rem; }
  tr:hover td { background: #1c2128; }
  .entry-name { cursor: pointer; color: var(--accent); }
  .entry-name:hover { text-decoration: underline; }
  .icon { margin-right: 6px; }
  .file-actions { display: flex; gap: 4px; }
  .fa-btn { padding: 3px 8px; border-radius: 4px; border: 1px solid var(--border);
            background: transparent; color: var(--muted); cursor: pointer; font-size: .78rem; }
  .fa-btn:hover { background: var(--border); color: var(--text); }

  /* Editor modal */
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.7);
                   z-index: 999; display: none; align-items: center; justify-content: center; }
  .modal-overlay.open { display: flex; }
  .modal { background: var(--surface); border: 1px solid var(--border);
           border-radius: 12px; width: 90vw; max-width: 900px; height: 80vh;
           display: flex; flex-direction: column; }
  .modal-header { padding: 14px 18px; border-bottom: 1px solid var(--border);
                  display: flex; align-items: center; gap: 10px; }
  .modal-header h3 { flex: 1; font-size: 1rem; }
  .modal-body { flex: 1; display: flex; overflow: hidden; }
  textarea.editor { flex: 1; background: var(--bg); border: none; color: var(--text);
                    font-family: 'Cascadia Code', 'Fira Code', monospace;
                    font-size: .9rem; padding: 14px; resize: none;
                    tab-size: 4; line-height: 1.5; }
  textarea.editor:focus { outline: none; }
  .modal-footer { padding: 10px 18px; border-top: 1px solid var(--border);
                  display: flex; justify-content: flex-end; gap: 8px; }
  .pwd-input { width: 100%; height: 32px; padding: 4px 10px; background: var(--bg);
               border: 1px solid var(--border); border-radius: 6px; color: var(--text);
               font-size: .9rem; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

  /* Mobile responsive styles */
  @media (max-width: 768px) {
    body { height: 100svh; } /* Safe area viewport height */
    
    /* Header adjustments */
    header { padding: 0 12px; height: 48px; flex-wrap: wrap; }
    header h1 { font-size: .9rem; }
    header span { font-size: .75rem; }
    .btn-sm { padding: 4px 10px; font-size: .78rem; }
    
    /* Tabs - scrollable */
    .tabs { overflow-x: auto; overflow-y: hidden; padding: 0 8px;
            -webkit-overflow-scrolling: touch; }
    .tab { padding: 8px 14px; font-size: .85rem; min-width: max-content; }
    
    /* Terminal toolbar - stack vertically on small screens */
    .term-toolbar { flex-wrap: wrap; padding: 8px; gap: 6px; }
    .term-toolbar span { width: 100%; font-size: .78rem; }
    .cmd-input { min-width: 100%; max-width: 100%; font-size: .85rem; flex: 1 1 100%; }
    .btn-run, .btn-clear { flex: 1 1 auto; min-width: 80px; font-size: .8rem; height: 36px; line-height: 36px; white-space: nowrap; }
    #term-netschoolbot, #term-nginx, #term-custom { padding: 2px; }
    .service-controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; width: 100%; }
    .service-controls button { min-width: 0; }
    
    /* File manager toolbar - stack */
    .fm-toolbar { flex-wrap: wrap; padding: 8px; gap: 6px; }
    .path-display { width: 100%; min-width: 100%; font-size: .78rem; padding: 5px 8px; }
    .fm-btn { flex: 1; font-size: .78rem; padding: 5px 10px; }
    
    /* Table adjustments */
    th, td { padding: 6px 8px; font-size: .8rem; }
    .icon { margin-right: 4px; }
    .fa-btn { padding: 3px 6px; font-size: .72rem; }
    
    /* Modal - full screen on mobile */
    .modal { width: 100vw; height: 100vh; max-width: 100vw;
             border-radius: 0; margin: 0; }
    .modal-header { padding: 12px 12px; }
    .modal-header h3 { font-size: .95rem; }
    textarea.editor { font-size: .85rem; padding: 10px; }
    .modal-footer { padding: 8px 12px; }
    .pwd-input { font-size: .85rem; }
  }
  
  @media (max-width: 480px) {
    /* Extra small screens */
    header { height: auto; min-height: 48px; }
    header h1 { font-size: .85rem; width: 100%; margin-bottom: 6px; }
    .tab { padding: 8px 12px; font-size: .8rem; }
    
    /* Hide file size/date columns on very small screens */
    .hide-on-tiny { display: none; }
    
    /* Stack buttons vertically */
    .file-actions { flex-direction: column; gap: 2px; }
    .fa-btn { width: 100%; }
  }
</style>
</head>
<body>
<header>
  <h1>🖥 Панель управления VDS</h1>
  <button class="btn-sm" id="btn-change-pass">Сменить пароль</button>
  <button class="btn-sm" id="btn-logout">Выйти</button>
</header>
<div id="notice" style="display:none; background:#2b1d1d; color:#ffb4b4; padding:8px 14px; border-bottom:1px solid #3b2a2a; font-size:.85rem;"></div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('netschoolbot')">🤖 Лог: NetSchoolBot</div>
  <div class="tab" onclick="switchTab('nginx')">🌐 Лог: nginx</div>
  <div class="tab" onclick="switchTab('custom')">⌨️ Терминал</div>
  <div class="tab" onclick="switchTab('filemgr')">📂 Файлы</div>
</div>

<!-- Панель: лог netschoolbot -->
<div class="panel active" id="panel-netschoolbot">
  <div class="term-toolbar">
    <span style="color:var(--muted);font-size:.85rem">Служба: netschoolbot.service</span>
    <div class="service-controls">
      <button class="btn-run" style="background:var(--green)" onclick="serviceControl('netschoolbot', 'start')">▶ Запустить</button>
      <button class="btn-clear" onclick="serviceControl('netschoolbot', 'stop')">⏸ Остановить</button>
      <button class="btn-run" onclick="serviceControl('netschoolbot', 'restart')">🔄 Перезапустить</button>
      <button class="btn-clear" style="color:var(--red);border-color:var(--red)" onclick="serviceControl('netschoolbot', 'kill')">💀 Убить</button>
    </div>
    <input id="cmd-netschoolbot" class="cmd-input" placeholder="Команда (bash)"
           onkeydown="onCmdKey(event, 'netschoolbot')">
    <button class="btn-run" onclick="runCommand('netschoolbot')">▶ Выполнить</button>
    <input id="in-netschoolbot" class="cmd-input" placeholder="Ввод в скрипт"
           onkeydown="onScriptInputKey(event)">
    <button class="btn-run" onclick="sendScriptInput()">➡ Ввести</button>
    <button class="btn-clear" onclick="clearTerm('netschoolbot')">Очистить</button>
    <button class="btn-run" onclick="connectLog('netschoolbot')">↺ Переподключить</button>
  </div>
  <div id="term-netschoolbot"></div>
</div>

<!-- Панель: лог nginx -->
<div class="panel" id="panel-nginx">
  <div class="term-toolbar">
    <span style="color:var(--muted);font-size:.85rem">Служба: nginx.service</span>
    <div class="service-controls">
      <button class="btn-run" onclick="serviceControl('nginx', 'restart')">🔄 Перезапустить</button>
      <button class="btn-clear" onclick="clearTerm('nginx')">Очистить</button>
    </div>
    <input id="cmd-nginx" class="cmd-input" placeholder="Команда (bash)"
           onkeydown="onCmdKey(event, 'nginx')">
    <button class="btn-run" onclick="runCommand('nginx')">▶ Выполнить</button>
    <button class="btn-run" onclick="connectLog('nginx')">↺ Переподключить</button>
  </div>
  <div id="term-nginx"></div>
</div>

<!-- Панель: интерактивный терминал -->
<div class="panel" id="panel-custom">
  <div class="term-toolbar">
    <span style="color:var(--muted);font-size:.85rem">Bash-терминал (полнофункциональный)</span>
    <button class="btn-clear" onclick="clearTerm('custom')">Очистить</button>
    <button class="btn-run" onclick="reconnectCustom()">↺ Новая сессия</button>
  </div>
  <div id="term-custom"></div>
</div>

<!-- Панель: файловый менеджер -->
<div class="panel" id="panel-filemgr">
  <div class="fm-toolbar">
    <button class="fm-btn" onclick="fmNav('..')">⬆ Вверх</button>
    <div class="path-display" id="fm-path">/</div>
    <button class="fm-btn" onclick="fmRefresh()">↺</button>
    <button class="fm-btn" onclick="fmGo('/opt/netschoolbot')">🐍 Скрипт Python</button>
    <button class="fm-btn" onclick="fmGo('/var/www/html')">🌐 ARSBB сайт</button>
    <button class="fm-btn" onclick="fmGo('/')">🗂 Все файлы</button>
    <button class="fm-btn primary" onclick="uploadFile()">⬆ Загрузить</button>
    <button class="fm-btn" onclick="newFile()">+ Файл</button>
    <button class="fm-btn" onclick="newFolder()">+ Папка</button>
    <input type="file" id="file-upload-input" multiple style="display:none"
           onchange="doUpload(this)">
  </div>
  <div class="fm-list">
    <table id="fm-table">
      <thead><tr>
        <th style="width:50%">Имя</th>
        <th class="hide-on-tiny">Размер</th>
        <th class="hide-on-tiny">Изменён</th>
        <th>Действия</th>
      </tr></thead>
      <tbody id="fm-tbody"></tbody>
    </table>
  </div>
</div>

<!-- Редактор -->
<div class="modal-overlay" id="editor-modal">
  <div class="modal">
    <div class="modal-header">
      <h3 id="editor-title">Редактор</h3>
      <button class="btn-sm" onclick="closeEditor()">✕</button>
    </div>
    <div class="modal-body">
      <textarea class="editor" id="editor-content" spellcheck="false"></textarea>
    </div>
    <div class="modal-footer">
      <button class="fm-btn" onclick="closeEditor()">Отмена</button>
      <button class="fm-btn primary" onclick="saveFile()">💾 Сохранить</button>
    </div>
  </div>
</div>

<!-- Смена пароля -->
<div class="modal-overlay" id="pwd-modal">
  <div class="modal">
    <div class="modal-header">
      <h3>Смена пароля</h3>
      <button class="btn-sm" onclick="closePwdModal()">✕</button>
    </div>
    <div class="modal-body" style="padding: 16px;">
      <label style="font-size:.85rem; color:var(--muted); margin-bottom:6px; display:block;">Текущий пароль</label>
      <input id="pwd-current" type="password" class="pwd-input" style="margin-bottom:12px;">
      <label style="font-size:.85rem; color:var(--muted); margin-bottom:6px; display:block;">Новый пароль</label>
      <input id="pwd-new" type="password" class="pwd-input" style="margin-bottom:12px;">
      <label style="font-size:.85rem; color:var(--muted); margin-bottom:6px; display:block;">Повторите новый пароль</label>
      <input id="pwd-new2" type="password" class="pwd-input">
      <div id="pwd-error" style="color:#f85149; font-size:.85rem; margin-top:10px; display:none;"></div>
    </div>
    <div class="modal-footer">
      <button class="fm-btn" onclick="closePwdModal()">Отмена</button>
      <button class="fm-btn primary" onclick="changePassword()">💾 Сохранить</button>
    </div>
  </div>
</div>

<script>
let socket = null;
const notice = document.getElementById('notice');
const basePath = window.location.pathname.startsWith('/panel') ? '/panel' : '';
const API_BASE = basePath + '/api';

function apiUrl(path) {
  return API_BASE + path;
}
function openFeedback(kind){
  const base='https://github.com/Vladcom4iiik/max_telegram_netschoolbot/issues/new';
  const mode=kind==='feature'?'feature_request':'bug_report';
  const title=kind==='feature'?'[Feature] ':'[Bug] ';
  const body=kind==='feature'
    ? 'Что хочется добавить?%0A%0AКак это должно работать?%0A%0AГде это должно быть в mini app?'
    : 'Что сломалось?%0A%0AКак повторить?%0A%0AЧто ожидалось?%0A%0AУстройство и режим: PWA / Telegram WebView / Safari';
  window.open(base+'?template='+mode+'.md&title='+encodeURIComponent(title)+'&body='+body,'_blank','noopener');
}

function initHeaderActions() {
  const logoutBtn = document.getElementById('btn-logout');
  if (logoutBtn) logoutBtn.onclick = () => { location.href = basePath + '/logout'; };
  const passBtn = document.getElementById('btn-change-pass');
  if (passBtn) passBtn.onclick = () => openPwdModal();
}

function showNotice(msg) {
  if (!notice) return;
  notice.textContent = msg;
  notice.style.display = 'block';
}

if (typeof io !== 'undefined') {
  socket = io();
  socket.on('connect', () => {
    connectLog('netschoolbot');
    connectLog('nginx');
    enableLogScrollLoad('netschoolbot');
    enableLogScrollLoad('nginx');
  });
  socket.on('disconnect', () => {
    showNotice('⚠️ Соединение потеряно. Переподключение...');
  });
  socket.on('reconnect', () => {
    showNotice('✅ Соединение восстановлено');
    setTimeout(() => { notice.style.display = 'none'; }, 3000);
  });
} else {
  showNotice('Не удалось загрузить Socket.IO. Проверьте доступ к /static_web/socket.io.min.js');
}

// Restore active tab from localStorage
try {
  const savedTab = localStorage.getItem('webterm_active_tab');
  if (savedTab && ['netschoolbot','nginx','custom','filemgr'].includes(savedTab)) {
    setTimeout(() => switchTab(savedTab), 100);
  }
} catch(e) {}
let terms = {};
let fitAddons = {};
let currentFmPath = '/';
let editorPath = '';
const history = {};  // per-term command history
const logState = {
  netschoolbot: { tail: 500, connected: false, fitted: false },
  nginx: { tail: 500, connected: false, fitted: false }
};

// ── Утилиты ─────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => {
    const names = ['netschoolbot','nginx','custom','filemgr'];
    t.classList.toggle('active', names[i] === name);
  });
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  if (terms[name]) { ensureFit(name); terms[name].focus(); }
  if (name === 'filemgr') fmRefresh();
  if (name === 'custom' && !terms.custom) { initTerm('custom'); connectCustom(); }
  // Save active tab to localStorage
  try {
    localStorage.setItem('webterm_active_tab', name);
  } catch(e) {}
}

function ensureFit(id) {
  const fit = fitAddons[id];
  if (!fit) return;
  requestAnimationFrame(() => {
    fit.fit();
  });
}

function bindFitObserver(id) {
  const el = document.getElementById('term-' + id);
  if (!el || el._fitObserverBound) return;
  el._fitObserverBound = true;
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => ensureFit(id));
    ro.observe(el);
  }
}

function mkTerm(id) {
  if (typeof Terminal === 'undefined') {
    showNotice('Не удалось загрузить xterm.js. Проверьте доступ к /static_web/xterm.min.js');
    return null;
  }
  if (terms[id]) return;
  const t = new Terminal({
    theme: { background:'#0d1117', foreground:'#e6edf3', cursor:'#e6edf3',
             selectionBackground:'rgba(56,139,253,.35)' },
    fontFamily: "'Cascadia Code','Fira Code',monospace",
    fontSize: 13, lineHeight: 1.4,
    cursorBlink: true, scrollback: 20000,
    convertEol: true,
    letterSpacing: 0,
  });
  const fit = new FitAddon.FitAddon();
  t.loadAddon(fit);
  t.open(document.getElementById('term-' + id));
  ensureFit(id);
  bindFitObserver(id);
  terms[id] = t;
  fitAddons[id] = fit;
  window.addEventListener('resize', () => fit.fit());
  return t;
}

function clearTerm(id) {
  if (terms[id]) terms[id].clear();
}

// ── Log terminals (netschoolbot / nginx) ───────────────────────
function connectLog(service, reload = false) {
  if (!socket) { showNotice('Socket.IO недоступен. Логи не будут подключены.'); return; }
  mkTerm(service);
  if (reload && terms[service]) terms[service].clear();
  socket.emit('log_subscribe', { service, tail: logState[service]?.tail || 500 });
  if (logState[service]) logState[service].connected = true;
  ensureFit(service);
}

function onCmdKey(e, service) {
  if (e.key === 'Enter') {
    e.preventDefault();
    runCommand(service);
  }
}

function runCommand(service) {
  if (!socket) { showNotice('Socket.IO недоступен. Команда не отправлена.'); return; }
  const input = document.getElementById('cmd-' + service);
  if (!input) return;
  const cmd = input.value.trim();
  if (!cmd) return;
  socket.emit('log_command', { service, cmd });
  input.value = '';
}

function onScriptInputKey(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    sendScriptInput();
  }
}

function sendScriptInput() {
  if (!socket) { showNotice('Socket.IO недоступен. Ввод не отправлен.'); return; }
  const input = document.getElementById('in-netschoolbot');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  socket.emit('script_input', { service: 'netschoolbot', text });
  input.value = '';
}

async function serviceControl(service, action) {
  const actions = {
    'start': '⏯ Запускаю сервис...',
    'stop': '⏸ Останавливаю сервис...',
    'restart': '🔄 Перезапускаю сервис...',
    'kill': '💀 Убиваю процесс...'
  };
  
  const msg = actions[action] || 'Выполняю действие...';
  showNotice(msg);
  
  try {
    const r = await fetch(apiUrl('/service/control'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service, action })
    });
    const d = await r.json();
    
    if (d.error) {
      showNotice('❌ Ошибка: ' + d.error);
      setTimeout(() => { notice.style.display = 'none'; }, 5000);
    } else {
      showNotice('✅ ' + d.message);
      setTimeout(() => { notice.style.display = 'none'; }, 3000);
      // Reconnect log to see new output
      if (action !== 'stop') {
        setTimeout(() => connectLog(service), 500);
      }
    }
  } catch(e) {
    showNotice('❌ Ошибка запроса: ' + e);
    setTimeout(() => { notice.style.display = 'none'; }, 5000);
  }
}

socket.on('log_output', (data) => {
  const t = terms[data.service];
  if (t) {
    t.write(data.data);
    if (logState[data.service] && !logState[data.service].fitted) {
      logState[data.service].fitted = true;
      ensureFit(data.service);
    }
  }
});

function enableLogScrollLoad(service) {
  const t = terms[service];
  if (!t || t._logScrollBound) return;
  t._logScrollBound = true;
  t.onScroll(() => {
    const atTop = t.buffer.active.viewportY === 0;
    if (!atTop) return;
    const state = logState[service];
    if (!state || state.loading) return;
    state.loading = true;
    state.tail = Math.min(state.tail + 500, 5000);
    connectLog(service, true);
    setTimeout(() => { state.loading = false; }, 500);
  });
}

// Автоподключение при старте
window.addEventListener('load', () => {
  initHeaderActions();
  mkTerm('netschoolbot');
  mkTerm('nginx');
  enableLogScrollLoad('netschoolbot');
  enableLogScrollLoad('nginx');
  setTimeout(() => {
    ensureFit('netschoolbot');
    ensureFit('nginx');
    ensureFit('custom');
  }, 120);
});

function openPwdModal() {
  document.getElementById('pwd-error').style.display = 'none';
  document.getElementById('pwd-current').value = '';
  document.getElementById('pwd-new').value = '';
  document.getElementById('pwd-new2').value = '';
  document.getElementById('pwd-modal').classList.add('open');
}

function closePwdModal() {
  document.getElementById('pwd-modal').classList.remove('open');
}

async function changePassword() {
  const cur = document.getElementById('pwd-current').value;
  const nw = document.getElementById('pwd-new').value;
  const nw2 = document.getElementById('pwd-new2').value;
  const err = document.getElementById('pwd-error');
  err.style.display = 'none';
  if (!nw || nw.length < 8) {
    err.textContent = 'Новый пароль должен быть минимум 8 символов.';
    err.style.display = 'block';
    return;
  }
  if (nw !== nw2) {
    err.textContent = 'Пароли не совпадают.';
    err.style.display = 'block';
    return;
  }
  const r = await fetch(apiUrl('/auth/change_password'), {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ current: cur, new_password: nw })
  });
  const d = await r.json();
  if (d.error) {
    err.textContent = d.error;
    err.style.display = 'block';
    return;
  }
  closePwdModal();
  alert('Пароль изменен');
}

// ── Custom terminal (PTY) ────────────────────────────────────
function initTerm(id) { mkTerm(id); }

function connectCustom() {
  if (!socket) { showNotice('Socket.IO недоступен. Терминал не подключится.'); return; }
  socket.emit('pty_create');
}

function reconnectCustom() {
  if (!socket) { showNotice('Socket.IO недоступен. Терминал не подключится.'); return; }
  socket.emit('pty_kill');
  setTimeout(() => {
    clearTerm('custom');
    connectCustom();
  }, 300);
}

socket.on('pty_created', () => {
  if (terms.custom) {
    const fit = fitAddons.custom;
    const cols = terms.custom.cols;
    const rows = terms.custom.rows;
    socket.emit('pty_resize', { cols, rows });
    fitAddons.custom?.fit();
    terms.custom.focus();
    // Send input
    terms.custom.onData(data => socket.emit('pty_input', { data }));
    // Resize
    terms.custom.onResize(({ cols, rows }) => socket.emit('pty_resize', { cols, rows }));
  }
});

socket.on('pty_output', (data) => {
  if (terms.custom) terms.custom.write(data.data);
});

socket.on('pty_closed', () => {
  if (terms.custom) {
    terms.custom.write('\\r\\n\\x1b[33m[Сессия завершена. Нажмите «Новая сессия» для переподключения.]\\x1b[0m\\r\\n');
  }
});

// ── Файловый менеджер ─────────────────────────────────────
async function fmNav(path) {
  const base = currentFmPath;
  let target;
  if (path === '..') {
    target = base === '/' ? '/' : base.replace(/\\/[^/]+\\/?$/, '') || '/';
  } else if (path.startsWith('/')) {
    target = path;
  } else {
    target = (base.endsWith('/') ? base : base + '/') + path;
  }
  await fmLoad(target);
}

async function fmRefresh() {
  await fmLoad(currentFmPath);
}

async function fmGo(path) {
  await fmLoad(path);
}

async function fmLoad(path) {
  try {
    const r = await fetch(apiUrl('/fm/list'), {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ path })
    });
    const data = await r.json();
    if (data.error) { alert(data.error); return; }
    currentFmPath = data.path;
    document.getElementById('fm-path').textContent = data.path;
    renderFmList(data.entries);
  } catch(e) { alert('Ошибка: ' + e); }
}

function fmSizeHuman(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
  return (b/1024/1024).toFixed(1) + ' MB';
}

function renderFmList(entries) {
  const tb = document.getElementById('fm-tbody');
  tb.innerHTML = '';
  for (const e of entries) {
    const tr = document.createElement('tr');
    const icon = e.is_dir ? '📁' : '📄';
    const size = e.is_dir ? '—' : fmSizeHuman(e.size);
    const mtime = e.mtime ? new Date(e.mtime * 1000).toLocaleString('ru') : '—';
    const namCell = `<span class="icon">${icon}</span><span class="entry-name"
      onclick="${e.is_dir ? `fmNav('${escHtml(e.name)}')`
        : `editFile('${escHtml(currentFmPath + '/' + e.name).replace(/\\/\\//g,'/')}')`}"
      >${escHtml(e.name)}</span>`;
    const actCell = `<div class="file-actions">
      ${!e.is_dir ? `<button class="fa-btn" onclick="downloadFile('${escHtml(currentFmPath + '/' + e.name).replace(/\\/\\//g,'/')}')">⬇</button>` : ''}
      <button class="fa-btn" onclick="renameEntry('${escHtml(e.name)}')">✏</button>
      ${e.is_dir
        ? `<button class="fa-btn" onclick="archiveEntry('${escHtml(e.name)}')">🗜</button>`
        : (e.name.endsWith('.tar.gz') || e.name.endsWith('.zip') || e.name.endsWith('.tar'))
          ? `<button class="fa-btn" onclick="extractEntry('${escHtml(e.name)}')">📂</button>` : ''}
      <button class="fa-btn" style="color:var(--red)" onclick="deleteEntry('${escHtml(e.name)}')">🗑</button>
    </div>`;
    tr.innerHTML = `<td>${namCell}</td><td class="hide-on-tiny">${size}</td><td class="hide-on-tiny">${mtime}</td><td>${actCell}</td>`;
    tb.appendChild(tr);
  }
}

function escHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

// Загрузка файла
function uploadFile() { document.getElementById('file-upload-input').click(); }
async function doUpload(input) {
  const files = input.files;
  if (!files.length) return;
  const fd = new FormData();
  fd.append('path', currentFmPath);
  for (const f of files) fd.append('files', f);
  try {
    const r = await fetch(apiUrl('/fm/upload'), { method: 'POST', body: fd });
    const d = await r.json();
    if (d.error) alert(d.error);
    else { fmRefresh(); alert('Загружено: ' + d.uploaded.join(', ')); }
  } catch(e) { alert('Ошибка загрузки: ' + e); }
  input.value = '';
}

// Скачивание
function downloadFile(fullPath) {
  window.open(apiUrl('/fm/download?path=') + encodeURIComponent(fullPath));
}

// Удаление
async function deleteEntry(name) {
  if (!confirm('Удалить «' + name + '»?')) return;
  const full = (currentFmPath.endsWith('/') ? currentFmPath : currentFmPath + '/') + name;
  const r = await fetch(apiUrl('/fm/delete'), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path: full })
  });
  const d = await r.json();
  if (d.error) alert(d.error); else fmRefresh();
}

// Переименование
async function renameEntry(name) {
  const newName = prompt('Новое имя:', name);
  if (!newName || newName === name) return;
  const base = currentFmPath.endsWith('/') ? currentFmPath : currentFmPath + '/';
  const r = await fetch(apiUrl('/fm/rename'), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ src: base + name, dst: base + newName })
  });
  const d = await r.json();
  if (d.error) alert(d.error); else fmRefresh();
}

// Архивирование
async function archiveEntry(name) {
  const base = currentFmPath.endsWith('/') ? currentFmPath : currentFmPath + '/';
  const r = await fetch(apiUrl('/fm/archive'), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path: base + name })
  });
  const d = await r.json();
  if (d.error) alert(d.error); else { fmRefresh(); alert('Архив создан: ' + d.archive); }
}

// Разархивирование
async function extractEntry(name) {
  const base = currentFmPath.endsWith('/') ? currentFmPath : currentFmPath + '/';
  const r = await fetch(apiUrl('/fm/extract'), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path: base + name, dest: currentFmPath })
  });
  const d = await r.json();
  if (d.error) alert(d.error); else { fmRefresh(); alert('Извлечено в: ' + d.dest); }
}

// Новый файл
async function newFile() {
  const name = prompt('Имя нового файла:');
  if (!name) return;
  const full = (currentFmPath.endsWith('/') ? currentFmPath : currentFmPath + '/') + name;
  const r = await fetch(apiUrl('/fm/write'), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path: full, content: '' })
  });
  const d = await r.json();
  if (d.error) alert(d.error); else { fmRefresh(); editFile(full); }
}

// Новая папка
async function newFolder() {
  const name = prompt('Имя папки:');
  if (!name) return;
  const full = (currentFmPath.endsWith('/') ? currentFmPath : currentFmPath + '/') + name;
  const r = await fetch(apiUrl('/fm/mkdir'), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path: full })
  });
  const d = await r.json();
  if (d.error) alert(d.error); else fmRefresh();
}

// Редактор файла
async function editFile(fullPath) {
  try {
    const r = await fetch(apiUrl('/fm/read'), {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ path: fullPath })
    });
    const d = await r.json();
    if (d.error) { alert(d.error); return; }
    editorPath = fullPath;
    document.getElementById('editor-title').textContent = '✏ ' + fullPath;
    document.getElementById('editor-content').value = d.content;
    document.getElementById('editor-modal').classList.add('open');
  } catch(e) { alert('Ошибка чтения: ' + e); }
}

function closeEditor() {
  document.getElementById('editor-modal').classList.remove('open');
}

async function saveFile() {
  const content = document.getElementById('editor-content').value;
  const r = await fetch(apiUrl('/fm/write'), {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path: editorPath, content })
  });
  const d = await r.json();
  if (d.error) alert(d.error); else closeEditor();
}

// Закрыть редактор по клику на фон
document.getElementById('editor-modal').addEventListener('click', function(e) {
  if (e.target === this) closeEditor();
});
// Tab в редакторе
document.getElementById('editor-content').addEventListener('keydown', function(e) {
  if (e.key === 'Tab') {
    e.preventDefault();
    const s = this.selectionStart, en = this.selectionEnd;
    this.value = this.value.substring(0,s) + '    ' + this.value.substring(en);
    this.selectionStart = this.selectionEnd = s + 4;
  }
});
</script>
</body>
</html>"""

NETSCHOOL_MINIAPP_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="theme-color" content="#4a76a8">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="NetSchool">
<link rel="apple-touch-icon" href="{{ icon_url }}">
<link rel="manifest" href="{{ manifest_url }}">
<title>NetSchool</title>
<script>
(function(){
  const syncEnabled={{ (data.theme_sync if data else True)|tojson }}!==false;
  const serverTheme={{ (data.theme if data else 'light')|tojson }};
  const serverThemeSaved={{ (data.theme_saved if data else False)|tojson }}===true;
  const serverThemeUpdatedAt=Date.parse({{ (data.theme_updated_at if data else '')|tojson }})||0;
  const serverAccent={{ (data.accent_color if data else '')|tojson }};
  const serverAccentSaved={{ (data.accent_saved if data else False)|tojson }}===true;
  const serverAccentUpdatedAt=Date.parse({{ (data.accent_updated_at if data else '')|tojson }})||0;
  let initialTheme=serverTheme||'light';
  let initialAccent=serverAccent||'';
  try{
    const localTheme=localStorage.getItem('ns-theme')||'';
    const localThemeUpdatedAt=Number(localStorage.getItem('ns-theme-updated-at')||0)||0;
    const localAccent=localStorage.getItem('ns-accent')||'';
    const localAccentUpdatedAt=Number(localStorage.getItem('ns-accent-updated-at')||0)||0;
    if(syncEnabled){
      if(localTheme&&localThemeUpdatedAt>serverThemeUpdatedAt)initialTheme=localTheme;
      else if(!serverThemeSaved&&localTheme)initialTheme=localTheme;
      if(localAccentUpdatedAt>serverAccentUpdatedAt)initialAccent=localAccent;
      else if(!serverAccentSaved&&localAccent)initialAccent=localAccent;
    }else{
      if(localTheme)initialTheme=localTheme;
      if(localAccent)initialAccent=localAccent;
    }
  }catch(e){}
  if(initialTheme==='dark')document.documentElement.setAttribute('data-theme','dark');
  const meta=document.querySelector('meta[name="theme-color"]');
  const validAccent=/^#[0-9a-fA-F]{6}$/.test(initialAccent);
  const lightenHex=(hex,amt)=>{
    let r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
    r=Math.min(255,Math.round(r+(255-r)*amt));g=Math.min(255,Math.round(g+(255-g)*amt));b=Math.min(255,Math.round(b+(255-b)*amt));
    return '#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');
  };
  const darkenHex=(hex,amt)=>{
    let r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
    r=Math.max(0,Math.round(r*(1-amt)));g=Math.max(0,Math.round(g*(1-amt)));b=Math.max(0,Math.round(b*(1-amt)));
    return '#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');
  };
  const pickContrast=(hex)=>{
    const r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
    const yiq=(r*299+g*587+b*114)/1000;
    return yiq>=186?'#1f2c3a':'#ffffff';
  };
  if(validAccent){
    document.documentElement.style.setProperty('--accent',initialAccent);
    document.documentElement.style.setProperty('--primary',initialAccent);
    document.documentElement.style.setProperty('--primary-contrast',pickContrast(initialAccent));
    const topbar=initialTheme==='dark'?darkenHex(initialAccent,.35):initialAccent;
    const topbarGrad=initialTheme==='dark'?darkenHex(initialAccent,.2):lightenHex(initialAccent,.15);
    document.documentElement.style.setProperty('--topbar',topbar);
    document.documentElement.style.setProperty('--topbar-grad',topbarGrad);
    if(meta)meta.setAttribute('content',topbar);
  }else if(meta){
    document.documentElement.style.removeProperty('--primary-contrast');
    meta.setAttribute('content',initialTheme==='dark'?'#1e3a5f':'#4a76a8');
  }
})();
</script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --primary:#4a76a8;--primary-dark:#3d6590;--primary-light:#e8f0fe;
  --bg:#f0f2f5;--card:#fff;--text:#222;--text2:#656565;--border:#e0e0e0;
  --green:#4caf50;--red:#e53935;--amber:#fb8c00;
  --nav-bg:#fff;--topbar:#4a76a8;--topbar-grad:#5b8dd0;
  --app-height:100dvh;--topbar-h:calc(48px + env(safe-area-inset-top));--bottom-nav-h:56px;--bottom-nav-safe:env(safe-area-inset-bottom);--bottom-nav-total-h:calc(var(--bottom-nav-h) + var(--bottom-nav-safe));--viewport-bottom-offset:0px;--week-nav-h:46px;
  --accent:var(--primary);
}
[data-theme=dark]{
  --primary:#6b9fd4;--primary-dark:#4a76a8;--primary-light:#1e3a5f;
  --bg:#121212;--card:#1e1e1e;--text:#e0e0e0;--text2:#aaa;--border:#333;
  --green:#66bb6a;--red:#ef5350;--amber:#ffa726;
  --nav-bg:#1a1a1a;--topbar:#1e3a5f;--topbar-grad:#2a5080;
}
html{height:100%;background:var(--topbar);overflow:hidden}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);height:var(--app-height);min-height:var(--app-height);padding-bottom:0;-webkit-tap-highlight-color:transparent;touch-action:manipulation;overscroll-behavior:none;overflow:hidden;position:relative}
body::before{content:'';position:fixed;inset:0 0 auto 0;height:calc(68px + env(safe-area-inset-top));background:linear-gradient(180deg,var(--topbar-grad) 0%,var(--topbar) 100%);pointer-events:none;z-index:-1;transition:background .3s ease}
a{color:var(--primary);text-decoration:none}

.topbar{position:absolute;top:0;left:0;right:0;z-index:30;display:flex;align-items:flex-end;padding:env(safe-area-inset-top) 16px 10px;background:linear-gradient(180deg,var(--topbar-grad) 0%,var(--topbar) 100%);color:#fff;min-height:var(--topbar-h);box-shadow:0 1px 0 rgba(0,0,0,.06);transition:background .3s ease}
.topbar-title{flex:1;font-size:17px;font-weight:600;text-align:center}
.topbar-title.is-clickable{display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;user-select:none}
.topbar-title .topbar-caret{font-size:12px;opacity:.9}

.refresh-indicator{position:fixed;top:calc(env(safe-area-inset-top) + 8px);left:50%;transform:translateX(-50%) translateY(-22px);z-index:35;padding:8px 14px;border-radius:999px;background:rgba(255,255,255,.92);color:var(--primary-dark);font-size:12px;font-weight:700;box-shadow:0 10px 28px rgba(28,53,94,.16);opacity:0;pointer-events:none;transition:transform .2s ease,opacity .2s ease}
.refresh-indicator.show{opacity:1;transform:translateX(-50%) translateY(0)}
.refresh-indicator.loading{padding:6px 12px;font-size:11px;font-weight:600;opacity:.92;background:color-mix(in srgb, var(--card) 92%, transparent);color:var(--text2)}
.refresh-indicator.loading::before{content:'';display:inline-block;width:10px;height:10px;margin-right:8px;border-radius:50%;border:2px solid color-mix(in srgb, var(--primary) 20%, transparent);border-top-color:var(--primary);animation:spin .7s linear infinite;vertical-align:-1px}

.panel{display:none;position:absolute;left:0;right:0;top:var(--topbar-h);bottom:calc(var(--bottom-nav-total-h) + var(--viewport-bottom-offset));overflow-y:auto;overflow-x:hidden;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;padding-top:0;padding-bottom:0;background:var(--bg);}
.panel.active{display:block;animation:panelIn .28s cubic-bezier(.4,0,.2,1) forwards;min-height:0}
@keyframes panelIn{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}

/* Week strip */
.week-nav{display:flex;align-items:center;justify-content:space-between;padding:6px 16px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5;min-height:var(--week-nav-h)}
.week-nav button{background:0;border:0;color:var(--primary);font-size:22px;padding:4px 12px;cursor:pointer;border-radius:8px;line-height:1}
.week-nav button:active{background:var(--primary-light)}
.week-label{font-size:14px;font-weight:600;cursor:pointer}
.day-strip{display:flex;justify-content:center;gap:2px;padding:4px 8px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:var(--week-nav-h);z-index:4}
.day-chip{display:flex;flex-direction:column;align-items:center;justify-content:center;width:46px;min-height:52px;padding:6px 2px 8px;border-radius:12px;font-size:12px;line-height:1.1;cursor:pointer;border:0;background:0;color:var(--text2);transition:background .2s ease,color .2s ease,transform .15s ease}
.day-chip:active{transform:scale(.93)}
.day-chip .dn{font-size:16px;font-weight:700;margin-top:3px;line-height:1}
.day-chip.active{background:var(--green);color:#fff}
.day-chip.today:not(.active){color:var(--green);font-weight:700}


/* Calendar */
.cal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:60;display:none;align-items:center;justify-content:center}
.cal-overlay.open{display:flex;animation:overlayIn .2s ease forwards}
.cal-box{background:var(--card);border-radius:16px;width:340px;max-width:92vw;max-height:min(520px,82vh);overflow:hidden;display:flex;flex-direction:column;animation:calPop .28s cubic-bezier(.32,.72,.32,1) forwards}
@keyframes calPop{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:scale(1)}}
.cal-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border)}
.cal-head button{background:0;border:0;font-size:20px;color:var(--primary);cursor:pointer;padding:4px 8px;appearance:none;-webkit-appearance:none}
.cal-month{font-weight:600;font-size:15px}
.cal-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));grid-auto-rows:42px;gap:4px;padding:10px 12px 14px;align-items:center;overflow:hidden}
.cal-dh{display:flex;align-items:center;justify-content:center;text-align:center;font-size:12px;color:var(--text2);padding:0;font-weight:700;min-height:28px}
.cal-d{display:flex;align-items:center;justify-content:center;text-align:center;min-height:42px;padding:0;font-size:14px;border-radius:10px;cursor:pointer;border:0;background:0;color:var(--text);appearance:none;-webkit-appearance:none;line-height:1;font:inherit}
.cal-d:active{background:var(--primary-light)}
.cal-d.today{position:relative;font-weight:700}
.cal-d.today::after{content:'';position:absolute;bottom:2px;left:50%;transform:translateX(-50%);width:5px;height:5px;border-radius:50%;background:var(--green)}
.cal-d.sel{background:var(--green);color:#fff;font-weight:700}
.cal-d.sel::after{display:none}
.cal-d.empty{visibility:hidden;pointer-events:none}


/* Lesson card */
.lesson-list{padding:0 16px 8px;background:var(--bg)}
.lesson{display:flex;gap:12px;padding:14px 0;border-bottom:1px solid var(--border);animation:riseIn .3s cubic-bezier(.4,0,.2,1) backwards}
.lesson:nth-child(1){animation-delay:0s}.lesson:nth-child(2){animation-delay:.03s}.lesson:nth-child(3){animation-delay:.06s}.lesson:nth-child(4){animation-delay:.09s}.lesson:nth-child(5){animation-delay:.12s}.lesson:nth-child(6){animation-delay:.15s}.lesson:nth-child(7){animation-delay:.18s}.lesson:nth-child(8){animation-delay:.21s}
.lesson:last-child{border-bottom:0}
.lesson.lesson-clickable{cursor:pointer}
.lesson.lesson-clickable:active{background:color-mix(in srgb,var(--primary-light) 42%, transparent)}
.lesson-num{width:30px;height:30px;border-radius:50%;background:var(--primary-light);color:var(--primary);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;flex-shrink:0;margin-top:2px}
.lesson-body{flex:1;min-width:0;display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.lesson-main{flex:1;min-width:0}
.lesson-subj{font-weight:600;font-size:15px;line-height:1.25}
.lesson-time{font-size:12px;color:var(--text2);margin-top:3px}
.lesson-right{display:flex;flex-direction:column;align-items:flex-end;gap:8px;min-width:76px}
.lesson-hw{margin-top:6px;padding:7px 10px;background:var(--primary-light);border-radius:8px;font-size:13px;line-height:1.4}
.lesson-hw-title{font-weight:600;font-size:12px;color:var(--primary-dark);margin-bottom:3px}
.lesson-marks{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}
.lesson-mark-wrap{display:flex;flex-direction:column;align-items:center;gap:2px}
.lesson-mark-btn{border:0;background:transparent;padding:0;cursor:pointer}
.lesson-mark-btn:active{transform:scale(.92)}
.mark{display:inline-flex;align-items:center;justify-content:center;min-width:28px;height:28px;padding:0 6px;border-radius:8px;font-weight:700;font-size:14px}
.mark-weight{font-size:10px;line-height:1;color:var(--text2);opacity:.82;font-weight:700}
.mark-5{background:#c8e6c9;color:#2e7d32}
.mark-4{background:#bbdefb;color:#1565c0}
.mark-3{background:#fff9c4;color:#f57f17}
.mark-2{background:#ffcdd2;color:#c62828}
@keyframes riseIn{from{opacity:0;transform:translateY(12px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
.diary-swipe-left{animation:swipeLeft .26s ease}
.diary-swipe-right{animation:swipeRight .26s ease}
@keyframes swipeLeft{from{opacity:.55;transform:translateX(18px)}to{opacity:1;transform:translateX(0)}}
@keyframes swipeRight{from{opacity:.55;transform:translateX(-18px)}to{opacity:1;transform:translateX(0)}}

/* Grades table */
.grades-wrap{padding:0 0 4px}
.grades-toolbar{display:flex;gap:8px;flex-wrap:wrap;padding:10px 12px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:4}
.grade-filter-chip{padding:8px 12px;border:1px solid var(--border);border-radius:999px;background:var(--bg);color:var(--text2);font:inherit;font-size:12px;font-weight:700;cursor:pointer}
.grade-filter-chip.active{background:var(--primary);border-color:var(--primary);color:var(--primary-contrast,#fff)}
.grades-table{width:100%;border-collapse:collapse;background:var(--card)}
.grades-table th,.grades-table td{padding:10px 8px;text-align:center;border-bottom:1px solid var(--border);font-size:13px}
.grades-table th{background:var(--primary-light);color:var(--primary-dark);font-weight:600;position:sticky;top:48px;z-index:2}
.grades-table th:first-child,.grades-table td:first-child{text-align:left;padding-left:14px;min-width:110px;max-width:180px;font-weight:500;white-space:normal;word-break:break-word}
.grades-table td:first-child{font-weight:600;font-size:13px}
.grades-table td.q-cell{cursor:pointer}
.grades-table td.q-cell:active{background:var(--primary-light)}
.grade-val{font-weight:700;color:var(--primary)}
.grade-final{font-weight:700;font-size:14px}
.grade-final.g5{color:#2e7d32}.grade-final.g4{color:#1565c0}.grade-final.g3{color:#f57f17}.grade-final.g2{color:#c62828}

/* Calculator */
.calc-wrap{padding:16px}
.calc-card{background:linear-gradient(180deg,color-mix(in srgb, var(--card) 86%, var(--primary-light) 14%) 0%,var(--card) 100%);border:1px solid var(--border);border-radius:18px;padding:18px;margin-bottom:12px;box-shadow:0 10px 28px rgba(20,35,60,.12)}
.calc-title{font-size:16px;font-weight:800;margin-bottom:12px;color:var(--text)}
.calc-select,.calc-input{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:12px;background:var(--card);color:var(--text);font:inherit}
.calc-quarter-row{display:flex;gap:10px;align-items:center;margin-top:14px}
.calc-quarter-card{border:1px solid var(--border);border-radius:16px;background:var(--bg);padding:14px;margin-top:14px}
.calc-quarter-title{font-size:14px;font-weight:800;color:var(--text);margin-bottom:12px}
.calc-grade-list{display:flex;flex-direction:column;gap:10px}
.calc-grade-row{display:grid;grid-template-columns:minmax(0,1fr) 88px 38px 38px 38px;gap:8px;align-items:center}
.calc-grade-label{font-size:14px;font-weight:800;color:var(--text);text-align:right;padding-right:4px}
.calc-grade-number{font-size:16px;color:var(--green)}
.calc-mini-btn{width:38px;height:38px;border:1px solid var(--border);border-radius:10px;background:var(--card);color:var(--primary);font-size:20px;font-weight:700;cursor:pointer}
.calc-mini-btn.danger{color:#df6c6c}
.calc-mini-btn:active{background:var(--primary-light)}
.calc-row-note{font-size:11px;color:var(--text2);margin-top:3px;text-align:right}
.calc-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:20px}
.calc-summary-card{border-radius:16px;padding:16px;background:var(--bg);border:1px solid var(--border);text-align:center}
.calc-metric-value{font-size:40px;line-height:1;font-weight:900;color:var(--green);margin-top:8px}
.calc-metric-label{font-size:15px;font-weight:700;color:var(--text2)}
.calc-metric-sub{font-size:13px;color:var(--text2);margin-top:6px}
.calc-help{font-size:12px;color:var(--text2);margin-top:10px;line-height:1.45}

/* Homework */
.hw-nav{display:flex;align-items:center;justify-content:space-between;padding:6px 16px;background:var(--card);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:4;min-height:var(--week-nav-h)}
.hw-nav button{background:0;border:0;color:var(--primary);font-size:22px;padding:4px 12px;cursor:pointer;border-radius:8px;line-height:1}
.hw-nav button:active{background:var(--primary-light)}
.hw-nav-label{font-size:14px;font-weight:600;text-align:center}
.hw-list{padding:0 16px 8px;background:var(--bg)}
.hw-item{padding:12px 0;border-bottom:1px solid var(--border);cursor:pointer}
.hw-item:active{background:var(--primary-light)}
.hw-day-head{font-size:13px;font-weight:600;color:var(--primary);padding:12px 0 6px;border-bottom:1px solid var(--border)}
.hw-item{padding:12px 0;border-bottom:1px solid var(--border)}
.hw-item:last-child{border-bottom:0}
.hw-subj{font-weight:600;font-size:14px}
.hw-text{font-size:13px;color:var(--text2);margin-top:3px;line-height:1.4}
.hw-load-note{margin-top:8px;font-size:12px;color:var(--text2)}

/* Mail */
.mail-list{padding:0 0 8px;background:var(--bg)}
.mail-item{display:flex;gap:10px;padding:14px 16px;border-bottom:1px solid var(--border);cursor:pointer}
.mail-item:active{background:var(--primary-light)}
.mail-item.unread .mail-subj{font-weight:700}
.mail-dot{width:8px;height:8px;border-radius:50%;background:var(--primary);flex-shrink:0;margin-top:6px}
.mail-item:not(.unread) .mail-dot{visibility:hidden}
.mail-info{flex:1;min-width:0}
.mail-from{font-size:13px;font-weight:600}
.mail-subj{font-size:14px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mail-date{font-size:12px;color:var(--text2);margin-top:2px}
.mail-actions{display:flex;gap:10px;padding:14px 16px 4px}
.mail-more-btn{width:100%;padding:11px 14px;border:1px solid var(--border);border-radius:12px;background:var(--card);color:var(--primary);font:inherit;font-weight:700;cursor:pointer}

/* Overlay / sheet */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:50;display:none;align-items:flex-end;justify-content:center;opacity:0;transition:opacity .2s ease}
.overlay.open{display:flex;animation:overlayIn .25s ease forwards}
@keyframes overlayIn{from{opacity:0}to{opacity:1}}
.sheet{background:var(--card);border-radius:20px 20px 0 0;width:100%;max-width:760px;max-height:84vh;display:flex;flex-direction:column;transform:translateY(100%);animation:sheetUp .32s cubic-bezier(.32,.72,.32,1) forwards}
.overlay.open .sheet{transform:translateY(0)}
@keyframes sheetUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.sheet::before{content:'';width:44px;height:5px;border-radius:999px;background:color-mix(in srgb, var(--text2) 28%, transparent);align-self:center;margin-top:8px;flex-shrink:0}
.sheet-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border);flex-shrink:0}
.sheet-head h3{font-size:16px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-right:8px}
.sheet-close{background:0;border:0;font-size:24px;color:var(--text2);cursor:pointer;padding:4px 8px;line-height:1;flex-shrink:0}
.sheet-body{padding:16px;overflow-y:auto;flex:1;-webkit-overflow-scrolling:touch;padding-bottom:calc(16px + env(safe-area-inset-bottom))}

/* Attachment chip */
.att-chip{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border:1px solid var(--border);border-radius:10px;font-size:13px;color:var(--primary);background:var(--card);cursor:pointer;text-decoration:none}
.att-chip::before{content:'📎'}
.att-chip:active{background:var(--primary-light)}
.file-viewer-wrap{display:flex;flex-direction:column;gap:10px;min-height:0;height:100%}
.file-viewer-actions{display:flex;gap:8px;flex-wrap:wrap;flex-shrink:0}
.file-viewer-frame{width:100%;flex:1;min-height:0;border:1px solid var(--border);border-radius:16px;background:rgba(255,255,255,.72);overflow:hidden}
[data-theme="dark"] .file-viewer-frame{background:rgba(15,23,36,.82)}
.file-viewer-frame iframe,.file-viewer-frame img,.file-viewer-frame video,.file-viewer-frame audio{width:100%;height:100%;display:block;border:0}
.file-viewer-frame img{height:100%;object-fit:contain;background:#fff}
.file-viewer-frame video{background:#000}
.file-viewer-text{white-space:pre-wrap;line-height:1.6;font-size:14px;padding:16px;overflow:auto;user-select:text;-webkit-user-select:text}
.file-viewer-textarea{width:100%;height:100%;min-height:100%;padding:16px;border:0;background:transparent;color:var(--text);font:inherit;font-size:14px;line-height:1.6;resize:none;outline:0;white-space:pre-wrap;user-select:text;-webkit-user-select:text}
.file-viewer-empty{display:flex;align-items:center;justify-content:center;text-align:center;min-height:220px;padding:24px;color:var(--text2);font-size:14px}

/* Subject detail sheet */
.subj-mark-row{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)}
.subj-mark-row:last-child{border-bottom:0}
.subj-mark-info{flex:1;min-width:0}
.subj-mark-title{font-size:14px;font-weight:500}
.subj-mark-meta{font-size:12px;color:var(--text2);margin-top:2px}

/* Profile */
.profile-section{padding:16px 16px 4px}
.pwa-icon-preview{width:72px;height:72px;border-radius:20px;display:flex;align-items:center;justify-content:center;font-size:36px;color:#fff;box-shadow:0 10px 24px rgba(0,0,0,.14);flex-shrink:0}
.pwa-icon-preview img{width:100%;height:100%;display:block;object-fit:cover;border-radius:inherit}
.pwa-icon-row{display:flex;align-items:center;gap:14px}
.pwa-icon-controls{display:flex;flex-direction:column;gap:10px;flex:1;min-width:0}
.pwa-icon-actions{display:flex;gap:8px;flex-wrap:wrap}
.pwa-icon-current{display:flex;align-items:center;gap:12px;padding:10px 12px;border:1px solid var(--border);border-radius:14px;background:var(--bg)}
.pwa-icon-current-meta{display:flex;flex-direction:column;gap:2px;min-width:0}
.pwa-icon-current-title{font-size:13px;font-weight:700}
.pwa-icon-current-sub{font-size:12px;color:var(--text2);line-height:1.35}
.pwa-icon-customize{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pwa-icon-color{width:54px;min-width:54px;height:42px;border:1px solid var(--border);border-radius:12px;background:var(--card);padding:4px;flex:0 0 auto}
.pwa-icon-file{width:100%;padding:10px 12px;border:1px dashed var(--border);border-radius:12px;background:var(--bg);color:var(--text);font:inherit;font-size:12px}
.pwa-icon-hint{font-size:12px;color:var(--text2);line-height:1.45}
.profile-card{background:var(--card);border-radius:12px;padding:16px;margin-bottom:12px;border:1px solid var(--border);animation:cardIn .35s cubic-bezier(.4,0,.2,1) backwards}
.profile-card:nth-child(1){animation-delay:.02s}
.profile-card:nth-child(2){animation-delay:.06s}
.profile-card:nth-child(3){animation-delay:.10s}
.profile-card:nth-child(4){animation-delay:.14s}
.profile-card:nth-child(5){animation-delay:.18s}
.profile-card:nth-child(6){animation-delay:.22s}
.profile-card:nth-child(7){animation-delay:.26s}
.profile-card:nth-child(8){animation-delay:.30s}
.profile-card:nth-child(9){animation-delay:.34s}
@keyframes cardIn{from{opacity:0;transform:translateY(16px) scale(.97)}to{opacity:1;transform:translateY(0) scale(1)}}
.profile-name{font-size:18px;font-weight:700}
.profile-school{font-size:13px;color:var(--text2);margin-top:4px}
.setting-row{display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid var(--border)}
.setting-row:last-child{border-bottom:0}
.setting-info{flex:1;min-width:0}
.setting-label{font-size:14px;font-weight:500;display:block}
.setting-desc{font-size:12px;color:var(--text2);display:block;margin-top:1px}
.setting-value{font-size:13px;color:var(--text2)}
.feedback-form{display:flex;flex-direction:column;gap:12px}
.feedback-field{width:100%;padding:12px 14px;border:1px solid var(--border);border-radius:12px;background:var(--bg);color:var(--text);font:inherit}
.feedback-textarea{min-height:160px;resize:vertical;line-height:1.5}
.feedback-status{font-size:12px;line-height:1.45;color:var(--text2)}
.feedback-status.error{color:var(--red)}
.feedback-status.success{color:var(--green)}
.toggle{width:44px;height:24px;border-radius:12px;background:var(--border);position:relative;cursor:pointer;border:0;transition:background .25s cubic-bezier(.4,0,.2,1)}
.toggle.on{background:var(--green)}
.toggle::after{content:'';position:absolute;top:2px;left:2px;width:20px;height:20px;border-radius:50%;background:#fff;transition:transform .25s cubic-bezier(.4,0,.2,1),box-shadow .25s ease;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.toggle.on::after{transform:translateX(20px);box-shadow:0 2px 6px rgba(0,0,0,.25)}
.pwa-link-box{margin-top:12px;padding:12px;border:1px solid var(--border);border-radius:12px;background:var(--bg)}
.pwa-link-input{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--card);color:var(--text);font-size:12px}
.pwa-link-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.pwa-link-note{margin-top:8px;font-size:12px;color:var(--text2);line-height:1.45}

/* Bottom nav */
.bottom-nav{position:absolute;left:0;right:0;bottom:var(--viewport-bottom-offset);z-index:30;display:flex;align-items:stretch;background:var(--nav-bg);border-top:1px solid var(--border);padding:0 env(safe-area-inset-left) 0 env(safe-area-inset-right);height:var(--bottom-nav-total-h);min-height:var(--bottom-nav-total-h);}
.nav-item{position:relative;flex:1 1 0;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;padding:3px 0 calc(3px + var(--bottom-nav-safe));min-height:var(--bottom-nav-total-h);color:var(--text2);cursor:pointer;border:0;background:transparent;transition:color .2s ease,transform .15s ease;appearance:none;-webkit-appearance:none}
.nav-item:active{transform:scale(.92)}
.nav-item .ico{display:block;font-size:20px;line-height:20px;height:20px;flex:0 0 20px;transition:transform .2s ease}
.nav-item.active .ico{transform:scale(1.12)}
.nav-label{display:block;width:100%;font-size:10px;line-height:12px;min-height:12px;font-weight:600;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:0}
.nav-item.active{color:var(--primary);font-weight:700}
.nav-item.active .nav-label{font-weight:800}
.nav-badge{position:absolute;top:3px;right:16%;min-width:18px;height:18px;padding:0 5px;border-radius:999px;background:var(--red);color:#fff;font-size:10px;font-weight:800;display:none;align-items:center;justify-content:center;line-height:1}
.nav-badge.show{display:inline-flex}
.nav-badge.mail{background:#e35b48}
.nav-badge.grades{background:#2e9f57}
.nav-badge.homework{background:#f39b15}

.empty{padding:40px 16px;text-align:center;color:var(--text2);font-size:14px;min-height:42vh;display:flex;align-items:center;justify-content:center;flex-direction:column}
.loader{padding:40px 16px;text-align:center;color:var(--text2)}
.spin{display:inline-block;width:20px;height:20px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.error-page{padding:40px 20px;text-align:center}
.error-page h1{font-size:20px;margin-bottom:12px;color:var(--red)}
.retry-btn{display:inline-block;margin-top:14px;padding:10px 28px;border:0;border-radius:10px;background:var(--primary);color:var(--primary-contrast,#fff);font-size:14px;font-weight:600;cursor:pointer;transition:transform .15s ease,background .2s ease,color .2s ease,box-shadow .2s ease;box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--primary) 75%, #000 10%)}
.retry-btn:active{background:var(--primary-dark);transform:scale(.95)}

.lesson-hw-btn{display:inline-flex;align-items:center;gap:6px;margin-top:10px;padding:7px 12px;font-size:13px;color:var(--primary);cursor:pointer;font-weight:700;background:var(--primary-light);border-radius:12px}
.lesson-hw-btn.has-files::before{content:'📎';font-size:13px}
#diaryContent,#hwContent,#mailContent{padding-bottom:0}
#hwDetailOverlay .sheet{max-width:860px}
#fileViewerOverlay{align-items:stretch}
#fileViewerOverlay .sheet{max-width:none;max-height:none;height:100svh;border-radius:0}
#fileViewerOverlay .sheet::before{display:none}
#fileViewerOverlay .sheet-head{padding:calc(12px + env(safe-area-inset-top)) 14px 10px;align-items:flex-start}
#fileViewerOverlay .sheet-head h3{white-space:normal;overflow:visible;text-overflow:clip;line-height:1.3;padding-right:12px;word-break:break-word}
#fileViewerOverlay .sheet-body{padding:8px 8px calc(8px + env(safe-area-inset-bottom));display:flex;min-height:0}

@media (max-width:720px){
  .calc-grade-row{grid-template-columns:minmax(0,1fr) 76px 36px 36px 36px}
}

@media (max-width:430px){
  .nav-item .ico{font-size:18px;line-height:18px;height:18px;flex-basis:18px}
  .nav-label{font-size:9px;line-height:11px;min-height:11px}
  .nav-badge{right:10%;min-width:16px;height:16px;font-size:9px}
  .nav-item{justify-content:flex-end;gap:0;padding:3px 0 calc(6px + var(--bottom-nav-safe));min-height:var(--bottom-nav-total-h)}
  .pwa-icon-row{flex-direction:column;align-items:stretch}
  .pwa-icon-preview{width:64px;height:64px;font-size:32px}
  .pwa-icon-current{padding:10px}
  .pwa-icon-customize{align-items:center}
}

/* iPad — nudge nav items lower */
@media (min-width:431px) and (max-width:1024px){
  .nav-item{padding:6px 0 4px;min-height:50px}
  .nav-item .ico{font-size:22px;line-height:22px;height:22px;flex-basis:22px}
  .nav-label{font-size:11px}
}

/* Standalone PWA — tighter bottom nav, no huge gap */
@media (display-mode: standalone){
  :root{--bottom-nav-h:50px;--bottom-nav-safe:max(env(safe-area-inset-bottom), 6px)}
  .nav-item{padding:2px 0 calc(2px + var(--bottom-nav-safe))}
}

/* Color palette picker */
.palette-row{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.palette-label{font-size:13px;flex:1;min-width:0}
.palette-swatch{width:36px;height:36px;border-radius:10px;border:2px solid var(--border);cursor:pointer;padding:0;flex-shrink:0;transition:transform .15s ease,box-shadow .15s ease}
.palette-swatch:active{transform:scale(.9)}
.palette-reset{font-size:12px;color:var(--primary);cursor:pointer;background:color-mix(in srgb,var(--primary) 12%, transparent);border:1px solid color-mix(in srgb,var(--primary) 30%, var(--border));padding:6px 10px;border-radius:8px}
.palette-reset:active{background:color-mix(in srgb,var(--primary) 18%, transparent)}

/* Icon gallery */
.gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(68px,1fr));gap:10px;margin-top:10px}
.gallery-item{position:relative;width:100%;aspect-ratio:1;border-radius:16px;overflow:hidden;cursor:pointer;border:2px solid transparent;transition:transform .15s ease,border-color .2s ease;background:var(--bg)}
.gallery-item:active{transform:scale(.92)}
.gallery-item.selected{border-color:var(--primary)}
.gallery-item img{width:100%;height:100%;object-fit:cover;display:block}
.gallery-item-delete{position:absolute;top:6px;right:6px;width:24px;height:24px;border:0;border-radius:999px;background:rgba(0,0,0,.66);color:#fff;font-size:14px;line-height:24px;text-align:center;cursor:pointer}

/* Session code entry */
.code-input-row{display:flex;gap:8px;margin-top:10px}
.code-input{flex:1;padding:12px 14px;border:1px solid var(--border);border-radius:12px;background:var(--card);color:var(--text);font:inherit;font-size:16px;text-align:center;letter-spacing:4px}
</style>
</head>
<body>
{% if error %}
<div class="error-page"><h1>Нет доступа</h1><p>{{ error }}</p></div>
<script>
(function(){
  try{
    const token=localStorage.getItem('ns-miniapp-token')||'';
    if(token&&!location.search.includes('token='))location.replace('{{ page_url }}?token='+encodeURIComponent(token));
  }catch(e){}
})();
</script>
{% else %}
<div class="topbar"><div class="topbar-title" id="topTitle">Дневник</div></div>
<div class="refresh-indicator" id="refreshIndicator">Потяните вниз, чтобы обновить</div>

<div class="panel active" id="p-diary">
  <div class="week-nav">
    <button id="weekPrev">◀</button>
    <div class="week-label" id="weekLabel"></div>
    <button id="weekNext">▶</button>
  </div>
  <div class="day-strip" id="dayStrip"></div>
  <div id="diaryContent"><div class="loader"><span class="spin"></span> Загрузка…</div></div>
</div>
<div class="panel" id="p-grades"><div class="grades-wrap" id="gradesContent"><div class="loader"><span class="spin"></span> Загрузка…</div></div></div>
<div class="panel" id="p-calc"><div class="calc-wrap" id="calcContent"><div class="loader"><span class="spin"></span> Загрузка…</div></div></div>
<div class="panel" id="p-homework"><div class="hw-nav"><button id="hwPrev">◀</button><div class="hw-nav-label" id="hwDateLabel"></div><button id="hwNext">▶</button></div><div id="hwContent"><div class="loader"><span class="spin"></span> Загрузка…</div></div></div>
<div class="panel" id="p-mail"><div id="mailContent"><div class="loader"><span class="spin"></span> Загрузка…</div></div></div>
<div class="panel" id="p-profile"><div class="profile-section" id="profileContent"></div></div>

<div class="bottom-nav" id="bottomNav">
  <button class="nav-item active" data-tab="diary"><span class="ico">📒</span><span class="nav-label">Дневник</span></button>
  <button class="nav-item" data-tab="grades"><span class="nav-badge grades" id="badgeGrades"></span><span class="ico">📊</span><span class="nav-label">Оценки</span></button>
  <button class="nav-item" data-tab="homework"><span class="nav-badge homework" id="badgeHomework"></span><span class="ico">📝</span><span class="nav-label">ДЗ</span></button>
  <button class="nav-item" data-tab="mail"><span class="nav-badge mail" id="badgeMail"></span><span class="ico">✉️</span><span class="nav-label">Почта</span></button>
  <button class="nav-item" data-tab="calc"><span class="ico">🧮</span><span class="nav-label">Баллы</span></button>
  <button class="nav-item" data-tab="profile"><span class="ico">👤</span><span class="nav-label">Профиль</span></button>
</div>

<div class="overlay" id="subjectOverlay"><div class="sheet">
  <div class="sheet-head"><h3 id="sheetSubjTitle"></h3><button class="sheet-close" onclick="closeOv('subjectOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetSubjBody"></div>
</div></div>

<div class="overlay" id="lessonInfoOverlay"><div class="sheet">
  <div class="sheet-head"><h3 id="sheetLessonInfoTitle"></h3><button class="sheet-close" onclick="closeOv('lessonInfoOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetLessonInfoBody"></div>
</div></div>

<div class="overlay" id="mailOverlay"><div class="sheet">
  <div class="sheet-head"><h3 id="sheetMailTitle"></h3><button class="sheet-close" onclick="closeOv('mailOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetMailBody"></div>
</div></div>

<div class="overlay" id="installGuideOverlay"><div class="sheet">
  <div class="sheet-head"><h3>Установка приложения</h3><button class="sheet-close" onclick="closeOv('installGuideOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetInstallGuideBody"></div>
</div></div>

<div class="overlay" id="galleryOverlay"><div class="sheet">
  <div class="sheet-head"><h3>Галерея иконок</h3><button class="sheet-close" onclick="closeOv('galleryOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetGalleryBody"></div>
</div></div>

<div class="overlay" id="hwDetailOverlay"><div class="sheet">
  <div class="sheet-head"><h3 id="sheetHwTitle"></h3><button class="sheet-close" onclick="closeOv('hwDetailOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetHwBody"></div>
</div></div>


<div class="overlay" id="fileViewerOverlay"><div class="sheet">
  <div class="sheet-head"><h3 id="sheetFileTitle"></h3><button class="sheet-close" onclick="closeOv('fileViewerOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetFileBody"></div>
</div></div>

<div class="overlay" id="sessionRecoveryOverlay"><div class="sheet">
  <div class="sheet-head"><h3>Сессия истекла</h3><button class="sheet-close" onclick="closeOv('sessionRecoveryOverlay')">✕</button></div>
  <div class="sheet-body">
    <div style="font-size:14px;line-height:1.6;margin-bottom:14px">Сессия мини-приложения истекла. Получите код в Telegram и введите его ниже, чтобы продолжить без переустановки.</div>
    <button class="retry-btn" style="margin-top:0;padding:10px 20px;font-size:13px;width:100%" onclick="requestSessionCode(this)">Отправить код в Telegram</button>
    <div class="code-input-row"><input class="code-input" id="sessionCodeInput" maxlength="6" inputmode="numeric" placeholder="000000"><button class="retry-btn" style="margin-top:0;padding:10px 20px;font-size:13px" onclick="verifySessionCode(this)">Войти</button></div>
    <div class="feedback-status" id="sessionCodeStatus">Нажмите кнопку выше, код придёт в Telegram.</div>
  </div>
</div></div>


<div class="overlay" id="feedbackOverlay"><div class="sheet">
  <div class="sheet-head"><h3 id="sheetFeedbackTitle">Обратная связь</h3><button class="sheet-close" onclick="closeFeedbackOverlay()">✕</button></div>
  <div class="sheet-body">
    <div class="feedback-form">
      <input class="feedback-field" id="feedbackSubject" maxlength="140" placeholder="Коротко: что не так или что добавить">
      <textarea class="feedback-field feedback-textarea" id="feedbackMessage" maxlength="4000" placeholder="Опишите проблему или идею подробнее"></textarea>
      <div class="feedback-status" id="feedbackStatus">Сообщение уйдёт в Telegram-бот администратора вместе с техническими логами.</div>
      <div class="pwa-link-actions" style="margin-top:0">
        <button class="retry-btn" type="button" id="feedbackSubmitBtn" style="margin-top:0">Отправить</button>
        <button class="mail-more-btn" type="button" id="feedbackCancelBtn">Отмена</button>
      </div>
    </div>
  </div>
</div></div>


<div class="overlay" id="childSwitchOverlay"><div class="sheet">
  <div class="sheet-head"><h3>Выбор ребёнка</h3><button class="sheet-close" onclick="closeOv('childSwitchOverlay')">✕</button></div>
  <div class="sheet-body" id="sheetChildSwitchBody"></div>
</div></div>



<div class="cal-overlay" id="calOverlay"><div class="cal-box">
  <div class="cal-head"><button id="calPrev">◀</button><div class="cal-month" id="calMonth"></div><button id="calNext">▶</button></div>
  <div class="cal-grid" id="calGrid"></div>
</div></div>

<script src="https://telegram.org/js/telegram-web-app.js?57"></script>
<script>
function pad2(n){return n<10?'0'+n:''+n}
function isoDate(d){return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate())}
const NS_TOKEN_STORAGE_KEY='ns-miniapp-token';
const NS_THEME_TS_KEY='ns-theme-updated-at';
const NS_ACCENT_TS_KEY='ns-accent-updated-at';
const tgApp=window.Telegram&&window.Telegram.WebApp?window.Telegram.WebApp:null;
const S={dash:null,mail:null,totals:null,totalsNotice:'',totalsFallback:false,weekOffset:0,selectedDate:isoDate(new Date()),theme:localStorage.getItem('ns-theme')||'light',accentColor:localStorage.getItem('ns-accent')||'',currentTab:'diary',calMonth:null,calYear:null,miniappToken:'',calcSubject:'',calcQuarter:'q1',calcQuarterCounts:null,calcCountsLoadedFor:'',isLoading:false,isMailLoading:false,gradeFilters:{currentQuarter:false,changedOnly:false,newOnly:false},delta:{newGradeKeys:new Set(),changedSubjects:new Set(),newHomeworkKeys:new Set(),gradeCount:0,homeworkCount:0,unreadMailCount:0},activeHwKey:'',autoPushAttempted:false,feedbackKind:'bug',pendingPwaIconImageData:''};
const INITIAL_DASH={{ initial_dash|tojson }};
const INITIAL_MAIL={{ initial_mail|tojson }};
const HASH_TABS=['diary','grades','calc','homework','mail','profile'];
let hashTab=(location.hash||'').replace('#','');
if (tgApp && tgApp.initDataUnsafe && tgApp.initDataUnsafe.start_param) { hashTab = tgApp.initDataUnsafe.start_param; }
if(HASH_TABS.includes(hashTab))S.currentTab=hashTab;
function esc(v){return String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function linkifyText(v){return String(v??'' ).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:var(--primary);text-decoration:none;">$1</a>')}
function $(id){return document.getElementById(id)}
function html(id,v){const el=$(id);if(el)el.innerHTML=v}
function txt(id,v){const el=$(id);if(el)el.textContent=v??''}
function parseStoredTs(v){const n=Number(v);return Number.isFinite(n)&&n>0?n:0}
function setLocalThemeChoice(theme,stamp){try{localStorage.setItem('ns-theme',theme);localStorage.setItem(NS_THEME_TS_KEY,String(stamp||Date.now()))}catch(e){}}
function setLocalAccentChoice(accent,stamp){try{if(accent)localStorage.setItem('ns-accent',accent);else localStorage.removeItem('ns-accent');localStorage.setItem(NS_ACCENT_TS_KEY,String(stamp||Date.now()))}catch(e){}}
function initTelegramMiniApp(){
  if(!tgApp)return;
  try{if(typeof tgApp.ready==='function')tgApp.ready()}catch(e){}
  try{if(typeof tgApp.expand==='function')tgApp.expand()}catch(e){}
  try{if(typeof tgApp.disableVerticalSwipes==='function')tgApp.disableVerticalSwipes()}catch(e){}
  try{if(typeof tgApp.requestFullscreen==='function')tgApp.requestFullscreen()}catch(e){}
}
function hasEditableFocus(){
  const active=document.activeElement;
  if(!active||!(active instanceof HTMLElement))return false;
  if(active.isContentEditable)return true;
  return !!active.closest('input, textarea, select');
}
function updateViewportVars(){
  const root=document.documentElement;
  const activePanel=document.querySelector('.panel.active');
  const preservedScroll=activePanel?activePanel.scrollTop:0;
  const vv=window.visualViewport;
  const isTg=!!(window.Telegram&&window.Telegram.WebApp&&window.Telegram.WebApp.initData);
  const layoutHeight=Math.round(window.innerHeight||0);
  const vvHeight=vv&&vv.height?Math.round(vv.height):0;
  let height=0;
  if(isTg&&typeof tgApp!=='undefined'&&tgApp){
    const tgHeight=Math.round(tgApp.viewportStableHeight||tgApp.viewportHeight||0);
    const candidates=[tgHeight,vvHeight,layoutHeight].filter(v=>v>0);
    height=candidates.length?Math.min(...candidates):0;
  }else{
    height=vvHeight>0?vvHeight:layoutHeight;
  }
  if(height>0) root.style.setProperty('--app-height',height+'px');
  
  const keyboardLikelyOpen=!!(vv&&hasEditableFocus()&&layoutHeight-vvHeight>120);
  const viewportBottomOffset=keyboardLikelyOpen&&vv?Math.max(0,Math.round(layoutHeight-(vv.height+vv.offsetTop))):0;
  root.style.setProperty('--viewport-bottom-offset',viewportBottomOffset+'px');
  if(activePanel)requestAnimationFrame(()=>{activePanel.scrollTop=preservedScroll});
}
initTelegramMiniApp();
updateViewportVars();
window.addEventListener('resize',updateViewportVars,{passive:true});
if(window.visualViewport)window.visualViewport.addEventListener('resize',updateViewportVars,{passive:true});
document.addEventListener('focusin',updateViewportVars,{passive:true});
document.addEventListener('focusout',()=>setTimeout(updateViewportVars,30),{passive:true});
if(tgApp&&typeof tgApp.onEvent==='function')tgApp.onEvent('viewportChanged',updateViewportVars);
document.addEventListener('touchstart',initTelegramMiniApp,{passive:true,once:true});
document.addEventListener('touchstart',()=>{if(isStandalonePwa())maybeAutoEnablePush().catch?.(()=>{})},{passive:true,once:true});
window.addEventListener('pageshow',()=>{setTimeout(updateViewportVars,30);if(isStandalonePwa())setTimeout(()=>maybeAutoEnablePush(),120)});
window.addEventListener('focus',()=>setTimeout(updateViewportVars,30),{passive:true});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){setTimeout(updateViewportVars,30);if(isStandalonePwa())setTimeout(()=>maybeAutoEnablePush(),120)}});
function storeMiniappToken(token){
  const value=String(token||'').trim();
  if(!value)return;
  S.miniappToken=value;
  try{localStorage.setItem(NS_TOKEN_STORAGE_KEY,value)}catch(e){}
}
function getMiniappToken(){
  if(S.miniappToken)return S.miniappToken;
  try{const value=localStorage.getItem(NS_TOKEN_STORAGE_KEY)||'';if(value){S.miniappToken=value;return value}}catch(e){}
  return '';
}
function miniappHeaders(extra){
  const headers=Object.assign({},extra||{});
  const token=getMiniappToken();
  if(token)headers['X-Netschool-Miniapp-Token']=token;
  return headers;
}
function withMiniappToken(url){
  const token=getMiniappToken();
  if(!token)return url;
  try{
    const full=new URL(url,window.location.origin);
    if((full.pathname.startsWith('/mini/netschool')||full.pathname.startsWith('/api/mini/netschool'))&&!full.searchParams.get('token'))full.searchParams.set('token',token);
    return full.pathname+full.search+full.hash;
  }catch(e){return url}
}
const NS_API_TIMEOUT_MS=25000;
const NS_ERROR_HINTS={
  invalid_credentials:'Проверьте логин/пароль в боте и выполните переавторизацию.',
  session_expired:'Сессия истекла. Запросите код в Telegram и войдите снова.',
  netschool_unavailable:'Подождите 1-2 минуты и повторите попытку. Данные из кэша останутся доступны.',
  netschool_busy:'Сервер перегружен. Подождите 1-2 минуты и повторите запрос.',
  login_failed:'Попробуйте переавторизоваться через код из Telegram.',
};
function getErrorHintByCode(code){return NS_ERROR_HINTS[String(code||'')]||''}
function escWithBr(s){return esc(String(s||'')).replace(/\n/g,'<br>')}
function createApiError(status,data,defaultMsg){
  const d=data||{};
  const code=String(d.error_code||'');
  const hint=getErrorHintByCode(code);
  const base=String(d.error||defaultMsg||'Ошибка');
  const msg=hint?base+'\n'+hint:base;
  const err=new Error(msg);
  err.error_code=code;
  err.http_status=status;
  err.user_hint=hint;
  return err;
}
function buildErrorActionBlock(err,retryAction){
  const code=String((err&&err.error_code)||'');
  const retry=retryAction||'loadAll()';
  let actions='<button class="retry-btn" onclick="'+retry+'">Повторить</button>';
  if(code==='invalid_credentials'||code==='session_expired'||code==='login_failed'){
    actions+=' <button class="retry-btn" onclick="showSessionRecovery()">Переавторизоваться</button>';
  }
  return '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">'+actions+'</div>';
}
async function fetchWithTimeout(url,options={},timeoutMs=NS_API_TIMEOUT_MS){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{
    return await fetch(url,Object.assign({},options,{signal:controller.signal}));
  }catch(e){
    if(e&&e.name==='AbortError')throw new Error('Сервер долго отвечает. Попробуйте обновить позже.');
    throw e;
  }finally{clearTimeout(timer)}
}
async function api(p){const r=await fetchWithTimeout(withMiniappToken(p),{credentials:'same-origin',headers:miniappHeaders(),cache:'no-store'});if(!r.ok){const d=await r.json().catch(()=>({}));if(r.status===401&&(d.error_code==='session_expired'||!d.error_code)){showSessionRecovery()}throw createApiError(r.status,d,'Ошибка '+r.status)}return r.json()}
async function postApi(p,b){const r=await fetchWithTimeout(withMiniappToken(p),{method:'POST',credentials:'same-origin',headers:miniappHeaders({'Content-Type':'application/json'}),body:JSON.stringify(b),cache:'no-store'});if(!r.ok){const d=await r.json().catch(()=>({}));if(r.status===401&&(d.error_code==='session_expired'||!d.error_code)){showSessionRecovery()}throw createApiError(r.status,d,'Ошибка')}return r.json()}

/* Session recovery */
function showSessionRecovery(){
  const ov=$('sessionRecoveryOverlay');
  if(ov)ov.classList.add('open');
}
async function requestSessionCode(btn){
  if(btn)btn.disabled=true;
  const status=$('sessionCodeStatus');
  try{
    const token=getMiniappToken();
    await postApi('/api/mini/netschool/session/request-code',{token});
    if(status){status.textContent='Код отправлен в Telegram. Введите его ниже.';status.className='feedback-status success'}
  }catch(e){
    if(status){status.textContent=e.message||'Не удалось отправить код';status.className='feedback-status error'}
  }finally{if(btn)btn.disabled=false}
}
async function verifySessionCode(btn){
  const input=$('sessionCodeInput');
  if(!input)return;
  const code=input.value.trim();
  if(code.length!==6){alert('Введите 6-значный код');return}
  if(btn)btn.disabled=true;
  const status=$('sessionCodeStatus');
  try{
    const res=await fetch(withMiniappToken('/api/mini/netschool/session/verify-code'),{method:'POST',credentials:'same-origin',headers:miniappHeaders({'Content-Type':'application/json'}),body:JSON.stringify({code})});
    const data=await res.json().catch(()=>({}));
    if(!res.ok)throw new Error(data.error||'Ошибка');
    if(data.profile)S.profileData=data.profile;
    const ov=$('sessionRecoveryOverlay');
    if(ov)ov.classList.remove('open');
    if(status){status.textContent='';status.className='feedback-status'}
    refreshLiveData(true,true).catch(()=>{});
  }catch(e){
    if(status){status.textContent=e.message||'Неверный код';status.className='feedback-status error'}
  }finally{if(btn)btn.disabled=false}
}

/* Download file with auth — open link directly (works in Telegram WebView) */
function downloadFile(url,name){
  const a=document.createElement('a');
  a.href=withMiniappToken(url);
  a.target='_blank';
  if(name)a.download=name;
  document.body.appendChild(a);a.click();a.remove();
}

function attachmentAbsoluteUrl(url){
  return new URL(withMiniappToken(url),window.location.origin).toString();
}

function attachmentPreviewUrl(url){
  const full=new URL(withMiniappToken(url),window.location.origin);
  full.searchParams.set('inline','1');
  return full.toString();
}

function attachmentSystemUrl(url){
  const full=new URL(withMiniappToken(url),window.location.origin);
  full.searchParams.set('inline','1');
  full.searchParams.set('open_external','1');
  return full.toString();
}

function officeViewerUrl(url){
  return 'https://view.officeapps.live.com/op/embed.aspx?src='+encodeURIComponent(attachmentPreviewUrl(url));
}

function attachmentExt(name,url){
  const source=String(name||url||'').split('?')[0].toLowerCase();
  const dot=source.lastIndexOf('.');
  return dot>=0?source.slice(dot+1):'';
}

function escapeJsString(value){
  return String(value||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
}

function attachmentLink(url,name){
  const displayName=name||'Файл';
  return '<a class="att-chip" href="#" onclick="event.preventDefault();openAttachmentViewer(\''+escapeJsString(url)+'\',\''+escapeJsString(displayName)+'\')">'+esc(displayName)+'</a>';
}

function openExternalFile(url,name){
  const fileName=String(name||'Файл');
  const ext=attachmentExt(fileName,url);
  const targetUrl=['ppt','pptx','pps','ppsx','doc','docx','xls','xlsx'].includes(ext)?officeViewerUrl(url):attachmentPreviewUrl(url);
  if(isAppleMobile()){
    window.location.assign(targetUrl);
    return;
  }
  try{
    if(window.Telegram&&window.Telegram.WebApp&&typeof window.Telegram.WebApp.openLink==='function'){
      const options={try_instant_view:false};
      if(isAppleMobile())options.try_browser='safari';
      window.Telegram.WebApp.openLink(targetUrl,options);
      return;
    }
  }catch(e){}
  window.open(targetUrl,'_blank','noopener,noreferrer');
}

function systemOpenLabel(){
  return isAppleMobile()?'Открыть в iOS':'Открыть в системе';
}

function openSystemFile(url){
  const targetUrl=attachmentSystemUrl(url);
  if(isAppleMobile()){
    window.location.assign(targetUrl);
    return;
  }
  try{
    if(window.Telegram&&window.Telegram.WebApp&&typeof window.Telegram.WebApp.openLink==='function'){
      const options={try_instant_view:false};
      if(isAppleMobile())options.try_browser='safari';
      window.Telegram.WebApp.openLink(targetUrl,options);
      return;
    }
  }catch(e){}
  window.open(targetUrl,'_blank','noopener,noreferrer');
}

function fileViewerActions(fileUrl,fileName,opts={}){
  const actions=[];
  if(opts.copyText){
    actions.push('<button class="retry-btn" type="button" style="margin-top:0" onclick="copyAttachmentText()">Копировать текст</button>');
  }
  if(opts.systemOpen!==false){
    actions.push('<button class="att-chip" type="button" onclick="openSystemFile(\''+escapeJsString(fileUrl)+'\')">'+esc(systemOpenLabel())+'</button>');
  }
  if(opts.externalOpen){
    actions.push('<button class="att-chip" type="button" onclick="openExternalFile(\''+escapeJsString(fileUrl)+'\',\''+escapeJsString(fileName)+'\')">Открыть отдельно</button>');
  }
  actions.push('<button class="retry-btn" type="button" style="margin-top:0" onclick="downloadFile(\''+escapeJsString(fileUrl)+'\',\''+escapeJsString(fileName)+'\')">Скачать</button>');
  return '<div class="file-viewer-actions">'+actions.join('')+'</div>';
}

async function copyAttachmentText(){
  const el=$('fileViewerText');
  if(!el)return;
  const value='value' in el?String(el.value||''):String(el.textContent||'');
  const ok=await tryCopyText(value).catch(()=>false);
  if(ok){
    txt('sheetFileTitle','Скопировано');
    setTimeout(()=>{
      const title=$('sheetFileTitle');
      const original=title&&title.dataset&&title.dataset.originalTitle?title.dataset.originalTitle:'';
      if(original)txt('sheetFileTitle',original);
    },1100);
  }
}

async function openAttachmentViewer(url,name){
  const fileUrl=String(url||'');
  const fileName=String(name||'Файл');
  const ext=attachmentExt(fileName,fileUrl);
  if(isAppleMobile()&&['ppt','pptx','pps','ppsx','doc','docx','xls','xlsx'].includes(ext)){
    openSystemFile(fileUrl);
    return;
  }
  const titleEl=$('sheetFileTitle');
  if(titleEl&&titleEl.dataset)titleEl.dataset.originalTitle=fileName;
  txt('sheetFileTitle',fileName);
  html('sheetFileBody','<div class="loader"><span class="spin"></span></div>');
  $('fileViewerOverlay').classList.add('open');
  const previewUrl=attachmentPreviewUrl(fileUrl);
  try{
    if(['png','jpg','jpeg','gif','webp','bmp','svg','heic','heif'].includes(ext)){
      html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{systemOpen:true})+'<div class="file-viewer-frame"><img src="'+esc(previewUrl)+'" alt="'+esc(fileName)+'"></div></div>');
      return;
    }
    if(ext==='pdf'){
      html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{systemOpen:true})+'<div class="file-viewer-frame"><iframe src="'+esc(previewUrl)+'#toolbar=1&navpanes=0"></iframe></div></div>');
      return;
    }
    if(['mp4','webm','mov','m4v'].includes(ext)){
      html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{systemOpen:true})+'<div class="file-viewer-frame"><video controls playsinline src="'+esc(previewUrl)+'"></video></div></div>');
      return;
    }
    if(['mp3','m4a','wav','ogg','aac'].includes(ext)){
      html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{systemOpen:true})+'<div class="file-viewer-frame" style="min-height:0;padding:20px"><audio controls src="'+esc(previewUrl)+'"></audio></div></div>');
      return;
    }
    if(['txt','log','md','csv','json','xml','html','htm','py','js','ts','css','ini','cfg','yml','yaml'].includes(ext)){
      const r=await fetch(previewUrl,{credentials:'same-origin',headers:miniappHeaders()});
      if(!r.ok)throw new Error('Не удалось открыть файл');
      const text=await r.text();
      html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{copyText:true,systemOpen:true})+'<div class="file-viewer-frame"><textarea id="fileViewerText" class="file-viewer-textarea" readonly spellcheck="false">'+esc(text)+'</textarea></div></div>');
      return;
    }
    if(['ppt','pptx','pps','ppsx','doc','docx','xls','xlsx'].includes(ext)){
      html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{systemOpen:true})+'<div class="file-viewer-frame"><div class="file-viewer-empty">Для офисных файлов встроенный просмотр в Telegram/iPhone часто работает плохо.<br>Откройте файл через системный просмотрщик iOS или скачайте его.</div></div></div>');
      return;
    }
    html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{systemOpen:true})+'<div class="file-viewer-frame"><div class="file-viewer-empty">Предпросмотр для этого формата внутри миниаппа недоступен.<br>Откройте файл через системное приложение или скачайте его.</div></div></div>');
  }catch(e){
    html('sheetFileBody','<div class="file-viewer-wrap">'+fileViewerActions(fileUrl,fileName,{systemOpen:true})+'<div class="file-viewer-frame"><div class="file-viewer-empty">'+esc(e.message||'Не удалось открыть файл')+'</div></div></div>');
  }
}

function isAppleMobile(){
  return /iPhone|iPad|iPod/i.test(navigator.userAgent) || (navigator.platform==='MacIntel' && navigator.maxTouchPoints>1);
}

function showPwaLinkBox(url,status,boxId='pwaGuideLinkBox',inputId='pwaGuideLinkInput'){
  return showLinkBox(boxId,inputId,url,status);
}

function showPwaIconLinkBox(url,status){
  return showLinkBox('pwaIconLinkBox','pwaIconLinkInput',url,status);
}

function showLinkBox(boxId,inputId,url,status){
  const box=$(boxId);
  if(!box)return;
  box.innerHTML='<input class="pwa-link-input" id="'+esc(inputId)+'" readonly value="'+esc(url)+'">'
    +'<div class="pwa-link-actions">'
    +'<button class="retry-btn" type="button" style="margin-top:0;padding:8px 16px;font-size:12px" onclick="selectPwaLink(\''+escapeJsString(inputId)+'\')">Выделить ссылку</button>'
    +'<a class="att-chip" href="'+esc(url)+'" target="_blank" rel="noopener">Открыть ссылку</a>'
    +'</div>'
    +(status?'<div class="pwa-link-note">'+esc(status)+'</div>':'');
  const input=$(inputId);
  if(input){input.focus();input.select();if(input.setSelectionRange)input.setSelectionRange(0,input.value.length)}
}

function selectPwaLink(inputId='pwaLinkInput'){
  const input=$(inputId);
  if(!input)return;
  input.focus();
  input.select();
  if(input.setSelectionRange)input.setSelectionRange(0,input.value.length);
}

async function tryCopyText(value){
  if(navigator.clipboard&&window.isSecureContext){
    await navigator.clipboard.writeText(value);
    return true;
  }
  const ta=document.createElement('textarea');
  ta.value=value;
  ta.style.cssText='position:fixed;left:-9999px;top:0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  let ok=false;
  try{ok=document.execCommand('copy')}finally{document.body.removeChild(ta)}
  return ok;
}

function renderPwaIconPreview(opts={}){
  const preview=$('pwaIconPreview');
  if(!preview)return;
  const bg=opts.bg||String((($('pwaIconBg')||{}).value)||((S.profileData||{}).pwa_icon_bg)||'#4a76a8');
  const emoji=String(opts.emoji||(($('pwaIconEmoji')||{}).value)||((S.profileData||{}).pwa_icon_emoji)||'📘').trim().slice(0,2)||'📘';
  const imageUrl=String(opts.imageUrl||S.pendingPwaIconImageData||(((S.profileData||{}).pwa_icon_has_image)?((S.profileData||{}).pwa_icon_url||''):'')).trim();
  preview.style.background=bg;
  if(imageUrl){
    preview.innerHTML='<img src="'+esc(imageUrl)+'" alt="Иконка">';
    return;
  }
  preview.innerHTML='';
  preview.textContent=emoji;
}

function describeCurrentPwaIcon(data){
  const profile=data||S.profileData||{};
  if(profile.pwa_icon_has_image&&profile.pwa_icon_url)return 'Своя картинка';
  return 'Эмодзи '+String(profile.pwa_icon_emoji||'📘');
}

function readFileAsDataUrl(file){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve(String(reader.result||''));
    reader.onerror=()=>reject(new Error('Не удалось прочитать файл.'));
    reader.readAsDataURL(file);
  });
}

function loadImageElement(src){
  return new Promise((resolve,reject)=>{
    const img=new Image();
    img.onload=()=>resolve(img);
    img.onerror=()=>reject(new Error('Не удалось открыть изображение.'));
    img.src=src;
  });
}

async function fileToPwaIconDataUrl(file){
  const original=await readFileAsDataUrl(file);
  const img=await loadImageElement(original);
  const size=512;
  const canvas=document.createElement('canvas');
  canvas.width=size;
  canvas.height=size;
  const ctx=canvas.getContext('2d');
  if(!ctx)throw new Error('Не удалось подготовить картинку.');
  const scale=Math.max(size/img.width,size/img.height);
  const width=img.width*scale;
  const height=img.height*scale;
  const x=(size-width)/2;
  const y=(size-height)/2;
  ctx.clearRect(0,0,size,size);
  ctx.drawImage(img,x,y,width,height);
  return canvas.toDataURL('image/png');
}

async function handlePwaIconFileChange(event){
  const file=((event||{}).target||{}).files&&((event||{}).target||{}).files[0];
  const hint=$('pwaIconFileHint');
  if(!file){
    S.pendingPwaIconImageData='';
    renderPwaIconPreview();
    if(hint)hint.textContent='Можно загрузить свою картинку. Она будет приведена к квадратной PNG-иконке.';
    return;
  }
  try{
    if(file.size>12*1024*1024)throw new Error('Файл слишком большой.');
    S.pendingPwaIconImageData=await fileToPwaIconDataUrl(file);
    renderPwaIconPreview({imageUrl:S.pendingPwaIconImageData});
    /* Auto-clear emoji when custom image is loaded */
    const emojiInput=$('pwaIconEmoji');
    if(emojiInput){emojiInput.value='';emojiInput.dispatchEvent(new Event('input'))}
    if(hint)hint.textContent='Картинка подготовлена. Нажмите «Сохранить иконку», затем установите PWA по новой ссылке ниже.';
  }catch(e){
    S.pendingPwaIconImageData='';
    renderPwaIconPreview();
    if(hint)hint.textContent=e.message||'Не удалось обработать картинку.';
    alert(e.message||'Не удалось обработать картинку.');
  }
}

function closeFeedbackOverlay(){
  closeOv('feedbackOverlay');
  const status=$('feedbackStatus');
  if(status){status.textContent='Сообщение уйдёт в Telegram-бот администратора вместе с техническими логами.';status.className='feedback-status';}
}

function openFeedback(kind){
  S.feedbackKind=kind==='feature'?'feature':'bug';
  txt('sheetFeedbackTitle',S.feedbackKind==='feature'?'Предложить функцию':'Сообщить о баге');
  const subject=$('feedbackSubject');
  const message=$('feedbackMessage');
  const status=$('feedbackStatus');
  if(subject&&!subject.value.trim())subject.value=S.feedbackKind==='feature'?'Идея по mini app':'Проблема в mini app';
  if(message){
    message.placeholder=S.feedbackKind==='feature'
      ? 'Что хочется добавить? Как это должно работать? В каком разделе это должно быть?'
      : 'Что сломалось? Как это повторить? Что ожидалось вместо этого?';
  }
  if(status){status.textContent='Сообщение уйдёт в Telegram-бот администратора вместе с техническими логами.';status.className='feedback-status';}
  $('feedbackOverlay').classList.add('open');
  setTimeout(()=>{if(subject)subject.focus()},30);
}

async function submitFeedback(){
  const subject=$('feedbackSubject');
  const message=$('feedbackMessage');
  const status=$('feedbackStatus');
  const btn=$('feedbackSubmitBtn');
  const subjectText=String(subject&&subject.value||'').trim();
  const messageText=String(message&&message.value||'').trim();
  if(!subjectText||subjectText.length<4){if(status){status.textContent='Добавьте короткий заголовок.';status.className='feedback-status error';}if(subject)subject.focus();return;}
  if(!messageText||messageText.length<10){if(status){status.textContent='Опишите подробнее, хотя бы в 10 символов.';status.className='feedback-status error';}if(message)message.focus();return;}
  if(btn)btn.disabled=true;
  if(status){status.textContent='Отправка…';status.className='feedback-status';}
  try{
    await postApi('/api/mini/netschool/feedback',{
      kind:S.feedbackKind||'bug',
      subject:subjectText,
      message:messageText,
      current_tab:S.currentTab,
      page_url:location.href,
      standalone:isStandalonePwa(),
    });
    if(status){status.textContent='Сообщение отправлено. Спасибо.';status.className='feedback-status success';}
    if(subject)subject.value='';
    if(message)message.value='';
    setTimeout(closeFeedbackOverlay,650);
  }catch(e){
    if(status){status.textContent=e.message||'Не удалось отправить сообщение.';status.className='feedback-status error';}
  }finally{
    if(btn)btn.disabled=false;
  }
}

function urlBase64ToUint8Array(base64String){
  const padding='='.repeat((4-base64String.length%4)%4);
  const base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');
  const raw=atob(base64);
  return Uint8Array.from([...raw].map(ch=>ch.charCodeAt(0)));
}

function isStandalonePwa(){
  return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone===true;
}

function setTopLoading(text,active){
  const indicator=$('refreshIndicator');
  if(!indicator)return;
  indicator.textContent=text||'';
  indicator.classList.toggle('loading',!!active);
  indicator.classList.toggle('show',!!active);
}

function nowSyncLabel(){
  const d=new Date();
  return pad2(d.getDate())+'.'+pad2(d.getMonth()+1)+'.'+d.getFullYear()+' '+pad2(d.getHours())+':'+pad2(d.getMinutes());
}

function showRefreshStatus(ok,message){
  const indicator=$('refreshIndicator');
  if(!indicator)return;
  indicator.classList.remove('loading');
  indicator.classList.add('show');
  indicator.textContent=message||(ok?'Обновление данных прошло успешно':'Обновление данных не удалось');
  setTimeout(()=>{
    indicator.classList.remove('show');
  },ok?1500:2200);
}

function extractMiniappTokenFromUrl(url){
  try{
    const u=new URL(url,window.location.origin);
    return String(u.searchParams.get('token')||'').trim();
  }catch(e){
    return '';
  }
}

function updateThemeChrome(){
  const meta=document.querySelector('meta[name="theme-color"]');
  const c=S.theme==='dark'?'#1e3a5f':'#4a76a8';
  if(meta)meta.setAttribute('content',c);
  /* update topbar gradient to match accent if set */
  const root=document.documentElement;
  if(S.accentColor){
    const r=parseInt(S.accentColor.slice(1,3),16),g=parseInt(S.accentColor.slice(3,5),16),b=parseInt(S.accentColor.slice(5,7),16);
    const yiq=(r*299+g*587+b*114)/1000;
    root.style.setProperty('--primary-contrast',yiq>=186?'#1f2c3a':'#ffffff');
    root.style.setProperty('--primary-dark',S.theme==='dark'?darkenHex(S.accentColor,.18):darkenHex(S.accentColor,.24));
    root.style.setProperty('--primary-light',S.theme==='dark'?darkenHex(S.accentColor,.64):lightenHex(S.accentColor,.84));
    root.style.setProperty('--topbar',S.theme==='dark'?darkenHex(S.accentColor,.35):S.accentColor);
    root.style.setProperty('--topbar-grad',S.theme==='dark'?darkenHex(S.accentColor,.2):lightenHex(S.accentColor,.15));
  }else{
    root.style.removeProperty('--primary-contrast');
    root.style.removeProperty('--primary-dark');
    root.style.removeProperty('--primary-light');
    root.style.removeProperty('--topbar');root.style.removeProperty('--topbar-grad');
  }
}
function isThemeSyncEnabled(){return !(S.profileData&&S.profileData.theme_sync===false)}
function lightenHex(hex,amt){
  let r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  r=Math.min(255,Math.round(r+(255-r)*amt));g=Math.min(255,Math.round(g+(255-g)*amt));b=Math.min(255,Math.round(b+(255-b)*amt));
  return '#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');
}
function darkenHex(hex,amt){
  let r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  r=Math.max(0,Math.round(r*(1-amt)));g=Math.max(0,Math.round(g*(1-amt)));b=Math.max(0,Math.round(b*(1-amt)));
  return '#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join('');
}
function mergeProfileData(nextProfile){
  if(!nextProfile)return;
  S.profileData=Object.assign({},S.profileData||{},nextProfile);
  updateTopbarTitle();
}
function syncAppearanceFromProfile(profile,opts){
  const next=profile||S.profileData||{};
  const options=opts||{};
  mergeProfileData(next);
  const sync=next.theme_sync!==false;
  if(!sync)return;
  const localThemeTs=parseStoredTs(localStorage.getItem(NS_THEME_TS_KEY)||0);
  const localAccentTs=parseStoredTs(localStorage.getItem(NS_ACCENT_TS_KEY)||0);
  const remoteThemeTs=Date.parse(next.theme_updated_at||'')||0;
  const remoteAccentTs=Date.parse(next.accent_updated_at||'')||0;
  const remoteTheme=String(next.theme||'').trim();
  const remoteAccent=String(next.accent_color||'').trim();
  if(remoteTheme&&(options.force||remoteThemeTs>=localThemeTs||!localStorage.getItem('ns-theme'))){
    if(remoteTheme!==S.theme)document.documentElement.setAttribute('data-theme',remoteTheme);
    S.theme=remoteTheme;
    setLocalThemeChoice(remoteTheme,remoteThemeTs||Date.now());
  }
  if(options.force||remoteAccentTs>=localAccentTs||!localStorage.getItem('ns-accent')){
    S.accentColor=remoteAccent;
    setLocalAccentChoice(remoteAccent,remoteAccentTs||Date.now());
    if(remoteAccent){
      document.documentElement.style.setProperty('--accent',remoteAccent);
      document.documentElement.style.setProperty('--primary',remoteAccent);
    }else{
      document.documentElement.style.removeProperty('--accent');
      document.documentElement.style.removeProperty('--primary');
    }
  }
  updateThemeChrome();
}
function availableStudents(){
  const profile=S.profileData||{};
  const raw=Array.isArray(profile.available_students)?profile.available_students:[];
  return raw
    .map(item=>{
      const sid=Number(item&&item.id);
      if(!Number.isFinite(sid))return null;
      const name=String((item&&item.name)||'').trim()||('Ученик '+sid);
      return {id:sid,name};
    })
    .filter(Boolean);
}
function selectedStudentId(){
  const profile=S.profileData||{};
  const sid=Number(profile.selected_student_id);
  return Number.isFinite(sid)?sid:null;
}
function selectedStudentName(){
  const students=availableStudents();
  const sid=selectedStudentId();
  const selected=students.find(item=>sid!=null&&item.id===sid);
  const profileName=String((S.profileData||{}).student_name||'').trim();
  const isGenericName=v=>/^(ученик|учаник|student)\s+\d+$/i.test(String(v||'').trim());
  if(selected&&selected.name){
    const isGeneric=isGenericName(selected.name);
    if(!isGeneric)return selected.name;
  }
  if(profileName&&!isGenericName(profileName))return profileName;
  return selected&&selected.name?selected.name:'Дневник';
}
function updateTopbarTitle(){
  const top=$('topTitle');
  if(!top)return;
  if(S.currentTab==='diary'){
    const students=availableStudents();
    const name=selectedStudentName();
    if(students.length>=2){
      top.classList.add('is-clickable');
      top.innerHTML='<span>'+esc(name)+'</span><span class="topbar-caret">▾</span>';
      top.onclick=()=>openChildSwitchOverlay();
      return;
    }
    top.classList.remove('is-clickable');
    top.textContent=name||'Дневник';
    top.onclick=null;
    return;
  }
  top.classList.remove('is-clickable');
  top.textContent=tabTitles[S.currentTab]||S.currentTab;
  top.onclick=null;
}
function renderChildSwitchSheet(){
  const body=$('sheetChildSwitchBody');
  if(!body)return;
  const students=availableStudents();
  if(students.length<2){
    body.innerHTML='<div class="empty">В профиле найден только один ребёнок.</div>';
    return;
  }
  const sid=selectedStudentId();
  const buttonsHtml=students.map(item=>{
    const isActive=sid!=null&&item.id===sid;
    const styleParts=['margin-top:0','text-align:left'];
    if(isActive)styleParts.push('background:var(--primary)','color:var(--primary-contrast, #fff)');
    return '<button class="retry-btn" data-student-id="'+item.id+'" style="'+styleParts.join(';')+'">'+(isActive?'✅ ':'')+esc(item.name)+'</button>';
  }).join('');
  body.innerHTML='<div style="display:flex;flex-direction:column;gap:8px">'+buttonsHtml+'</div>';
  body.querySelectorAll('button[data-student-id]').forEach(btn=>{
    btn.addEventListener('click',()=>selectMiniappChild(btn));
  });
}
function openChildSwitchOverlay(){
  renderChildSwitchSheet();
  $('childSwitchOverlay')?.classList.add('open');
}
async function selectMiniappChild(btn){
  if(!btn)return;
  const studentId=Number(btn.dataset.studentId);
  if(!Number.isFinite(studentId))return;
  btn.disabled=true;
  try{
    const res=await postApi('/api/mini/netschool/child/select',{student_id:studentId});
    if(res&&res.profile)mergeProfileData(res.profile);
    $('childSwitchOverlay')?.classList.remove('open');
    updateTopbarTitle();
    await refreshLiveData(true,true);
  }catch(e){
    alert(e.message||'Не удалось переключить ребёнка');
  }finally{
    btn.disabled=false;
  }
}
function applyTheme(t,save){S.theme=t;document.documentElement.setAttribute('data-theme',t);setLocalThemeChoice(t);updateThemeChrome();if(save!==false&&isThemeSyncEnabled())postApi('/api/mini/netschool/settings/toggle',{key:'theme',value:t}).catch(()=>{})}
applyTheme(S.theme,false);

(function(){
  let lastTouch=0;
  document.addEventListener('touchend',e=>{
    const target=e.target;
    if(target&&target.closest&&target.closest('input, textarea, select'))return;
    const now=Date.now();
    if(now-lastTouch<280)e.preventDefault();
    lastTouch=now;
  },{passive:false});
})();

function closeOv(id){$(id).classList.remove('open')}
document.querySelectorAll('.overlay,.cal-overlay').forEach(ov=>{ov.addEventListener('click',e=>{if(e.target===ov)ov.classList.remove('open')})});

const tabTitles={diary:'Дневник',grades:'Оценки',calc:'Калькулятор',homework:'Задания',mail:'Почта',profile:'Профиль'};
updateTopbarTitle();
function refreshCurrentTab(){
  if(S.currentTab==='diary'){renderWeekNav();renderDiary();return}
  if(S.currentTab==='grades'){renderGrades();return}
  if(S.currentTab==='calc'){renderCalc();return}
  if(S.currentTab==='homework'){renderHomework();return}
  if(S.currentTab==='mail'){renderMailList();return}
  if(S.currentTab==='profile'){renderProfile();return}
}
function switchTab(tab){
  S.currentTab=tab;
  if(location.hash!==('#'+tab))history.replaceState(null,'','#'+tab);
  updateTopbarTitle();
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id==='p-'+tab));
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.toggle('active',n.dataset.tab===tab));
  const activePanel=document.getElementById('p-'+tab);
  if(activePanel)activePanel.scrollTop=0;
  if(tab==='mail'&&!S.mail)ensureMailLoaded();
  refreshCurrentTab();
}
document.querySelectorAll('.nav-item').forEach(el=>el.addEventListener('click',()=>switchTab(el.dataset.tab)));

function activePanelScrollTop(){
  const activePanel=document.querySelector('.panel.active');
  return activePanel?activePanel.scrollTop:0;
}

function syncDiarySelectionFromDash(preferDash=false){
  const diaryDays=((S.dash||{}).diary_days||[]);
  if(!diaryDays.length)return;
  const dashSelected=String((S.dash||{}).selected_date||'').trim();
  const hasCurrent=S.selectedDate&&diaryDays.some(day=>day.date===S.selectedDate);
  if(preferDash&&dashSelected&&diaryDays.some(day=>day.date===dashSelected)){
    S.selectedDate=dashSelected;
    updateWeekOffsetForSelectedDate();
    return;
  }
  if(hasCurrent)return;
  if(dashSelected&&diaryDays.some(day=>day.date===dashSelected)){
    S.selectedDate=dashSelected;
    updateWeekOffsetForSelectedDate();
    return;
  }
  const todayIso=isoDate(new Date());
  const fallback=diaryDays.find(day=>String(day.date)>=todayIso)||diaryDays[diaryDays.length-1];
  if(fallback&&fallback.date){
    S.selectedDate=fallback.date;
    updateWeekOffsetForSelectedDate();
  }
}

function updateWeekOffsetForSelectedDate(){
  if(!S.selectedDate)return;
  const today=new Date();today.setHours(0,0,0,0);
  const sel=new Date(S.selectedDate+'T00:00:00');
  const todayMon=getMonday(today),selMon=getMonday(sel);
  S.weekOffset=Math.round((selMon-todayMon)/(7*86400000));
}

function moveDiaryDate(delta){
  const allDays=((S.dash||{}).diary_days||[]).slice().sort((a,b)=>String(a.date).localeCompare(String(b.date)));
  if(!allDays.length)return;
  let idx=allDays.findIndex(d=>d.date===S.selectedDate);
  if(idx<0){
    idx=allDays.findIndex(d=>String(d.date)>=String(S.selectedDate||''));
    if(idx<0)idx=allDays.length-1;
  }
  const next=allDays[idx+delta];
  if(!next)return;
  const dir=delta>0?'left':'right';
  S.selectedDate=next.date;
  updateWeekOffsetForSelectedDate();
  renderWeekNav();
  renderDiary(dir,true);
}

function attachHorizontalSwipe(element,leftHandler,rightHandler){
  if(!element)return;
  let startX=0,startY=0;
  element.addEventListener('touchstart',e=>{startX=e.touches[0].clientX;startY=e.touches[0].clientY},{passive:true});
  element.addEventListener('touchend',e=>{
    const dx=e.changedTouches[0].clientX-startX;
    const dy=e.changedTouches[0].clientY-startY;
    if(Math.abs(dx)>50&&Math.abs(dx)>Math.abs(dy)*1.5){
      if(dx<0&&leftHandler)leftHandler();
      else if(dx>0&&rightHandler)rightHandler();
    }
  },{passive:true});
}

function markCls(v){const n=parseInt(v);if(n>=5)return'mark-5';if(n===4)return'mark-4';if(n===3)return'mark-3';return'mark-2'}
function gradeColor(v){const n=Math.round(parseFloat(v));if(n>=5)return'g5';if(n===4)return'g4';if(n===3)return'g3';return'g2'}

const DN=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const DNF=['Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье'];
const MO=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
const MON=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const CALC_MARKS=[5,4,3,2];
const CALC_LABELS={5:'Пятерок',4:'Четверок',3:'Троек',2:'Двоек'};

function gradeItemKey(item,subjectName){return [subjectName||item.subject||'',item.quarter||'',item.date_sort||item.date||'',item.title||'',item.mark||'',item.weight||1].join('|')}
function homeworkItemKey(item){
  const attIds=[...(item.attachments||[]),...(item.atts||[])].map(a=>String(a.id||'')).sort().join(',');
  return [item.sort_date||item.date||'',item.subject||'',item.text||'',attIds].join('|');
}
function computeDashboardDelta(prevDash,nextDash){
  if(!prevDash||!nextDash)return {newGradeKeys:new Set(),changedSubjects:new Set(),newHomeworkKeys:new Set(),gradeCount:0,homeworkCount:0};
  const prevGradeKeys=new Set();
  ((prevDash.subjects)||[]).forEach(subject=>((subject.items)||[]).forEach(item=>prevGradeKeys.add(gradeItemKey(item,subject.subject))));
  const nextGradeKeys=new Set();
  ((nextDash.subjects)||[]).forEach(subject=>((subject.items)||[]).forEach(item=>nextGradeKeys.add(gradeItemKey(item,subject.subject))));
  const newGradeKeys=new Set([...nextGradeKeys].filter(key=>!prevGradeKeys.has(key)));
  const changedSubjects=new Set();
  const prevSubjects=new Map(((prevDash.subjects)||[]).map(subject=>[subject.subject,JSON.stringify(((subject.items)||[]).map(item=>gradeItemKey(item,subject.subject)).sort())]));
  ((nextDash.subjects)||[]).forEach(subject=>{
    const nextItems=JSON.stringify(((subject.items)||[]).map(item=>gradeItemKey(item,subject.subject)).sort());
    if((prevSubjects.get(subject.subject)||'')!==nextItems)changedSubjects.add(subject.subject);
  });
  const prevHomework=new Set(((prevDash.homework)||[]).map(homeworkItemKey));
  const newHomeworkKeys=new Set((((nextDash.homework)||[]).map(homeworkItemKey)).filter(key=>!prevHomework.has(key)));
  return {newGradeKeys,changedSubjects,newHomeworkKeys,gradeCount:newGradeKeys.size,homeworkCount:newHomeworkKeys.size};
}
function setBadge(id,count){
  const el=$(id);if(!el)return;
  const value=parseInt(count,10)||0;
  el.textContent=value>99?'99+':String(value);
  el.classList.toggle('show',value>0);
}
function updateNavBadges(){
  setBadge('badgeGrades',S.delta.gradeCount||0);
  setBadge('badgeHomework',S.delta.homeworkCount||0);
  setBadge('badgeMail',S.delta.unreadMailCount||0);
}

function getMonday(d){const r=new Date(d);const dy=r.getDay();r.setDate(r.getDate()-dy+(dy===0?-6:1));r.setHours(0,0,0,0);return r}

function getWeekDays(off){
  const today=new Date();today.setHours(0,0,0,0);
  const mon=getMonday(today);mon.setDate(mon.getDate()+off*7);
  const days=[];
  for(let i=0;i<7;i++){
    const d=new Date(mon);d.setDate(mon.getDate()+i);
    const iso=isoDate(d);
    days.push({date:iso,dayNum:d.getDate(),dayName:DN[i],isToday:isoDate(d)===isoDate(today)});
  }
  return days;
}
function weekRangeLabel(off){
  const days=getWeekDays(off);
  const d0=new Date(days[0].date+'T00:00:00'),d6=new Date(days[6].date+'T00:00:00');
  return d0.getDate()+' '+MO[d0.getMonth()]+' — '+d6.getDate()+' '+MO[d6.getMonth()];
}

function renderWeekNav(){txt('weekLabel',weekRangeLabel(S.weekOffset))}
$('weekPrev').onclick=()=>{S.weekOffset--;S.selectedDate=null;renderWeekNav();renderDiary('',true)};
$('weekNext').onclick=()=>{S.weekOffset++;S.selectedDate=null;renderWeekNav();renderDiary('',true)};
$('weekLabel').onclick=()=>openCalendar();

function renderDayStrip(){
  const days=getWeekDays(S.weekOffset);
  if(!S.selectedDate||!days.find(d=>d.date===S.selectedDate)){
    const td=days.find(d=>d.isToday);
    S.selectedDate=td?td.date:days[0].date;
  }
  html('dayStrip',days.map(d=>`<button class="day-chip${d.date===S.selectedDate?' active':''}${d.isToday?' today':''}" data-d="${d.date}">${esc(d.dayName)}<span class="dn">${d.dayNum}</span></button>`).join(''));
  document.querySelectorAll('.day-chip').forEach(el=>el.addEventListener('click',()=>{S.selectedDate=el.dataset.d;renderDiary('',true)}));
}

function openLessonHomework(dateKey,lessonIdx){
  buildHwIndex();
  const items=S.hwByDate[dateKey]||[];
  const targetIdx=items.findIndex(item=>String(item.source_idx)===String(lessonIdx));
  if(targetIdx<0)return;
  openHwDetail(dateKey,targetIdx);
}

function lessonByPosition(dateKey,lessonIdx){
  const allDays=(S.dash||{}).diary_days||[];
  const day=allDays.find(d=>d.date===dateKey);
  if(!day)return null;
  const lessons=day.lessons||[];
  return {day,lesson:lessons[lessonIdx]||null};
}

function openLessonInfo(dateKey,lessonIdx){
  const data=lessonByPosition(dateKey,lessonIdx);
  if(!data||!data.lesson)return;
  const l=data.lesson;
  const dayLabel=data.day&&data.day.display_date?data.day.display_date:(dateKey||'');
  txt('sheetLessonInfoTitle',(l.subject||'Урок')+(dayLabel?' · '+dayLabel:''));
  let body='';
  if(l.topic)body+='<div style="font-size:15px;line-height:1.5;margin-bottom:12px"><strong>Тема урока:</strong><br>'+esc(l.topic)+'</div>';
  else body+='<div style="font-size:14px;color:var(--text2);margin-bottom:12px">Тема урока в электронном журнале не указана.</div>';
  const meta=[];
  if(l.time)meta.push('Время: '+esc(l.time));
  if(l.room)meta.push('Кабинет: '+esc(l.room));
  if(typeof l.number==='number')meta.push('Урок №'+esc(l.number));
  if(meta.length)body+='<div style="font-size:13px;color:var(--text2);line-height:1.6">'+meta.join('<br>')+'</div>';
  html('sheetLessonInfoBody',body);
  $('lessonInfoOverlay').classList.add('open');
}

function openLessonMarkInfo(dateKey,lessonIdx,markIdx){
  const data=lessonByPosition(dateKey,lessonIdx);
  if(!data||!data.lesson)return;
  const mark=((data.lesson.marks||[])[markIdx])||null;
  if(!mark)return;
  const dayLabel=data.day&&data.day.display_date?data.day.display_date:(dateKey||'');
  txt('sheetLessonInfoTitle','Оценка: '+esc(mark.mark||'—'));
  let body='<div style="font-size:14px;line-height:1.6">';
  body+='<div><strong>Предмет:</strong> '+esc(data.lesson.subject||'—')+'</div>';
  body+='<div><strong>Тип:</strong> '+esc(mark.title||'Задание')+'</div>';
  body+='<div><strong>Когда внесена:</strong> '+esc(mark.entered_at_label||mark.date_label||dayLabel||'—')+'</div>';
  if(mark.weight&&Number(mark.weight)>1)body+='<div><strong>Вес:</strong> x'+esc(mark.weight)+'</div>';
  if(mark.comment)body+='<div style="margin-top:8px"><strong>Комментарий:</strong><br>'+esc(mark.comment)+'</div>';
  body+='</div>';
  html('sheetLessonInfoBody',body);
  $('lessonInfoOverlay').classList.add('open');
}

function renderDayLessons(direction=''){
  const allDays=(S.dash||{}).diary_days||[];
  const day=allDays.find(d=>d.date===S.selectedDate);
  const content=$('diaryContent');
  if(content){content.classList.remove('diary-swipe-left','diary-swipe-right');if(direction)content.classList.add(direction==='left'?'diary-swipe-left':'diary-swipe-right')}
  if(!day||!day.lessons||!day.lessons.length){
    const dt=S.selectedDate?new Date(S.selectedDate+'T00:00:00'):new Date();
    const wd=dt.getDay();
    const lbl=DNF[wd===0?6:wd-1]+', '+dt.getDate()+' '+MO[dt.getMonth()];
    html('diaryContent','<div class="empty">Нет уроков<br><small>'+esc(lbl)+'</small></div>');
    return;
  }
  html('diaryContent','<div class="lesson-list">'+day.lessons.map((l,i)=>{
    const num=l.number||(i+1);
    const filesCount=(l.hw_attachments_count!=null?Number(l.hw_attachments_count):hwAllAttachments({atts:l.hw_attachments||[],details:l.hw_details||[]}).length);
    const marks=(l.marks||[]).map((m,mi)=>'<button type="button" class="lesson-mark-btn" data-mark-date="'+esc(S.selectedDate)+'" data-mark-lesson="'+i+'" data-mark-idx="'+mi+'"><span class="lesson-mark-wrap"><span class="mark '+markCls(m.mark)+'">'+esc(m.mark)+'</span>'+(m.weight&&Number(m.weight)>1?'<span class="mark-weight">x'+esc(m.weight)+'</span>':'')+'</span></button>').join('');
    let hwBlock='';
    if(l.has_homework||l.homework||(l.hw_attachments||[]).length){
      hwBlock='<div class="lesson-hw-btn'+(filesCount?' has-files':'')+'" data-hw-date="'+esc(S.selectedDate)+'" data-hw-idx="'+i+'">Д/З</div>';
    }
    return '<div class="lesson lesson-clickable" data-lesson-date="'+esc(S.selectedDate)+'" data-lesson-idx="'+i+'"><div class="lesson-num">'+num+'</div><div class="lesson-body"><div class="lesson-main"><div class="lesson-subj">'+esc(l.subject)+'</div>'+(l.time?'<div class="lesson-time">'+esc(l.time)+(l.room?' · каб. '+esc(l.room):'')+'</div>':'')+hwBlock+'</div><div class="lesson-right">'+(marks?'<div class="lesson-marks">'+marks+'</div>':'')+'</div></div></div>';
  }).join('')+'</div>');
  document.querySelectorAll('.lesson-hw-btn').forEach(btn=>{
    btn.addEventListener('click',e=>{e.stopPropagation();openLessonHomework(btn.dataset.hwDate,+btn.dataset.hwIdx)});
  });
  document.querySelectorAll('.lesson').forEach(card=>{
    card.addEventListener('click',()=>openLessonInfo(card.dataset.lessonDate,+card.dataset.lessonIdx));
  });
  document.querySelectorAll('.lesson-mark-btn').forEach(btn=>{
    btn.addEventListener('click',e=>{e.stopPropagation();openLessonMarkInfo(btn.dataset.markDate,+btn.dataset.markLesson,+btn.dataset.markIdx)});
  });
}

function renderDiary(direction='',resetScroll=false){
  syncDiarySelectionFromDash();
  renderDayStrip();
  renderDayLessons(direction);
  if(resetScroll){
    const diaryPanel=$('p-diary');
    if(diaryPanel)requestAnimationFrame(()=>{diaryPanel.scrollTop=0});
  }
}

attachHorizontalSwipe($('p-diary'),()=>moveDiaryDate(1),()=>moveDiaryDate(-1));

/* Calendar */
function openCalendar(){
  const sel=S.selectedDate?new Date(S.selectedDate+'T00:00:00'):new Date();
  S.calMonth=sel.getMonth();S.calYear=sel.getFullYear();
  renderCalendar();$('calOverlay').classList.add('open');
}
$('calPrev').onclick=()=>{S.calMonth--;if(S.calMonth<0){S.calMonth=11;S.calYear--}renderCalendar()};
$('calNext').onclick=()=>{S.calMonth++;if(S.calMonth>11){S.calMonth=0;S.calYear++}renderCalendar()};

function renderCalendar(){
  txt('calMonth',MON[S.calMonth]+' '+S.calYear);
  const todayIso=isoDate(new Date());
  const first=new Date(S.calYear,S.calMonth,1);
  let sd=first.getDay();if(sd===0)sd=7;sd--;
  const dim=new Date(S.calYear,S.calMonth+1,0).getDate();
  let g='';
  DN.forEach(d=>{g+='<div class="cal-dh">'+d+'</div>'});
  for(let i=0;i<sd;i++)g+='<button class="cal-d empty"></button>';
  for(let d=1;d<=dim;d++){
    const iso=S.calYear+'-'+pad2(S.calMonth+1)+'-'+pad2(d);
    const cls=['cal-d'];
    if(iso===todayIso)cls.push('today');
    if(iso===S.selectedDate)cls.push('sel');
    g+='<button class="'+cls.join(' ')+'" data-iso="'+iso+'">'+d+'</button>';
  }
  html('calGrid',g);
  document.querySelectorAll('#calGrid .cal-d:not(.empty)').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const iso=btn.dataset.iso;S.selectedDate=iso;
      const today=new Date();today.setHours(0,0,0,0);
      const sel=new Date(iso+'T00:00:00');
      const todayMon=getMonday(today),selMon=getMonday(sel);
      S.weekOffset=Math.round((selMon-todayMon)/(7*86400000));
      $('calOverlay').classList.remove('open');renderWeekNav();renderDiary('',true);
    });
  });
}

/* Grades — no "Ср." column, show final grades per quarter */
function renderGrades(){
  if(!S.dash){html('gradesContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');return}
  if(!S.totals)ensureTotalsLoaded();
  const subjects=(S.dash||{}).subjects||[];
  const filters=S.gradeFilters||{};
  const currentQuarterKey=(S.dash||{}).current_quarter_key||'';
  const allCols=(S.dash||{}).quarter_columns||[];
  const qCols=filters.currentQuarter&&currentQuarterKey?allCols.filter(q=>q.key===currentQuarterKey):allCols;
  if(!subjects.length){html('gradesContent','<div class="empty">Оценок пока нет</div>');return}

  const totalsMap=new Map();
  (S.totals||[]).forEach(row=>{
    const name=String((row||{}).subject||'').trim();
    if(!name)return;
    const period=(row&&row.period_marks)||[];
    totalsMap.set(name,period);
  });

  const quarterOrder=(allCols||[]).map(col=>col.key);
  const quarterToIndex={};
  quarterOrder.forEach((k,i)=>{quarterToIndex[k]=i});
  const visibleSubjects=subjects.filter(subject=>{
    if(filters.changedOnly&&!S.delta.changedSubjects.has(subject.subject))return false;
    if(filters.newOnly&&!((subject.items||[]).some(item=>S.delta.newGradeKeys.has(gradeItemKey(item,subject.subject)))))return false;
    return true;
  });
  let t='<div class="grades-toolbar">'
    +'<button class="grade-filter-chip'+(filters.currentQuarter?' active':'')+'" data-grade-filter="currentQuarter">'+esc((S.dash||{}).current_quarter_label||'Текущая четверть')+'</button>'
    +'<button class="grade-filter-chip'+(filters.changedOnly?' active':'')+'" data-grade-filter="changedOnly">С изменениями</button>'
    +'<button class="grade-filter-chip'+(filters.newOnly?' active':'')+'" data-grade-filter="newOnly">Только новые</button>'
    +'</div>';
  if(S.totalsNotice){
    t+='<div class="empty" style="margin-bottom:8px;text-align:left">'+escWithBr(S.totalsNotice)+'</div>';
  }
  if(!visibleSubjects.length){
    html('gradesContent',t+'<div class="empty">По выбранным фильтрам ничего нет</div>');
    document.querySelectorAll('[data-grade-filter]').forEach(btn=>btn.addEventListener('click',()=>toggleGradeFilter(btn.dataset.gradeFilter)));
    return;
  }
  let table='<table class="grades-table"><thead><tr><th>Предмет</th>';
  qCols.forEach(q=>{table+='<th>'+esc(q.label.replace(' четверть','ч.'))+'</th>'});
  table+='</tr></thead><tbody>';
  visibleSubjects.forEach(s=>{
    const si=subjects.findIndex(item=>item.subject===s.subject);
    table+='<tr><td>'+esc(s.subject)+'</td>';
    qCols.forEach(q=>{
      const qd=(s.quarters||{})[q.key]||{};
      let cellContent='—';
      const subjectPeriodMarks=totalsMap.get(String(s.subject||'').trim())||[];
      const periodIdx=quarterToIndex[q.key];
      const totalMark=periodIdx!=null?subjectPeriodMarks[periodIdx]:null;
      const hasQuarterActivity=Number(qd.count||0)>0;
      const canUseOfficialTotals=!S.totalsFallback;
      if(canUseOfficialTotals&&qd.is_past===true&&hasQuarterActivity&&totalMark&&totalMark!=='-'){
        cellContent='<span class="grade-final '+gradeColor(totalMark)+'">'+esc(totalMark)+'</span>';
      } else if(qd.final_grade){
        cellContent='<span class="grade-final '+gradeColor(qd.final_grade)+'">'+esc(qd.final_grade)+'</span>';
      }
      table+='<td class="q-cell" data-si="'+si+'" data-qk="'+esc(q.key)+'">'+cellContent+'</td>';
    });
    table+='</tr>';
  });
  table+='</tbody></table><div style="height:8px"></div>';
  html('gradesContent',t+table);
  document.querySelectorAll('[data-grade-filter]').forEach(btn=>btn.addEventListener('click',()=>toggleGradeFilter(btn.dataset.gradeFilter)));
  document.querySelectorAll('.q-cell').forEach(td=>{td.addEventListener('click',()=>openSubjQ(+td.dataset.si,td.dataset.qk))});
}

function toggleGradeFilter(key){
  S.gradeFilters[key]=!S.gradeFilters[key];
  renderGrades();
}

function makeCalcQuarterCounts(){return {q1:{5:0,4:0,3:0,2:0},q2:{5:0,4:0,3:0,2:0},q3:{5:0,4:0,3:0,2:0},q4:{5:0,4:0,3:0,2:0}}}
function getCalcWeightValue(value){
  const numeric=Number(value);
  return Number.isFinite(numeric)&&numeric>0?numeric:0;
}
function subjectCalcQuarterCounts(subjectName){
  const counts=makeCalcQuarterCounts();
  const subjects=(S.dash||{}).subjects||[];
  const subject=subjects.find(item=>item.subject===subjectName);
  (subject&&subject.items||[]).forEach(item=>{
    const quarter=item.quarter||'';
    const mark=parseInt(item.mark,10);
    const weight=getCalcWeightValue(item.weight||1)||1;
    if(counts[quarter]&&counts[quarter][mark]!=null)counts[quarter][mark]+=weight;
  });
  return counts;
}

function ensureCalcCounts(force=false){
  if(!S.calcQuarterCounts)S.calcQuarterCounts=makeCalcQuarterCounts();
  if(force||S.calcCountsLoadedFor!==S.calcSubject){
    S.calcQuarterCounts=S.calcSubject==='__custom__'?makeCalcQuarterCounts():subjectCalcQuarterCounts(S.calcSubject);
    S.calcCountsLoadedFor=S.calcSubject;
    const currentQuarterKey=(S.dash||{}).current_quarter_key||'q1';
    if(S.calcQuarterCounts[currentQuarterKey])S.calcQuarter=currentQuarterKey;
  }
}

function calcAverage(counts){
  const data=counts||{5:0,4:0,3:0,2:0};
  const total=(data[5]||0)+(data[4]||0)+(data[3]||0)+(data[2]||0);
  if(!total)return {count:0,average:0};
  const sum=(data[5]||0)*5+(data[4]||0)*4+(data[3]||0)*3+(data[2]||0)*2;
  return {count:total,average:sum/total};
}

function calcQuarterSummary(){
  const total={5:0,4:0,3:0,2:0};
  Object.values(S.calcQuarterCounts||makeCalcQuarterCounts()).forEach(counts=>CALC_MARKS.forEach(mark=>{total[mark]+=counts[mark]||0}));
  return calcAverage(total);
}

function setCalcCount(quarter,mark,value){
  if(!S.calcQuarterCounts)S.calcQuarterCounts=makeCalcQuarterCounts();
  if(!S.calcQuarterCounts[quarter])S.calcQuarterCounts[quarter]={5:0,4:0,3:0,2:0};
  S.calcQuarterCounts[quarter][mark]=getCalcWeightValue(value);
}

function renderCalcQuarterCard(quarterKey,label){
  const counts=(S.calcQuarterCounts&&S.calcQuarterCounts[quarterKey])||{5:0,4:0,3:0,2:0};
  const stats=calcAverage(counts);
  return '<div class="calc-quarter-card"><div class="calc-quarter-title">'+esc(label)+'</div><div class="calc-grade-list">'+CALC_MARKS.map(mark=>'<div class="calc-grade-row" data-quarter="'+quarterKey+'" data-mark="'+mark+'"><div><div class="calc-grade-label">'+CALC_LABELS[mark]+' <span class="calc-grade-number">'+mark+'</span></div><div class="calc-row-note">Сумма коэффициентов</div></div><input class="calc-input" data-role="count" inputmode="decimal" value="'+esc(counts[mark]||0)+'"><button class="calc-mini-btn" data-role="plus">+</button><button class="calc-mini-btn" data-role="minus">−</button><button class="calc-mini-btn danger" data-role="clear">✕</button></div>').join('')+'</div><div class="calc-help">Средний балл: <strong>'+(stats.count?stats.average.toFixed(2):'—')+'</strong> · суммарный вес: '+stats.count+'</div></div>';
}

function renderCalc(){
  if(!S.dash){html('calcContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');return}
  const subjects=((S.dash||{}).subjects||[]).map(item=>item.subject);
  const quarterColumns=(S.dash||{}).quarter_columns||[{key:'q1',label:'1 четверть'},{key:'q2',label:'2 четверть'},{key:'q3',label:'3 четверть'},{key:'q4',label:'4 четверть'}];
  if(!S.calcSubject)S.calcSubject=subjects[0]||'__custom__';
  ensureCalcCounts();
  if(!quarterColumns.find(item=>item.key===S.calcQuarter))S.calcQuarter=quarterColumns[0]&&quarterColumns[0].key||'q1';
  const totalStats=calcQuarterSummary();
  const selectedQuarter=quarterColumns.find(item=>item.key===S.calcQuarter)||quarterColumns[0]||{key:'q1',label:'1 четверть'};
  const selectedStats=calcAverage((S.calcQuarterCounts||{})[selectedQuarter.key]||{});
  let out='<div class="calc-card"><div class="calc-title">Калькулятор оценок</div><select class="calc-select" id="calcSubjectSelect"><option value="__custom__"'+(S.calcSubject==='__custom__'?' selected':'')+'>С нуля</option>'+subjects.map(subject=>'<option value="'+esc(subject)+'"'+(S.calcSubject===subject?' selected':'')+'>'+esc(subject)+'</option>').join('')+'</select><div class="calc-quarter-row"><label style="font-size:12px;color:var(--text2);font-weight:700">Четверть</label><select class="calc-select" id="calcQuarterSelect">'+quarterColumns.map(q=>'<option value="'+esc(q.key)+'"'+(S.calcQuarter===q.key?' selected':'')+'>'+esc(q.label)+'</option>').join('')+'</select></div>'+renderCalcQuarterCard(selectedQuarter.key,selectedQuarter.label)+'<div class="calc-summary"><div class="calc-summary-card"><div class="calc-metric-label">Средний балл</div><div class="calc-metric-value">'+(selectedStats.count?selectedStats.average.toFixed(2):'—')+'</div><div class="calc-metric-sub">'+esc(selectedQuarter.label)+'</div></div><div class="calc-summary-card"><div class="calc-metric-label">Сумма весов</div><div class="calc-metric-value">'+totalStats.count+'</div><div class="calc-metric-sub">По всем четвертям</div></div></div><div class="calc-help">Для предметов из дневника коэффициенты уже учтены автоматически. Если оценка стоит с весом x2, в калькулятор попадут две единицы веса.</div></div>';
  html('calcContent',out);
  const subjectSelect=$('calcSubjectSelect');
  if(subjectSelect)subjectSelect.addEventListener('change',()=>{S.calcSubject=subjectSelect.value;ensureCalcCounts(true);renderCalc()});
  const quarterSelect=$('calcQuarterSelect');
  if(quarterSelect)quarterSelect.addEventListener('change',()=>{S.calcQuarter=quarterSelect.value;renderCalc()});
  document.querySelectorAll('.calc-grade-row').forEach(row=>{
    const quarter=row.dataset.quarter;
    const mark=+row.dataset.mark;
    row.querySelector('[data-role="count"]').addEventListener('change',e=>{setCalcCount(quarter,mark,e.target.value);renderCalc()});
    row.querySelector('[data-role="plus"]').addEventListener('click',()=>{setCalcCount(quarter,mark,(((S.calcQuarterCounts||{})[quarter]||{})[mark]||0)+1);renderCalc()});
    row.querySelector('[data-role="minus"]').addEventListener('click',()=>{setCalcCount(quarter,mark,(((S.calcQuarterCounts||{})[quarter]||{})[mark]||0)-1);renderCalc()});
    row.querySelector('[data-role="clear"]').addEventListener('click',()=>{setCalcCount(quarter,mark,0);renderCalc()});
  });
}

function openSubjQ(si,qKey){
  const s=((S.dash||{}).subjects||[])[si];if(!s)return;
  const qCols=(S.dash||{}).quarter_columns||[];
  const qMeta=qCols.find(q=>q.key===qKey);
  const qLabel=qMeta?qMeta.label:'';
  const qData=(s.quarters||{})[qKey]||{};
  const items=(s.items||[]).filter(r=>r.quarter===qKey).slice().sort((a,b)=>String(a.date_sort||a.date).localeCompare(String(b.date_sort||b.date)));
  txt('sheetSubjTitle',s.subject+(qLabel?' — '+qLabel:''));
  let body='';
  if(qData.final_grade){
    body+='<div style="margin-bottom:12px;font-size:15px">Итоговая оценка: <span class="grade-final '+gradeColor(qData.final_grade)+'" style="font-size:18px">'+esc(qData.final_grade)+'</span></div>';
  }
  if(qData.average!=null){
    body+='<div style="margin-bottom:14px;font-size:14px;color:var(--text2)">Средний балл: '+esc(qData.display)+' · Оценок: '+qData.count+'</div>';
  } else if(!items.length){
    body+='<div style="margin-bottom:12px;font-size:14px;color:var(--text2)">Нет оценок за '+esc(qLabel)+'</div>';
  }
  if(items.length){
    body+='<table style="width:100%;border-collapse:collapse;font-size:13px"><thead><tr style="border-bottom:2px solid var(--border)"><th style="text-align:left;padding:8px 4px;font-weight:600">Дата</th><th style="text-align:left;padding:8px 4px;font-weight:600">Задание</th><th style="text-align:center;padding:8px 4px;font-weight:600">Оценка</th><th style="text-align:center;padding:8px 4px;font-weight:600">Вес</th></tr></thead><tbody>';
    items.forEach(r=>{
      body+='<tr style="border-bottom:1px solid var(--border)"><td style="padding:8px 4px;white-space:nowrap;color:var(--text2)">'+esc(r.date_label||r.date)+'</td><td style="padding:8px 4px">'+esc(r.title)+'</td><td style="text-align:center;padding:8px 4px"><span class="mark '+markCls(r.mark)+'" style="min-width:24px;height:24px;font-size:13px">'+esc(r.mark)+'</span></td><td style="text-align:center;padding:8px 4px;color:var(--text2)">'+esc(r.weight)+'</td></tr>';
    });
    body+='</tbody></table>';
  }
  html('sheetSubjBody',body);
  $('subjectOverlay').classList.add('open');
}

/* Homework — day-by-day navigation */
S.hwDates=[];
S.hwDateIdx=0;
S.hwByDate={};

function buildHwIndex(){
  const allDays=(S.dash||{}).diary_days||[];
  const map={};
  allDays.forEach(day=>{(day.lessons||[]).forEach(l=>{
    if(l.has_homework||l.homework||(l.hw_attachments||[]).length){
      (map[day.date]=map[day.date]||[]).push({subject:l.subject,text:l.homework,atts:l.hw_attachments||[],details:l.hw_details||[],time:l.time||'',room:l.room||'',date:day.display_date||day.date,weekday:day.weekday||'',source_idx:l.source_index});
    }
  })});
  const bk=(S.dash||{}).homework||[];
  bk.forEach(h=>{
    const key=h.sort_date||h.date;
    const arr=map[key]||[];
    if(!arr.find(i=>i.subject===h.subject&&i.text===h.text)){
      (map[key]=map[key]||[]).push({subject:h.subject,text:h.text,atts:h.attachments||[],details:h.hw_details||[],time:h.time||'',room:h.room||'',date:h.date,weekday:h.weekday||'',source_idx:typeof h.lesson_number==='number'?h.lesson_number-1:null});
    }
  });
  S.hwByDate=map;
  S.hwDates=Object.keys(map).sort();
  const todayIso=isoDate(new Date());
  let idx=S.hwDates.findIndex(d=>d>=todayIso);
  if(idx<0)idx=S.hwDates.length-1;
  if(idx<0)idx=0;
  S.hwDateIdx=idx;
}

function renderHwNav(){
  if(!S.hwDates.length){txt('hwDateLabel','Нет заданий');return}
  const iso=S.hwDates[S.hwDateIdx];
  const dt=new Date(iso+'T00:00:00');
  const wd=dt.getDay();
  const wdName=DNF[wd===0?6:wd-1];
  txt('hwDateLabel',wdName+', '+dt.getDate()+' '+MO[dt.getMonth()]);
}

function renderHwDay(){
  if(!S.hwDates.length){html('hwContent','<div class="empty">Домашних заданий нет</div>');return}
  const iso=S.hwDates[S.hwDateIdx];
  const items=S.hwByDate[iso]||[];
  if(!items.length){html('hwContent','<div class="empty">Нет заданий на этот день</div>');return}
  let out='<div class="hw-list">';
  items.forEach((h,idx)=>{
    const preview=h.text?esc(h.text.length>80?h.text.slice(0,80)+'…':h.text):(h.unspecified?'<span style="color:var(--text2)">Не указана</span>':'<span style="color:var(--primary)">Прикреплены файлы</span>');
    out+='<div class="hw-item" data-hwi="'+idx+'"><div class="hw-subj">'+esc(h.subject)+'</div><div class="hw-text">'+preview+'</div><div style="margin-top:4px;font-size:12px;color:var(--primary)">Подробнее →</div></div>';
  });
  out+='</div>';
  html('hwContent',out);
  document.querySelectorAll('[data-hwi]').forEach(el=>el.addEventListener('click',()=>openHwDetail(S.hwDates[S.hwDateIdx],+el.dataset.hwi)));
}

function hwAllAttachments(item){
  const result=[];
  const seen=new Set();
  const pushAtt=att=>{const key=String(att.id||'');if(key&&seen.has(key))return;if(key)seen.add(key);result.push(att)};
  (item.atts||[]).forEach(pushAtt);
  (item.details||[]).forEach(detail=>(detail.attachments||[]).forEach(pushAtt));
  return result;
}

function buildHwBody(item){
  if(!item)return '<div class="empty">Задание не найдено</div>';
  const attachments=hwAllAttachments(item);
  const detailAttachmentIds=new Set();
  let body='<div style="font-size:13px;color:var(--text2);margin-bottom:12px">'+esc(item.weekday||'')+(item.date?', '+esc(item.date):'')+(item.time?' · '+esc(item.time):'')+(item.room?' · каб. '+esc(item.room):'')+'</div>';
  if(item.details&&item.details.length){
    item.details.forEach(detail=>{
      if(detail.kind)body+='<div style="font-size:12px;font-weight:700;color:var(--primary);margin-bottom:4px">'+esc(detail.kind)+'</div>';
      if(detail.text)body+='<div style="white-space:pre-wrap;line-height:1.6;font-size:14px;margin-bottom:10px">'+linkifyText(detail.text)+'</div>';
      if(detail.attachments&&detail.attachments.length){
        detail.attachments.forEach(att=>detailAttachmentIds.add(String(att.id||'')));
        body+='<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">'+detail.attachments.map(a=>attachmentLink('/api/mini/netschool/attachments/'+a.id+'?name='+encodeURIComponent(a.name),a.name)).join('')+'</div>';
      }
    });
  } else if(item.text){
    body+='<div style="white-space:pre-wrap;line-height:1.6;font-size:14px;margin-bottom:10px">'+linkifyText(item.text)+'</div>';
  } else if(item.unspecified){
    body+='<div style="white-space:pre-wrap;line-height:1.6;font-size:14px;margin-bottom:10px;color:var(--text2)">Не указана</div>';
  }
  if(!item.text&&!(item.details||[]).length&&!attachments.length){
    body+='<div class="empty" style="min-height:0;padding:8px 0 0">Подробности по заданию пока не загрузились</div>';
  }
  const extraAttachments=attachments.filter(att=>!detailAttachmentIds.has(String(att.id||'')));
  if(extraAttachments.length){
    body+='<div style="display:flex;flex-wrap:wrap;gap:6px">'+extraAttachments.map(a=>attachmentLink('/api/mini/netschool/attachments/'+a.id+'?name='+encodeURIComponent(a.name),a.name)).join('')+'</div>';
  }
  return body;
}

async function loadHwDetailLive(dateKey,idx){
  const item=((S.hwByDate||{})[dateKey]||[])[idx];
  if(!item||item.source_idx==null)return;
  const requestKey=[dateKey,idx,item.source_idx].join('|');
  S.activeHwKey=requestKey;
  try{
    const detail=await api('/api/mini/netschool/homework-detail?date='+encodeURIComponent(dateKey)+'&lesson='+encodeURIComponent(item.source_idx));
    const target=((S.hwByDate||{})[dateKey]||[])[idx];
    if(!target)return;
    target.text=detail.text||target.text||'';
    target.details=detail.details||target.details||[];
    target.atts=detail.attachments||target.atts||[];
    target.time=detail.time||target.time||'';
    target.room=detail.room||target.room||'';
    target.date=detail.date||target.date||dateKey;
    target.weekday=detail.weekday||target.weekday||'';
    if(S.activeHwKey===requestKey&&$('hwDetailOverlay').classList.contains('open'))html('sheetHwBody',buildHwBody(target));
  }catch(e){
    const target=((S.hwByDate||{})[dateKey]||[])[idx];
    if(target&&S.activeHwKey===requestKey&&$('hwDetailOverlay').classList.contains('open'))html('sheetHwBody',buildHwBody(target)+'<div class="hw-load-note">Не удалось обновить задание с сервера. Показана сохраненная версия.</div>');
  }
}

async function refreshPushStatus(){
  const helpEl=$('pushHelpNote');
  const testBtn=$('pushTestBtn');
  const enableBtn=$('pushEnableBtn');
  if(!helpEl)return;
  const d=S.profileData||{};
  const supportsPush=('serviceWorker' in navigator)&&('PushManager' in window)&&('Notification' in window);
  let localSub=false;
  try{
    const reg=await ensurePushRegistration();
    const sub=reg&&reg.pushManager?await reg.pushManager.getSubscription():null;
    localSub=!!sub;
  }catch(e){}
  if(!d.push_configured){
    helpEl.textContent='Сервер web push ещё не настроен.';
    if(enableBtn){enableBtn.disabled=true;enableBtn.textContent='Push недоступен'}
  }else if(isAppleMobile()&&!isStandalonePwa()){
    helpEl.textContent='На iPhone push включаются автоматически только из установленного PWA, запущенного с домашнего экрана.';
    if(enableBtn){enableBtn.disabled=false;enableBtn.textContent='Включить в PWA'}
  }else if(localSub){
    helpEl.textContent='Push уже активен на этом устройстве. Можно отправить тестовое уведомление.';
    if(enableBtn){enableBtn.disabled=true;enableBtn.textContent='Уведомления включены'}
  }else {
    helpEl.textContent='Нажмите кнопку ниже, чтобы запросить разрешение и включить уведомления на этом устройстве.';
    if(enableBtn){enableBtn.disabled=!supportsPush;enableBtn.textContent='Включить уведомления'}
  }
  if(!supportsPush&&enableBtn){enableBtn.disabled=true;enableBtn.textContent='Push не поддерживается'}
  if(testBtn)testBtn.disabled=!localSub||!d.push_configured;
}

async function ensurePushRegistration(){
  if(!('serviceWorker' in navigator))return null;
  try{
    const existing=await navigator.serviceWorker.getRegistration('/mini/');
    if(existing)return existing;
  }catch(e){}
  return navigator.serviceWorker.register('/mini/netschool/sw.js',{scope:'/mini/'});
}

async function enableAppPush(btn){
  const d=S.profileData||{};
  const silent=!!(btn&&btn.dataset&&btn.dataset.silent==='1');
  if(!d.push_public_key){alert('Сервер push не настроен');return}
  if(isAppleMobile()&&!isStandalonePwa()){
    if(!silent)alert('Откройте установленное приложение с домашнего экрана и включите push уже там.');
    return;
  }
  try{
    btn.textContent='Подключение...';
    const reg=await ensurePushRegistration();
    if(!reg)throw new Error('Service Worker недоступен');
    const permission=await Notification.requestPermission();
    if(permission!=='granted')throw new Error('Разрешение на уведомления не выдано');
    let sub=await reg.pushManager.getSubscription();
    if(!sub){
      sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(d.push_public_key)});
    }
    const res=await postApi('/api/mini/netschool/push/subscribe',{subscription:sub.toJSON(),userAgent:navigator.userAgent||''});
    if(res.profile)S.profileData=res.profile;
    if(!(btn&&btn.dataset&&btn.dataset.skipTest==='1'))await postApi('/api/mini/netschool/push/test',{ endpoint: sub.endpoint }).catch(()=>null);
    renderProfile();
  }catch(e){if(!silent)alert(e.message||'Не удалось включить push')}finally{btn.textContent='Включить push'}
}

async function disableAppPush(btn){
  try{
    btn.textContent='Отключение...';
    const reg=await ensurePushRegistration();
    const sub=reg&&reg.pushManager?await reg.pushManager.getSubscription():null;
    if(sub){
      const endpoint=sub.endpoint;
      await sub.unsubscribe().catch(()=>{});
      const res=await postApi('/api/mini/netschool/push/unsubscribe',{endpoint});
      if(res.profile)S.profileData=res.profile;
    }
    renderProfile();
  }catch(e){alert(e.message||'Не удалось отключить push')}finally{btn.textContent='Отключить push'}
}

async function testPushNotification(btn){
  try{
    btn.textContent='Отправка...';
    const reg=await ensurePushRegistration();
    const sub=reg&&reg.pushManager?await reg.pushManager.getSubscription():null;
    const endpoint = sub ? sub.endpoint : null;
    const res=await postApi('/api/mini/netschool/push/test',{endpoint});
    if(res.profile)S.profileData=res.profile;
    alert(res.message||'Тестовый push отправлен');
    renderProfile();
  }catch(e){alert(e.message||'Не удалось отправить тест')}finally{btn.textContent='Тест push'}
}

function openHwDetail(dateKey,idx){
  const items=S.hwByDate[dateKey]||[];
  const h=items[idx];if(!h)return;
  txt('sheetHwTitle',h.subject);
  html('sheetHwBody',buildHwBody(h));
  $('hwDetailOverlay').classList.add('open');
  loadHwDetailLive(dateKey,idx);
}

function renderHomework(){
  if(!S.dash){html('hwContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');return}
  buildHwIndex();
  renderHwNav();
  renderHwDay();
}

$('hwPrev').onclick=()=>{if(S.hwDateIdx>0){S.hwDateIdx--;renderHwNav();renderHwDay()}};
$('hwNext').onclick=()=>{if(S.hwDateIdx<S.hwDates.length-1){S.hwDateIdx++;renderHwNav();renderHwDay()}};



attachHorizontalSwipe($('p-homework'),()=>{if(S.hwDateIdx<S.hwDates.length-1){S.hwDateIdx++;renderHwNav();renderHwDay()}},()=>{if(S.hwDateIdx>0){S.hwDateIdx--;renderHwNav();renderHwDay()}});

function attachSwipeDownToClose(overlayId){
  const overlay=$(overlayId);if(!overlay)return;
  const sheet=overlay.querySelector('.sheet');const sheetBody=overlay.querySelector('.sheet-body');if(!sheet||!sheetBody)return;
  let active=false,startY=0,startX=0;
  sheet.addEventListener('touchstart',e=>{
    if(!overlay.classList.contains('open'))return;
    if(e.target.closest('.sheet-body')&&sheetBody.scrollTop>4)return;
    active=true;startY=e.touches[0].clientY;startX=e.touches[0].clientX;
    sheet.style.transition='';overlay.style.transition='';
  },{passive:true});
  sheet.addEventListener('touchmove',e=>{
    if(!active)return;
    const dy=e.touches[0].clientY-startY;
    const dx=e.touches[0].clientX-startX;
    if(dy<=0||dy<Math.abs(dx))return;
    if(dy>12)e.preventDefault();
    const shift=Math.min(dy,180);
    sheet.style.transform='translateY('+shift+'px)';
    overlay.style.background='rgba(0,0,0,'+Math.max(0.12,0.45-shift/420)+')';
  },{passive:false});
  sheet.addEventListener('touchend',e=>{
    if(!active)return;
    active=false;
    const dy=e.changedTouches[0].clientY-startY;
    const dx=e.changedTouches[0].clientX-startX;
    sheet.style.transition='transform .18s ease';overlay.style.transition='background .18s ease';
    if(dy>90&&dy>Math.abs(dx)*1.2){closeOv(overlayId)}
    sheet.style.transform='';overlay.style.background='';
    setTimeout(()=>{sheet.style.transition='';overlay.style.transition=''},220);
  },{passive:true});
}
attachSwipeDownToClose('hwDetailOverlay');

/* Mail */

function ensureTotalsLoaded(){
  api('/api/mini/netschool/totals?ts='+Date.now()).then(data=>{
    S.totals=data.totals;
    S.totalsNotice=data.notice||'';
    S.totalsFallback=!!data.fallback;
    if(S.currentTab==='grades')renderGrades();
  }).catch(e=>{
    S.totals=[];
    S.totalsFallback=true;
    S.totalsNotice=e&&e.message?e.message:'Не удалось загрузить итоговые оценки';
    if(S.currentTab==='grades')renderGrades();
  });
}

function renderMailList(){
  if(!S.mail){html('mailContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');return}
  const entries=(S.mail||{}).entries||[];
  if(!entries.length){html('mailContent','<div class="empty">Входящих писем нет</div>');return}
  html('mailContent','<div class="mail-list">'+entries.map(m=>
    '<div class="mail-item'+(m.unread?' unread':'')+'" data-mid="'+m.id+'"><div class="mail-dot"></div><div class="mail-info"><div class="mail-from">'+esc(m.author)+'</div><div class="mail-subj">'+esc(m.subject)+'</div><div class="mail-date">'+esc(m.sent)+'</div></div></div>'
  ).join('')+'</div><div class="mail-actions"><button class="mail-more-btn" id="mailReadAllBtn">Прочитать все письма</button>'+((S.mail||{}).has_more?'<button class="mail-more-btn" id="mailMoreBtn">Показать еще письма</button>':'')+'</div>');
  document.querySelectorAll('[data-mid]').forEach(el=>el.addEventListener('click',()=>openMail(el.dataset.mid)));
  const moreBtn=$('mailMoreBtn');
  if(moreBtn)moreBtn.addEventListener('click',()=>loadMailPage(((S.mail||{}).page||1)+1,true));
  const readAllBtn=$('mailReadAllBtn');
  if(readAllBtn)readAllBtn.addEventListener('click',markAllMailRead);
}

async function markAllMailRead(){
  const ids=((S.mail||{}).entries||[]).map(item=>item.id);
  try{
    await postApi('/api/mini/netschool/mail/read-all',{ids});
    ((S.mail||{}).entries||[]).forEach(item=>{item.unread=false});
    S.delta.unreadMailCount=0;
    if(S.profileData)S.profileData.mail_unread_count=0;
    updateNavBadges();
    try{localStorage.setItem('ns-cache-mail',JSON.stringify(S.mail))}catch(e){}
    renderMailList();
  }catch(e){alert(e.message||'Не удалось отметить письма прочитанными')}
}

async function loadMailPage(page=1,append=false){
  if(S.isMailLoading)return;
  S.isMailLoading=true;
  setTopLoading(page>1?'Подгружаем письма':'Обновляем почту',true);
  if(!append&&(!S.mail||!(S.mail.entries||[]).length))html('mailContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');
  try{
    const payload=await api('/api/mini/netschool/mail?page='+page+'&page_size=20');
    if(append&&S.mail){
      const existing=new Set((S.mail.entries||[]).map(item=>String(item.id)));
      S.mail={...payload,entries:[...(S.mail.entries||[]),...(payload.entries||[]).filter(item=>!existing.has(String(item.id)))]};
    }else{
      S.mail=payload;
    }
    S.delta.unreadMailCount=(payload.unread_count??((S.mail.entries||[]).filter(item=>item.unread).length))||0;
    if(S.profileData)S.profileData.mail_unread_count=S.delta.unreadMailCount;
    updateNavBadges();
    try{localStorage.setItem('ns-cache-mail',JSON.stringify(S.mail))}catch(e){}
    if(S.currentTab==='mail')renderMailList();
  }catch(e){
    if(!S.mail)html('mailContent','<div class="empty">'+esc(e.message||'Ошибка загрузки почты')+'<br><button class="retry-btn" onclick="ensureMailLoaded(true)">Повторить</button></div>');
  }finally{S.isMailLoading=false;setTopLoading('',false)}
}

function ensureMailLoaded(force=false){
  if(force||!S.mail)return loadMailPage(1,false);
  renderMailList();
  return Promise.resolve();
}

async function openMail(id){
  txt('sheetMailTitle','Загрузка…');
  html('sheetMailBody','<div class="loader"><span class="spin"></span></div>');
  $('mailOverlay').classList.add('open');
  setTopLoading('Открываем письмо',true);
  try{
    const msg=await api('/api/mini/netschool/mail/'+encodeURIComponent(id));
    /* Mark as read in UI */
    const entries=(S.mail||{}).entries||[];
    const entry=entries.find(e=>String(e.id)===String(id));
    if(entry&&entry.unread){entry.unread=false;S.delta.unreadMailCount=Math.max(0,(S.delta.unreadMailCount||0)-1);if(S.profileData)S.profileData.mail_unread_count=S.delta.unreadMailCount;updateNavBadges();try{localStorage.setItem('ns-cache-mail',JSON.stringify(S.mail))}catch(e){}renderMailList()}
    txt('sheetMailTitle',msg.subject||'(без темы)');
    let atts='';
    if((msg.attachments||[]).length){
      atts='<div style="margin-top:14px;display:flex;flex-wrap:wrap;gap:8px">'+msg.attachments.map(a=>
        attachmentLink('/api/mini/netschool/mail/'+msg.id+'/attachments/'+a.id+'?name='+encodeURIComponent(a.name),a.name)
      ).join('')+'</div>';
    }
    html('sheetMailBody','<div style="font-size:13px;color:var(--text2);margin-bottom:12px"><div>От: '+esc(msg.author)+'</div><div>Кому: '+esc(msg.to_names)+'</div><div>'+esc(msg.sent)+'</div></div><div style="white-space:pre-wrap;line-height:1.6;font-size:14px">'+linkifyText(msg.body)+'</div>'+atts);
  }catch(e){html('sheetMailBody','<div class="empty">'+esc(e.message)+'</div>')}
  finally{setTopLoading('',false)}
}

/* Profile */
function renderProfile(){
  const d=S.profileData||{};
  const iconBg=d.pwa_icon_bg||'#4a76a8';
  const iconEmoji=d.pwa_icon_emoji||'📘';
  const iconUrl=d.pwa_icon_url||'';
  const iconPreview=d.pwa_icon_has_image&&iconUrl?'<img src="'+esc(iconUrl)+'" alt="Иконка">':esc(iconEmoji);
  let childSwitcher = '';
  if (S.dashData && S.dashData.students && S.dashData.students.length > 1) {
    childSwitcher = '<div class="profile-card"><div style="font-weight:600;font-size:14px;margin-bottom:8px">Сменить ученика</div><select id="studentSwitchSelect" style="border:1px solid var(--line);border-radius:12px;padding:8px 12px;background:var(--card);color:var(--text);font:inherit;width:100%;margin-bottom:8px">' + 
      S.dashData.students.map(s => '<option value="' + esc(s.id) + '"' + (s.name===d.student_name ? ' selected' : '') + '>' + esc(s.name) + '</option>').join('') + 
      '</select><button class="retry-btn" id="studentSwitchBtn" style="margin-top:0;padding:8px 16px;font-size:12px">Переключить</button></div>';
  }
  html('profileContent',
    '<div class="profile-card"><div class="profile-name">'+esc(d.student_name)+'</div><div class="profile-school">'+esc(d.school)+'</div><div style="font-size:12px;color:var(--text2);margin-top:8px">Синхронизация: '+esc(d.last_sync_at)+'</div></div>'+
    childSwitcher +
    '<div class="profile-card">'+
      '<div class="setting-row"><div class="setting-info"><span class="setting-label">Оценки</span><span class="setting-desc">Уведомления о новых оценках</span></div><button class="toggle '+(d.enabled_class==='ok'?'on':'')+'" data-key="enabled"></button></div>'+
      '<div class="setting-row"><div class="setting-info"><span class="setting-label">Почта</span><span class="setting-desc">Уведомления о входящих письмах</span></div><button class="toggle '+(d.mail_class==='ok'?'on':'')+'" data-key="mail"></button></div>'+
      '<div class="setting-row"><div class="setting-info"><span class="setting-label">Изменения</span><span class="setting-desc">Уведомления об изменении оценок</span></div><button class="toggle '+(d.changes_class==='ok'?'on':'')+'" data-key="changes"></button></div>'+
      '<div class="setting-row"><div class="setting-info"><span class="setting-label">Удаления</span><span class="setting-desc">Уведомления об удалении оценок</span></div><button class="toggle '+(d.deletes_class==='ok'?'on':'')+'" data-key="deletes"></button></div>'+
      '<div class="setting-row"><div class="setting-info"><span class="setting-label">Сводка</span><span class="setting-desc">Еженедельный отчёт по оценкам</span></div><button class="toggle '+(d.weekly_class==='ok'?'on':'')+'" data-key="weekly"></button></div>'+
      '<div class="setting-row"><div class="setting-info"><span class="setting-label">Домашние задания</span><span class="setting-desc">Уведомления о новых ДЗ</span></div><button class="toggle '+(d.homework_class==='ok'?'on':'')+'" data-key="homework"></button></div>'+
    '</div>'+
    '<div class="profile-card"><div class="setting-row"><span class="setting-label">Тёмная тема</span><button class="toggle '+(S.theme==='dark'?'on':'')+'" id="themeToggle"></button></div><div style="margin-top:12px;font-weight:600;font-size:14px;margin-bottom:8px">Палитра</div><div class="palette-row"><span class="palette-label">Акцентный цвет</span><input type="color" class="palette-swatch" id="accentPicker" value="'+(S.accentColor||'#4a76a8')+'"><button class="palette-reset" id="accentReset">Сбросить</button></div><label style="display:flex;align-items:center;gap:8px;margin-top:10px;font-size:13px;color:var(--text2)"><input type="checkbox" id="syncThemeAllDevices" '+(d.theme_sync!==false?'checked':'')+'>Синхронизировать оформление на всех устройствах</label></div>'+
    '<div class="profile-card"><div style="font-weight:600;font-size:14px;margin-bottom:8px">Уведомления PWA</div><div class="setting-row"><div class="setting-info"><span class="setting-label">Канал доставки</span><span class="setting-desc">Push можно включить вручную на этом устройстве. Отключение выполняется через системные настройки устройства.</span></div><label style="display:block"><select id="pushModeSelect" style="border:1px solid var(--line);border-radius:12px;padding:8px 12px;background:var(--card);color:var(--text);font:inherit"><option value="telegram"'+(d.push_mode==='telegram'?' selected':'')+'>Только Telegram</option><option value="app"'+(d.push_mode==='app'?' selected':'')+'>Только приложение</option><option value="both"'+(d.push_mode==='both'?' selected':'')+'>Приложение и Telegram</option></select></label></div><div class="pwa-link-actions"><button class="retry-btn" id="pushEnableBtn" style="margin-top:0;padding:8px 16px;font-size:12px">Включить уведомления</button><button class="retry-btn" id="pushTestBtn" style="margin-top:0;padding:8px 16px;font-size:12px">Тест push</button></div><div class="pwa-link-note" id="pushHelpNote">После установки PWA подписка создается автоматически на этом устройстве.</div></div>'+
    '<div class="profile-card" style="font-size:13px;color:var(--text2)"><div>Логин: '+esc(d.login)+'</div><div>Интервал: '+esc(d.interval_label)+'</div><div>Тихие часы: '+esc(d.quiet_hours)+'</div></div>'+
    '<div class="profile-card"><div style="font-weight:600;font-size:14px;margin-bottom:8px">PWA и иконки</div><div class="pwa-link-note" style="margin-bottom:10px">Установка на iPhone и Android вынесена в отдельную инструкцию. Общая галерея иконок открывается отдельной страницей.</div><div class="pwa-link-actions"><button class="retry-btn" type="button" id="openInstallGuideBtn" style="margin-top:0;padding:8px 16px;font-size:12px">Как установить PWA</button><button class="retry-btn" type="button" id="openGalleryBtn" style="margin-top:0;padding:8px 16px;font-size:12px">Галерея иконок</button></div></div>'+
    '<div class="profile-card"><div style="font-weight:600;font-size:14px;margin-bottom:10px">Иконка PWA</div><div class="pwa-icon-current"><div class="pwa-icon-preview" style="background:'+esc(iconBg)+'">'+iconPreview+'</div><div class="pwa-icon-current-meta"><div class="pwa-icon-current-title">Текущая иконка</div><div class="pwa-icon-current-sub">'+esc(describeCurrentPwaIcon(d))+'</div></div></div><div class="pwa-icon-row" style="margin-top:12px"><div class="pwa-icon-preview" id="pwaIconPreview" style="background:'+esc(iconBg)+'">'+iconPreview+'</div><div class="pwa-icon-controls"><div class="pwa-icon-customize"><input class="feedback-field" id="pwaIconEmoji" maxlength="2" placeholder="Эмодзи" value="'+esc(iconEmoji)+'"><input class="pwa-icon-color" id="pwaIconBg" type="color" value="'+esc(iconBg)+'"></div><input class="pwa-icon-file" id="pwaIconFile" type="file" accept="image/*"><div class="pwa-icon-hint" id="pwaIconFileHint">Можно загрузить свою картинку. Она будет приведена к квадратной PNG-иконке.</div><label style="display:flex;align-items:center;gap:8px;margin:8px 0;font-size:13px;color:var(--text2)"><input type="checkbox" id="pwaIconPublic" checked> Добавить в галерею иконок</label><div class="pwa-icon-actions"><button class="retry-btn" type="button" id="pwaIconSaveBtn" style="margin-top:0;padding:8px 16px;font-size:12px">Сохранить иконку</button><button class="mail-more-btn" type="button" id="pwaIconResetBtn">Сбросить</button></div><div id="pwaIconLinkBox"></div></div></div><div class="pwa-link-note">После сохранения отдельная ссылка для иконки появится прямо здесь.</div></div>'+
    '<div class="profile-card"><div style="font-weight:600;font-size:14px;margin-bottom:8px">Обратная связь</div><div class="pwa-link-actions"><button class="retry-btn" type="button" style="margin-top:0;padding:8px 16px;font-size:12px" onclick="openFeedback(\'bug\')">Сообщить о баге</button><button class="retry-btn" type="button" style="margin-top:0;padding:8px 16px;font-size:12px" onclick="openFeedback(\'feature\')">Предложить функцию</button></div><div class="pwa-link-note">Форма откроется прямо внутри mini app, без перехода во внешний браузер.</div></div>'
  );
  
  const studentSwitchBtn=$('studentSwitchBtn');
  if(studentSwitchBtn) {
    studentSwitchBtn.addEventListener('click', async () => {
      const targetId = $('studentSwitchSelect').value;
      if (!targetId) return;
      studentSwitchBtn.textContent = 'Переключение...';
      try {
        await postApi('/api/mini/netschool/student/switch', {student_id: targetId});
        location.reload();
      } catch (e) {
        alert(e.message);
        studentSwitchBtn.textContent = 'Переключить';
      }
    });
  }

  document.querySelectorAll('.toggle[data-key]').forEach(btn=>btn.addEventListener('click',async()=>{
    try{const res=await postApi('/api/mini/netschool/settings/toggle',{key:btn.dataset.key});S.profileData=res.profile;renderProfile()}catch(e){alert(e.message)}
  }));
  const tt=$('themeToggle');
  if(tt)tt.addEventListener('click',()=>{applyTheme(S.theme==='dark'?'light':'dark',true);renderProfile()});
  const accentPicker=$('accentPicker');
  const accentReset=$('accentReset');
  let _accentTimer=null;
  function applyAccent(c){S.accentColor=c;setLocalAccentChoice(c);document.documentElement.style.setProperty('--accent',c);document.documentElement.style.setProperty('--primary',c);updateThemeChrome()}
  if(accentPicker)accentPicker.addEventListener('input',()=>{applyAccent(accentPicker.value);clearTimeout(_accentTimer);if(isThemeSyncEnabled())_accentTimer=setTimeout(()=>postApi('/api/mini/netschool/settings/toggle',{key:'accent_color',value:accentPicker.value}).catch(()=>{}),600)});
  if(accentReset)accentReset.addEventListener('click',()=>{S.accentColor='';setLocalAccentChoice('');document.documentElement.style.removeProperty('--accent');document.documentElement.style.removeProperty('--primary');updateThemeChrome();if(accentPicker)accentPicker.value=S.theme==='dark'?'#6b9fd4':'#4a76a8';if(isThemeSyncEnabled())postApi('/api/mini/netschool/settings/toggle',{key:'accent_color',value:''}).catch(()=>{})});
  const syncThemeCb=$('syncThemeAllDevices');
  if(syncThemeCb)syncThemeCb.addEventListener('change',async()=>{
    try{
      const res=await postApi('/api/mini/netschool/settings/toggle',{key:'theme_sync',value:syncThemeCb.checked?'true':'false'});
      mergeProfileData(res.profile);
      if(syncThemeCb.checked){
        await postApi('/api/mini/netschool/settings/toggle',{key:'theme',value:S.theme});
        await postApi('/api/mini/netschool/settings/toggle',{key:'accent_color',value:S.accentColor||''});
      }
      renderProfile();
    }catch(e){alert(e.message);syncThemeCb.checked=d.theme_sync!==false}
  });
  const pushModeSelect=$('pushModeSelect');
  if(pushModeSelect)pushModeSelect.addEventListener('change',async()=>{
    try{const res=await postApi('/api/mini/netschool/settings/toggle',{key:'push_mode',value:pushModeSelect.value});S.profileData=res.profile;renderProfile()}catch(e){alert(e.message);pushModeSelect.value=d.push_mode||'telegram'}
  });
  const pushEnableBtn=$('pushEnableBtn');
  if(pushEnableBtn)pushEnableBtn.addEventListener('click',()=>enableAppPush(pushEnableBtn));
  const pushTestBtn=$('pushTestBtn');
  if(pushTestBtn)pushTestBtn.addEventListener('click',()=>testPushNotification(pushTestBtn));
  const openInstallGuideBtn=$('openInstallGuideBtn');
  if(openInstallGuideBtn)openInstallGuideBtn.addEventListener('click',openInstallGuide);
  const openGalleryBtn=$('openGalleryBtn');
  if(openGalleryBtn)openGalleryBtn.addEventListener('click',openGalleryPage);
  const pwaIconEmoji=$('pwaIconEmoji');
  const pwaIconBg=$('pwaIconBg');
  const pwaIconFile=$('pwaIconFile');
  const syncPwaIconPreview=()=>renderPwaIconPreview({
    bg:(pwaIconBg&&pwaIconBg.value)||'#4a76a8',
    emoji:((pwaIconEmoji&&pwaIconEmoji.value)||'📘').trim().slice(0,2)||'📘',
  });
  if(pwaIconEmoji&&!pwaIconEmoji.dataset.bound){pwaIconEmoji.dataset.bound='1';pwaIconEmoji.addEventListener('input',syncPwaIconPreview)}
  if(pwaIconBg&&!pwaIconBg.dataset.bound){pwaIconBg.dataset.bound='1';pwaIconBg.addEventListener('input',syncPwaIconPreview)}
  if(pwaIconFile&&!pwaIconFile.dataset.bound){pwaIconFile.dataset.bound='1';pwaIconFile.addEventListener('change',handlePwaIconFileChange)}
  const pwaIconSaveBtn=$('pwaIconSaveBtn');
  if(pwaIconSaveBtn&&!pwaIconSaveBtn.dataset.bound){pwaIconSaveBtn.dataset.bound='1';pwaIconSaveBtn.addEventListener('click',savePwaIconSettings)}
  const pwaIconResetBtn=$('pwaIconResetBtn');
  if(pwaIconResetBtn&&!pwaIconResetBtn.dataset.bound){pwaIconResetBtn.dataset.bound='1';pwaIconResetBtn.addEventListener('click',resetPwaIconSettings)}
  const feedbackSubmitBtn=$('feedbackSubmitBtn');
  if(feedbackSubmitBtn&&!feedbackSubmitBtn.dataset.bound){feedbackSubmitBtn.dataset.bound='1';feedbackSubmitBtn.addEventListener('click',submitFeedback)}
  const feedbackCancelBtn=$('feedbackCancelBtn');
  if(feedbackCancelBtn&&!feedbackCancelBtn.dataset.bound){feedbackCancelBtn.dataset.bound='1';feedbackCancelBtn.addEventListener('click',closeFeedbackOverlay)}
  renderPwaIconPreview();
  refreshPushStatus();
}

function openInstallGuide(){
  html('sheetInstallGuideBody',
    '<div class="profile-card" style="margin:0 0 12px 0"><div style="font-weight:600;font-size:14px;margin-bottom:8px">iPhone и iPad</div><div style="font-size:13px;line-height:1.7;color:var(--text2)">1. Нажмите кнопку ниже и получите личную ссылку.<br>2. Откройте её именно в Safari.<br>3. Нажмите «Поделиться» (📤).<br>4. Выберите «На экран Домой».<br>5. Запускайте уже с иконки на домашнем экране.</div></div>'+
    '<div class="profile-card" style="margin:0 0 12px 0"><div style="font-weight:600;font-size:14px;margin-bottom:8px">Android</div><div style="font-size:13px;line-height:1.7;color:var(--text2)">1. Получите ту же личную ссылку ниже.<br>2. Откройте её в Chrome.<br>3. Нажмите меню браузера.<br>4. Выберите «Установить приложение» или «Добавить на главный экран».<br>5. Подтвердите установку и запускайте PWA уже как отдельное приложение.</div></div>'+
    '<div class="profile-card" style="margin:0"><div style="font-weight:600;font-size:14px;margin-bottom:8px">Личная ссылка для установки</div><div class="pwa-link-actions"><button class="retry-btn" type="button" style="margin-top:0;padding:8px 16px;font-size:12px" onclick="copyPwaLink(this,\'pwaGuideLinkBox\',\'pwaGuideLinkInput\')">Получить ссылку</button><button class="retry-btn" type="button" style="margin-top:0;padding:8px 16px;font-size:12px;opacity:.78" onclick="resetPwaLink(this,\'pwaGuideLinkBox\',\'pwaGuideLinkInput\')">Перевыпустить</button></div><div class="pwa-link-note" style="margin-top:10px">Если иконка менялась, переустановка по новой ссылке подтянет свежий значок.</div><div id="pwaGuideLinkBox"></div></div>'
  );
  $('installGuideOverlay').classList.add('open');
}

function openGalleryPage(){
  html('sheetGalleryBody','<div class="pwa-link-note" style="margin-bottom:12px">Здесь собраны все публичные иконки. Нажмите на иконку, чтобы применить её к своему PWA. Свои публикации можно удалить прямо отсюда.</div><div class="gallery-grid" id="galleryPageGrid"><div class="loader"><span class="spin"></span></div></div>');
  $('galleryOverlay').classList.add('open');
  loadGallery('galleryPageGrid');
}

async function loadGallery(targetId='galleryPageGrid'){
  const grid=$(targetId);
  if(!grid)return;
  try{
    const res=await fetch(withMiniappToken('/api/mini/netschool/gallery'),{credentials:'same-origin',headers:miniappHeaders()});
    if(!res.ok){grid.innerHTML='<div style="font-size:12px;color:var(--text2);grid-column:1/-1;text-align:center;padding:12px">Не удалось загрузить</div>';return}
    const data=await res.json();
    const icons=data.icons||[];
    if(!icons.length){grid.innerHTML='<div style="font-size:12px;color:var(--text2);grid-column:1/-1;text-align:center;padding:16px">Пока нет публичных иконок.<br>Загрузите свою картинку выше с галочкой «Добавить в галерею», и она появится здесь.</div>';return}
    grid.innerHTML=icons.map(ic=>'<div class="gallery-item" data-id="'+esc(ic.id)+'"><img src="'+esc(withMiniappToken(ic.url))+'" loading="lazy">'+(ic.can_delete?'<button class="gallery-item-delete" data-del-id="'+esc(ic.id)+'" title="Удалить публикацию">✕</button>':'')+'</div>').join('');
    grid.querySelectorAll('.gallery-item').forEach(item=>item.addEventListener('click',()=>selectGalleryIcon(item.dataset.id)));
    grid.querySelectorAll('.gallery-item-delete').forEach(btn=>btn.addEventListener('click',e=>{e.stopPropagation();deleteGalleryIcon(btn.dataset.delId)}));
  }catch(e){grid.innerHTML='<div style="font-size:12px;color:var(--text2);grid-column:1/-1;text-align:center;padding:12px">Ошибка загрузки галереи</div>'}
}

async function deleteGalleryIcon(galleryId){
  if(!confirm('Удалить эту иконку из общей галереи?'))return;
  try{
    await postApi('/api/mini/netschool/gallery/delete',{id:galleryId});
    loadGallery();
  }catch(e){alert(e.message||'Не удалось удалить публикацию')}
}

async function selectGalleryIcon(galleryId){
  if(!confirm('Применить эту иконку?'))return;
  try{
    const res=await postApi('/api/mini/netschool/gallery/select',{id:galleryId});
    if(res.profile)S.profileData=res.profile;
    S.pendingPwaIconImageData='';
    closeOv('galleryOverlay');
    renderProfile();
    if(res.install_url)showPwaIconLinkBox(res.install_url,'Иконка применена. Переустановите PWA по ссылке ниже.');
  }catch(e){alert(e.message||'Не удалось применить иконку')}
}

async function maybeAutoEnablePush(){
  if(S.autoPushAttempted)return;
  S.autoPushAttempted=true;
  const d=S.profileData||{};
  if(!d.push_configured||!isStandalonePwa()||!('Notification' in window)||!('serviceWorker' in navigator)||!('PushManager' in window))return;
  const flagKey='ns-auto-push:'+String(getMiniappToken()||'default');
  try{if(localStorage.getItem(flagKey)==='done')return}catch(e){}
  try{
    const reg=await ensurePushRegistration();
    const existing=reg&&reg.pushManager?await reg.pushManager.getSubscription():null;
    if(existing){try{localStorage.setItem(flagKey,'done')}catch(e){};return;}
    if(Notification.permission==='denied')return;
    const fakeBtn={textContent:'',dataset:{silent:'1'}};
    await enableAppPush(fakeBtn);
    try{localStorage.setItem(flagKey,'done')}catch(e){}
  }catch(e){}
}

async function savePwaIconSettings(){
  const emoji=String((($('pwaIconEmoji')||{}).value)||'').trim()||'📘';
  const bg=String((($('pwaIconBg')||{}).value)||'').trim()||'#4a76a8';
  const publicToggle=$('pwaIconPublic');
  const isPublic=publicToggle?publicToggle.checked:true;
  try{
    const payload={emoji,bg,'public':isPublic,keep_image:!!((S.profileData||{}).pwa_icon_has_image)};
    if(S.pendingPwaIconImageData)payload.image_data=S.pendingPwaIconImageData;
    const res=await postApi('/api/mini/netschool/settings/icon',payload);
    if(res.profile)S.profileData=res.profile;
    S.pendingPwaIconImageData='';
    renderProfile();
    if(res.install_url)showPwaIconLinkBox(res.install_url,'Отдельная ссылка для иконки готова. Откройте её в Safari и установите PWA заново, чтобы подтянуть новую иконку.');
  }catch(e){alert(e.message||'Не удалось сохранить иконку')}
}

async function resetPwaIconSettings(){
  try{
    const res=await postApi('/api/mini/netschool/settings/icon',{reset:true});
    if(res.profile)S.profileData=res.profile;
    S.pendingPwaIconImageData='';
    renderProfile();
    if(res.install_url)showPwaIconLinkBox(res.install_url,'Отдельная ссылка для иконки обновлена. Используйте её, если хотите заново поставить PWA со стандартной иконкой.');
  }catch(e){alert(e.message||'Не удалось сбросить иконку')}
}

async function copyPwaLink(btn,boxId='pwaGuideLinkBox',inputId='pwaGuideLinkInput'){
  try{
    const res=await api('/api/mini/netschool/pwa-link');
    if(res.url){
      const currentToken=extractMiniappTokenFromUrl(res.url);
      if(currentToken)storeMiniappToken(currentToken);
      let status='Ссылка готова ниже.';
      if(isAppleMobile()&&navigator.share){
        try{
          await navigator.share({title:'NetSchool PWA',url:res.url});
          status='Открылось системное меню «Поделиться». Если установка не завершена, ссылка остаётся ниже.';
          btn.textContent='Поделиться';
          showPwaLinkBox(res.url,status,boxId,inputId);
          return;
        }catch(e){}
      }
      const copied=await tryCopyText(res.url).catch(()=>false);
      if(copied){
        status='Ссылка скопирована и показана ниже на случай, если iOS не отдаст буфер приложению.';
        btn.textContent='Скопировано';
      } else {
        status='Буфер обмена недоступен в текущем WebView. Ссылка показана ниже: нажмите «Выделить ссылку» и скопируйте вручную.';
        btn.textContent='Ссылка готова';
      }
      showPwaLinkBox(res.url,status,boxId,inputId);
    }
  }catch(e){btn.textContent='Ошибка';alert(e.message)}
}

async function resetPwaLink(btn,boxId='pwaGuideLinkBox',inputId='pwaGuideLinkInput'){
  if(!confirm('Старая ссылка перестанет работать. Перевыпустить?'))return;
  try{
    const res=await postApi('/api/mini/netschool/pwa-link/reset',{});
    if(res.url){
      const newToken=extractMiniappTokenFromUrl(res.url);
      if(newToken)storeMiniappToken(newToken);
      const copied=await tryCopyText(res.url).catch(()=>false);
      showPwaLinkBox(res.url,copied
        ?'Новая ссылка перевыпущена и скопирована. Предыдущая ссылка больше не работает.'
        :'Новая ссылка перевыпущена. Предыдущая ссылка больше не работает. Если вход слетел, используйте новую ссылку ниже или код из Telegram.',boxId,inputId);
      btn.textContent=copied?'Перевыпущено':'Ссылка обновлена';
    }
  }catch(e){btn.textContent='Ошибка';alert(e.message)}
}

async function refreshDashboard(showLoading=false,announce=false){
  if(S.isLoading)return;
  S.isLoading=true;
  setTopLoading('Обновляем данные',true);
  if(showLoading){
    html('diaryContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');
    if(S.currentTab==='homework')html('hwContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');
    if(S.currentTab==='grades')html('gradesContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');
    if(S.currentTab==='calc')html('calcContent','<div class="loader"><span class="spin"></span> Загрузка…</div>');
  }
  const previousDash=S.dash;
  try{
    S.dash=await api('/api/mini/netschool/dashboard?ts='+Date.now());
    syncDiarySelectionFromDash(!previousDash);
    const diff=computeDashboardDelta(previousDash,S.dash);
    S.delta.newGradeKeys=diff.newGradeKeys;
    S.delta.changedSubjects=diff.changedSubjects;
    S.delta.newHomeworkKeys=diff.newHomeworkKeys;
    S.delta.gradeCount=diff.gradeCount;
    S.delta.homeworkCount=diff.homeworkCount;
    updateNavBadges();
    try{localStorage.setItem('ns-cache-dash',JSON.stringify(S.dash))}catch(e){}
    if(S.dash&&S.dash.profile)syncAppearanceFromProfile(S.dash.profile);
    if(S.profileData){
      S.profileData.last_sync_at=nowSyncLabel();
    }
    const activePanel=document.querySelector('.panel.active');
    const activePanelId=activePanel?activePanel.id:'';
    const preservedScroll=activePanel?activePanel.scrollTop:0;
    if(S.dash.cache_notice)txt('weekLabel',S.dash.cache_notice);else if(S.currentTab==='diary')renderWeekNav();
    if(S.currentTab!=='profile'&&!document.querySelector('.overlay.open,.cal-overlay.open')){
      refreshCurrentTab();
      if(activePanelId){
        requestAnimationFrame(()=>{
          const panel=$(activePanelId);
          if(!panel||!panel.classList.contains('active'))return;
          const maxScroll=Math.max(0,panel.scrollHeight-panel.clientHeight);
          panel.scrollTop=Math.min(preservedScroll,maxScroll);
        });
      }
    }
    if(announce)showRefreshStatus(true,'Обновление данных прошло успешно');
  }catch(e){
    if(!S.dash)html('diaryContent','<div class="empty">'+escWithBr(e&&e.message?e.message:'Ошибка загрузки')+buildErrorActionBlock(e,'loadAll()')+'</div>');
    if(announce)showRefreshStatus(false,'Обновление данных не удалось');
    throw e;
  }finally{
    S.isLoading=false;
    setTopLoading('',false);
  }
}

async function refreshLiveData(showLoading=false,announce=false){
  try{
    await refreshDashboard(showLoading,false);
    S.totals=null;
    if(S.currentTab==='grades')ensureTotalsLoaded();
    if(S.currentTab==='mail'||S.mail)await loadMailPage(1,false);
    if(announce)showRefreshStatus(true,'Обновление данных прошло успешно');
  }catch(e){
    if(announce)showRefreshStatus(false,'Обновление данных не удалось');
    throw e;
  }
}

/* Load data — cache-first, then live update */
async function loadAll(){
  if(S.isLoading)return;
  if(!S.dash&&INITIAL_DASH){S.dash=INITIAL_DASH;syncDiarySelectionFromDash(true);renderWeekNav();refreshCurrentTab()}
  try{
    S.delta.unreadMailCount=Number((S.profileData||{}).mail_unread_count||0)||0;
    updateNavBadges();
    const cd=localStorage.getItem('ns-cache-dash');
    if(cd){S.dash=JSON.parse(cd);syncDiarySelectionFromDash(true);renderWeekNav();refreshCurrentTab()}
    const cm=localStorage.getItem('ns-cache-mail');
    if(cm){
      S.mail=JSON.parse(cm);
      S.delta.unreadMailCount=Math.max(Number((S.profileData||{}).mail_unread_count||0)||0,((S.mail.entries)||[]).filter(item=>item.unread).length);
      updateNavBadges();
      if(S.currentTab==='mail')renderMailList();
    }
  }catch(e){}
  return refreshLiveData(!S.dash).catch(()=>null);
}

(function(){
  let pulling=false,startY=0,deltaY=0;
  const threshold=56;
  const indicator=$('refreshIndicator');
  const setIndicator=(text,show)=>{if(!indicator)return;indicator.textContent=text;if(show)indicator.classList.add('show');else indicator.classList.remove('show')};
  const topScroll=()=>activePanelScrollTop();
  const canStartPull=(target)=>{
    if(S.isLoading)return false;
    if(document.querySelector('.overlay.open,.cal-overlay.open'))return false;
    if(target&&target.closest&&target.closest('input, textarea, select, button, .sheet-body, .bottom-nav'))return false;
    return topScroll()<=4;
  };
  document.addEventListener('touchstart',e=>{
    if(!canStartPull(e.target))return;
    pulling=true;startY=e.touches[0].clientY;deltaY=0;
  },{passive:true});
  document.addEventListener('touchmove',e=>{
    if(!pulling)return;
    deltaY=e.touches[0].clientY-startY;
    if(deltaY>14){
      setIndicator(deltaY>threshold?'Отпустите для обновления':'Потяните вниз, чтобы обновить',true);
      if(deltaY>18)e.preventDefault();
    }
  },{passive:false});
  document.addEventListener('touchend',()=>{
    if(!pulling)return;
    pulling=false;
    if(deltaY>threshold&&!S.isLoading){
      setIndicator('Обновление…',true);
      refreshLiveData(false,true).finally(()=>setTimeout(()=>setIndicator('',false),120));
      return;
    }
    setIndicator('',false);
  },{passive:true});
})();

S.profileData={
  student_name:{{ data.student_name|tojson }},
  school:{{ data.school|tojson }},
  last_sync_at:{{ data.last_sync_at|tojson }},
  login:{{ data.login|tojson }},
  interval_label:{{ data.interval_label|tojson }},
  quiet_hours:{{ data.quiet_hours|tojson }},
  enabled_class:{{ data.enabled_class|tojson }},
  mail_class:{{ data.mail_class|tojson }},
  mail_unread_count:{{ data.mail_unread_count|tojson }},
  changes_class:{{ data.changes_class|tojson }},
  deletes_class:{{ data.deletes_class|tojson }},
  weekly_class:{{ data.weekly_class|tojson }},
  homework_class:{{ data.homework_class|tojson }},
  push_mode:{{ data.push_mode|tojson }},
  push_mode_label:{{ data.push_mode_label|tojson }},
  push_status_label:{{ data.push_status_label|tojson }},
  push_subscription_count:{{ data.push_subscription_count|tojson }},
  push_configured:{{ data.push_configured|tojson }},
  push_public_key:{{ data.push_public_key|tojson }},
  miniapp_token:{{ data.miniapp_token|tojson }},
  pwa_icon_emoji:{{ data.pwa_icon_emoji|tojson }},
  pwa_icon_bg:{{ data.pwa_icon_bg|tojson }},
  pwa_icon_has_image:{{ data.pwa_icon_has_image|tojson }},
  pwa_icon_url:{{ data.pwa_icon_url|tojson }},
  pwa_icon_version:{{ data.pwa_icon_version|tojson }},
  theme:{{ data.theme|tojson }},
  theme_saved:{{ data.theme_saved|tojson }},
  theme_updated_at:{{ data.theme_updated_at|tojson }},
  accent_color:{{ data.accent_color|tojson }},
  accent_saved:{{ data.accent_saved|tojson }},
  accent_updated_at:{{ data.accent_updated_at|tojson }},
  theme_sync:{{ data.theme_sync|tojson }},
  available_students:{{ data.available_students|tojson }},
  selected_student_id:{{ data.selected_student_id|tojson }},
};
storeMiniappToken(S.profileData.miniapp_token||'');
/* Apply server theme if sync enabled */
(function(){
  const sync=S.profileData.theme_sync!==false;
  syncAppearanceFromProfile(S.profileData,{force:true});
  const localTheme=localStorage.getItem('ns-theme')||S.theme;
  const localAccent=localStorage.getItem('ns-accent')||'';
  const localThemeUpdatedAt=parseStoredTs(localStorage.getItem(NS_THEME_TS_KEY)||0);
  const localAccentUpdatedAt=parseStoredTs(localStorage.getItem(NS_ACCENT_TS_KEY)||0);
  const srvThemeUpdatedAt=Date.parse(S.profileData.theme_updated_at||'')||0;
  const srvAccentUpdatedAt=Date.parse(S.profileData.accent_updated_at||'')||0;
  if(sync&&localTheme&&(localThemeUpdatedAt>srvThemeUpdatedAt||!S.profileData.theme_saved)){
    if(localTheme!==S.theme)applyTheme(localTheme,false);
    postApi('/api/mini/netschool/settings/toggle',{key:'theme',value:localTheme}).then(res=>{mergeProfileData(res.profile)}).catch(()=>{});
  }
  if(sync&&(localAccentUpdatedAt>srvAccentUpdatedAt||!S.profileData.accent_saved)){
    if(localAccent){S.accentColor=localAccent;document.documentElement.style.setProperty('--accent',localAccent);document.documentElement.style.setProperty('--primary',localAccent);updateThemeChrome();postApi('/api/mini/netschool/settings/toggle',{key:'accent_color',value:localAccent}).then(res=>{mergeProfileData(res.profile)}).catch(()=>{})}
    else if(localAccentUpdatedAt>srvAccentUpdatedAt){document.documentElement.style.removeProperty('--accent');document.documentElement.style.removeProperty('--primary');S.accentColor='';updateThemeChrome();postApi('/api/mini/netschool/settings/toggle',{key:'accent_color',value:''}).then(res=>{mergeProfileData(res.profile)}).catch(()=>{})}
  }else if(!sync){if(localTheme&&localTheme!==S.theme)applyTheme(localTheme,false);if(localAccent){S.accentColor=localAccent;document.documentElement.style.setProperty('--accent',localAccent);document.documentElement.style.setProperty('--primary',localAccent);updateThemeChrome()}}
})();
renderWeekNav();
if('serviceWorker' in navigator){ensurePushRegistration().catch(()=>null)}
window.addEventListener('hashchange',()=>{const tab=(location.hash||'').replace('#','');if(HASH_TABS.includes(tab)&&tab!==S.currentTab)switchTab(tab)});
switchTab(S.currentTab);
loadAll();
setTimeout(()=>maybeAutoEnablePush(),500);
</script>
{% endif %}
</body>
</html>"""
