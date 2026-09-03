// Мини-приложение «Сетевого города».
//
// Отдельный файл вместо JavaScript внутри Python-строки: подсветка, линтер
// и кэширование браузером теперь работают.
'use strict';

const { base, token, pushEnabled } = window.NETSCHOOL;

const banner = document.getElementById('banner');
const refreshButton = document.getElementById('refresh');

// Что уже загружено: повторное открытие вкладки не дёргает школьный сервер.
const loaded = new Set();
let activeView = 'diary';

function showBanner(text, isError) {
  banner.textContent = text;
  banner.classList.toggle('error', Boolean(isError));
  banner.hidden = !text;
}

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

function markClass(mark) {
  const digits = String(mark || '').match(/\d/);
  return digits ? `mark m${digits[0]}` : 'mark';
}

async function api(path, options = {}) {
  const url = new URL(base + path, location.origin);
  const response = await fetch(url, {
    ...options,
    headers: { 'X-Netschool-Token': token, 'Content-Type': 'application/json', ...(options.headers || {}) },
  });

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error('Сервер ответил неожиданным образом');
  }
  if (!response.ok || !payload.ok) {
    const error = new Error(payload.error || 'Не удалось загрузить данные');
    error.reason = payload.reason;
    throw error;
  }
  return payload;
}

function skeleton(container, rows = 4) {
  container.innerHTML = `<div class="card">${'<div class="skeleton"></div>'.repeat(rows)}</div>`;
}

const views = {
  async diary(container) {
    const { data, stale } = await api('/api/diary');
    if (stale) showBanner('Школьный сервер не отвечает — показываю сохранённые данные.');

    const days = data.days.filter((day) => day.marks.length || day.homework.length);
    if (!days.length) {
      container.innerHTML = '<div class="card muted">Записей за период нет.</div>';
      return;
    }
    container.innerHTML = days
      .map(
        (day) => `
        <div class="card">
          <h2>${escapeHtml(day.label)}</h2>
          ${day.marks
            .map(
              (m) => `<div class="row">
                <span class="label">${escapeHtml(m.subject)} · ${escapeHtml(m.title)}</span>
                <span class="${markClass(m.mark)}">${escapeHtml(m.mark)}</span>
              </div>`
            )
            .join('')}
          ${day.homework
            .map(
              (h) => `<div class="row">
                <span class="label">📚 ${escapeHtml(h.subject)}: ${escapeHtml(h.text || '—')}</span>
                ${h.attachments.length ? `<span class="chip">${h.attachments.length} файл.</span>` : ''}
              </div>`
            )
            .join('')}
        </div>`
      )
      .join('');
  },

  async marks(container) {
    const { data, stale } = await api('/api/marks');
    if (stale) showBanner('Показаны сохранённые оценки.');

    if (!data.subjects.length) {
      container.innerHTML = '<div class="card muted">Оценок за период нет.</div>';
      return;
    }
    const overall = data.average ? data.average.toFixed(2) : '—';
    container.innerHTML =
      `<div class="card"><h2>Средний балл<span class="mark">${overall}</span></h2></div>` +
      data.subjects
        .map(
          (subject) => `
        <div class="card">
          <h2>
            <span class="label">${escapeHtml(subject.subject)}</span>
            <span class="${markClass(Math.round(subject.average || 0))}">
              ${subject.average ? subject.average.toFixed(2) : '—'}
            </span>
          </h2>
          ${subject.marks
            .map(
              (m) => `<div class="row">
                <span class="label">${escapeHtml(m.date.split('-').reverse().slice(0, 2).join('.'))} ${escapeHtml(m.title)}</span>
                <span class="${markClass(m.mark)}">${escapeHtml(m.mark)}</span>
              </div>`
            )
            .join('')}
        </div>`
        )
        .join('');
  },

  async homework(container) {
    const { data, stale } = await api('/api/homework');
    if (stale) showBanner('Показаны сохранённые задания.');

    if (!data.items.length) {
      container.innerHTML = '<div class="card muted">Заданий нет.</div>';
      return;
    }
    const byDate = new Map();
    for (const item of data.items) {
      if (!byDate.has(item.label)) byDate.set(item.label, []);
      byDate.get(item.label).push(item);
    }
    container.innerHTML = [...byDate.entries()]
      .map(
        ([label, items]) => `
        <div class="card">
          <h2>${escapeHtml(label)}</h2>
          ${items
            .map(
              (item) => `<div class="row">
                <span class="label"><b>${escapeHtml(item.subject)}</b><br>${escapeHtml(item.text || '—')}</span>
              </div>
              ${
                item.attachments.length
                  ? `<div class="chips">${item.attachments
                      .map(
                        (a) =>
                          `<a class="chip" href="${base}/api/attachment/${a.id}?token=${encodeURIComponent(token)}">📎 ${escapeHtml(a.name)}</a>`
                      )
                      .join('')}</div>`
                  : ''
              }`
            )
            .join('')}
        </div>`
      )
      .join('');
  },

  async settings(container) {
    const { data } = await api('/api/profile');
    const students = data.students.length > 1
      ? `<div class="card">
           <h2>Ученик</h2>
           ${data.students
             .map(
               (s) =>
                 `<button class="wide ${s.current ? 'primary' : ''}" data-student="${s.id}">${escapeHtml(s.name)}</button>`
             )
             .join('')}
         </div>`
      : '';

    container.innerHTML = `
      <div class="card">
        <h2>Профиль</h2>
        <div class="row"><span class="label">Ученик</span><span>${escapeHtml(data.name)}</span></div>
        <div class="row"><span class="label">Школа</span><span>${escapeHtml(data.school)}</span></div>
        <div class="row"><span class="label">Проверка</span><span>каждые ${data.interval_minutes} мин</span></div>
        <div class="row"><span class="label">Тихие часы</span><span>${escapeHtml(data.quiet_hours)}</span></div>
      </div>
      ${students}
      ${pushEnabled ? '<div class="card"><h2>Уведомления в браузере</h2><button class="wide" id="push">Включить</button></div>' : ''}
      <div class="card muted small">
        Настройки уведомлений меняются в Telegram-боте: <code>/settings</code>.
      </div>`;

    container.querySelectorAll('[data-student]').forEach((button) => {
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          await api('/api/student', {
            method: 'POST',
            body: JSON.stringify({ id: Number(button.dataset.student) }),
          });
          // Дневник другого ребёнка — другие данные, кэш вкладок сбрасываем.
          loaded.clear();
          location.reload();
        } catch (error) {
          showBanner(error.message, true);
          button.disabled = false;
        }
      });
    });

    const pushButton = container.querySelector('#push');
    if (pushButton) pushButton.addEventListener('click', () => enablePush(pushButton));
  },
};

async function render(name, { force = false } = {}) {
  const container = document.getElementById(`view-${name}`);
  if (!force && loaded.has(name)) return;

  skeleton(container);
  try {
    await views[name](container);
    loaded.add(name);
  } catch (error) {
    loaded.delete(name);
    const needsLogin = error.reason === 'auth' || error.reason === 'token';
    container.innerHTML = `<div class="card">
        <p>${escapeHtml(error.message)}</p>
        ${needsLogin ? '<p class="muted small">Откройте бота в Telegram и выполните /login.</p>' : ''}
      </div>`;
  }
}

function switchTo(name) {
  activeView = name;
  document.querySelectorAll('.view').forEach((section) => {
    section.hidden = section.id !== `view-${name}`;
  });
  document.querySelectorAll('.tabs button').forEach((button) => {
    button.classList.toggle('active', button.dataset.view === name);
  });
  render(name);
}

document.querySelectorAll('.tabs button').forEach((button) => {
  button.addEventListener('click', () => switchTo(button.dataset.view));
});

refreshButton.addEventListener('click', async () => {
  refreshButton.classList.add('spinning');
  showBanner('');
  loaded.delete(activeView);
  await render(activeView, { force: true });
  refreshButton.classList.remove('spinning');
});

async function enablePush(button) {
  button.disabled = true;
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      throw new Error('Браузер не поддерживает уведомления');
    }
    if ((await Notification.requestPermission()) !== 'granted') {
      throw new Error('Разрешение на уведомления не выдано');
    }
    const registration = await navigator.serviceWorker.register(
      `${base}/sw.js?token=${encodeURIComponent(token)}`,
      { scope: base + '/' }
    );
    const { data } = await api('/api/push/key');
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(data.key),
    });
    await api('/api/push/subscribe', { method: 'POST', body: JSON.stringify(subscription.toJSON()) });
    button.textContent = 'Уведомления включены ✓';
  } catch (error) {
    showBanner(error.message, true);
    button.disabled = false;
  }
}

function urlBase64ToUint8Array(value) {
  const padding = '='.repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

switchTo('diary');
