// Общее для всех экранов: доступ к API, разметка, состояние.
'use strict';

export const { base, token, pushEnabled, student, school } = window.NETSCHOOL;

// Telegram отдаёт объект только внутри мини-приложения. Вне его
// (установленное на домашний экран) работаем по токену из ссылки.
export const tg = window.Telegram && window.Telegram.WebApp;
export const initData = (tg && tg.initData) || '';

/** Состояние приложения. Одно место вместо переменных врассыпную. */
export const state = {
  tab: 'diary',
  week: 0,
  day: null,
  diary: null,
  grades: null,
  homework: null,
  mail: null,
  profile: null,
  gradeFilter: 'all',
  calc: null,
};

export const $ = (id) => document.getElementById(id);

export function esc(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

/** Экранирование плюс переносы строк и кликабельные ссылки. */
export function escRich(value) {
  return esc(value)
    .replace(/\n/g, '<br>')
    .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

export function markClass(mark) {
  const digit = String(mark || '').match(/[2-5]/);
  return digit ? `mark m${digit[0]}` : 'mark';
}

export function avgClass(value) {
  const rounded = Math.round(Number(value) || 0);
  return rounded >= 5 ? 'g5' : rounded === 4 ? 'g4' : rounded === 3 ? 'g3' : 'g2';
}

export function skeleton(count = 5) {
  return `<div class="card">${'<div class="skeleton"></div>'.repeat(count)}</div>`;
}

export function banner(text, isError) {
  const el = $('banner');
  el.textContent = text || '';
  el.classList.toggle('error', Boolean(isError));
  el.hidden = !text;
}

/** Запрос к API с удостоверением личности и разбором ошибки. */
export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  // initData подписана токеном бота — сервер доверяет ей больше, чем
  // токену из ссылки, поэтому шлём оба и приоритет отдаёт он.
  if (initData) headers['X-Telegram-Init-Data'] = initData;
  if (token) headers['X-Netschool-Token'] = token;

  const response = await fetch(base + path, { ...options, headers, cache: 'no-store' });

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error('Сервер ответил неожиданным образом');
  }
  if (!response.ok || !payload.ok) {
    const error = new Error(payload.error || `Ошибка ${response.status}`);
    error.reason = payload.reason;
    throw error;
  }
  return payload;
}

/** Ссылка на вложение: браузер качает её сам, заголовок туда не положить. */
export function attachmentUrl(id) {
  const credential = initData
    ? `tgWebAppData=${encodeURIComponent(initData)}`
    : `token=${encodeURIComponent(token)}`;
  return `${base}/api/attachment/${id}?${credential}`;
}

export function attachmentsHtml(items) {
  if (!items || !items.length) return '';
  return items
    .map(
      (item) =>
        `<a class="attach" href="${attachmentUrl(item.id)}" target="_blank" rel="noopener">📎 ${esc(item.name)}</a>`
    )
    .join('');
}

export function errorCard(error, retryId) {
  const needsLogin = error.reason === 'login' || error.reason === 'auth';
  return `<div class="card">
      <p>${esc(error.message)}</p>
      ${needsLogin ? '<p class="muted small" style="margin-top:6px">Откройте бота и выполните /login.</p>' : ''}
      ${retryId ? `<button class="btn" id="${retryId}">Повторить</button>` : ''}
    </div>`;
}

/* ─────────────────────────── Даты ─────────────────────────── */

export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
export const MONTHS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];

export function isoToday() {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function pad(n) {
  return n < 10 ? `0${n}` : String(n);
}

export function parseIso(iso) {
  const [y, m, d] = String(iso).split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function shortDate(iso) {
  const date = parseIso(iso);
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}`;
}

export function longDate(iso) {
  const date = parseIso(iso);
  return `${WEEKDAYS[(date.getDay() + 6) % 7]}, ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}
