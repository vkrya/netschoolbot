// Профиль: ученик, школа, оформление, уведомления в браузере.
'use strict';

import {
  $, api, banner, errorCard, esc, pushEnabled, skeleton, state, tg,
} from './core.js';
import { closeSheet, openSheet } from './sheet.js';

const THEME_KEY = 'ns-theme';

export async function loadProfile(force = false) {
  const container = $('profileContent');
  if (!state.profile || force) {
    container.innerHTML = skeleton();
    try {
      const { data } = await api('/api/profile');
      state.profile = data;
    } catch (error) {
      container.innerHTML = errorCard(error, 'profileRetry');
      $('profileRetry')?.addEventListener('click', () => loadProfile(true));
      return;
    }
  }
  render();
}

function render() {
  const data = state.profile;
  const theme = currentTheme();

  const children = data.students.length > 1
    ? `<div class="card">
         <div class="card-title">Ученик</div>
         ${data.students
           .map(
             (item) =>
               `<button class="btn ${item.current ? 'primary' : ''}" data-student="${item.id}">${esc(item.name)}</button>`
           )
           .join('')}
       </div>`
    : '';

  $('profileContent').innerHTML = `
    <div class="card">
      <div class="card-title">Профиль</div>
      <div class="row"><span class="label">Ученик</span><span>${esc(data.name)}</span></div>
      <div class="row"><span class="label">Школа</span><span>${esc(data.school)}</span></div>
      <div class="row"><span class="label">Проверка оценок</span><span>каждые ${data.interval_minutes} мин</span></div>
      <div class="row"><span class="label">Тихие часы</span><span>${esc(data.quiet_hours)}</span></div>
    </div>

    ${children}

    <div class="card">
      <div class="card-title">Оформление</div>
      <div class="chips">
        <button class="chip ${theme === 'light' ? 'active' : ''}" data-theme="light">Светлая</button>
        <button class="chip ${theme === 'dark' ? 'active' : ''}" data-theme="dark">Тёмная</button>
        <button class="chip ${theme === 'auto' ? 'active' : ''}" data-theme="auto">Как в системе</button>
      </div>
    </div>

    ${pushEnabled ? `<div class="card">
      <div class="card-title">Уведомления в браузере</div>
      <p class="muted small">Приходят, даже когда приложение закрыто. В Telegram уведомления работают и без этого.</p>
      <button class="btn" id="pushBtn">Включить</button>
    </div>` : ''}

    <div class="card">
      <div class="card-title">Уведомления</div>
      ${notificationRows(data.notifications)}
      <p class="muted small" style="margin-top:8px">Меняются в боте: <code>/settings</code></p>
    </div>

    <div class="card muted small">
      Дневник «Сетевого города». Данные не покидают ваш сервер.
    </div>`;

  bind();
}

function notificationRows(prefs) {
  const labels = {
    grades: 'Новые оценки',
    changes: 'Изменения оценок',
    deletes: 'Удаления оценок',
    homework: 'Домашние задания',
    mail: 'Школьная почта',
    weekly_summary: 'Сводка по понедельникам',
  };
  return Object.entries(labels)
    .map(
      ([key, label]) =>
        `<div class="row"><span class="label">${label}</span><span>${prefs[key] ? '✅' : '🔕'}</span></div>`
    )
    .join('');
}

function currentTheme() {
  try {
    return localStorage.getItem(THEME_KEY) || 'auto';
  } catch {
    // Приватный режим и запрет на хранилище — не повод ломать экран.
    return 'auto';
  }
}

export function applyStoredTheme() {
  const theme = currentTheme();
  if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
}

function bind() {
  $('profileContent').querySelectorAll('[data-theme]').forEach((chip) => {
    chip.addEventListener('click', () => {
      try {
        localStorage.setItem(THEME_KEY, chip.dataset.theme);
      } catch {
        /* хранилище недоступно — тема продержится до перезагрузки */
      }
      applyStoredTheme();
      render();
    });
  });

  $('profileContent').querySelectorAll('[data-student]').forEach((button) => {
    button.addEventListener('click', () => switchStudent(button));
  });

  $('pushBtn')?.addEventListener('click', (event) => enablePush(event.target));
}

async function switchStudent(button) {
  button.disabled = true;
  try {
    await api('/api/student', {
      method: 'POST',
      body: JSON.stringify({ id: Number(button.dataset.student) }),
    });
    // Дневник другого ребёнка — совсем другие данные, сбрасываем всё.
    location.reload();
  } catch (error) {
    banner(error.message, true);
    button.disabled = false;
  }
}

export function openChildSwitch() {
  const students = state.profile?.students || [];
  if (students.length < 2) return;
  const body = openSheet(
    'Ученик',
    students
      .map(
        (item) =>
          `<button class="btn ${item.current ? 'primary' : ''}" data-student="${item.id}">${esc(item.name)}</button>`
      )
      .join('')
  );
  body.querySelectorAll('[data-student]').forEach((button) => {
    button.addEventListener('click', () => {
      closeSheet();
      switchStudent(button);
    });
  });
}

async function enablePush(button) {
  button.disabled = true;
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      throw new Error('Браузер не поддерживает уведомления');
    }
    if ((await Notification.requestPermission()) !== 'granted') {
      throw new Error('Разрешение не выдано');
    }
    const { base, token } = window.NETSCHOOL;
    const registration = await navigator.serviceWorker.register(
      `${base}/sw.js?token=${encodeURIComponent(token)}`,
      { scope: `${base}/` }
    );
    const { data } = await api('/api/push/key');
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(data.key),
    });
    await api('/api/push/subscribe', {
      method: 'POST',
      body: JSON.stringify(subscription.toJSON()),
    });
    button.textContent = 'Уведомления включены ✓';
  } catch (error) {
    banner(error.message, true);
    button.disabled = false;
  }
}

function urlBase64ToUint8Array(value) {
  const padding = '='.repeat((4 - (value.length % 4)) % 4);
  const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}
