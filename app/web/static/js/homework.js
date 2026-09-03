// Домашние задания, сгруппированные по дате.
'use strict';

import {
  $, api, attachmentsHtml, errorCard, esc, escRich, isoToday, longDate,
  skeleton, state,
} from './core.js';
import { openSheet } from './sheet.js';

export async function loadHomework(force = false) {
  const container = $('homeworkContent');
  if (!state.homework || force) {
    container.innerHTML = skeleton();
    try {
      const { data } = await api('/api/homework');
      state.homework = data;
    } catch (error) {
      container.innerHTML = errorCard(error, 'hwRetry');
      $('hwRetry')?.addEventListener('click', () => loadHomework(true));
      return;
    }
  }
  render();
}

function render() {
  const today = isoToday();
  // Прошедшее не показываем: домашка нужна на «сейчас и вперёд».
  const items = state.homework.items.filter((item) => item.date >= today);

  if (!items.length) {
    $('homeworkContent').innerHTML =
      '<div class="card"><div class="empty">Заданий нет 🎉</div></div>';
    return;
  }

  const byDate = new Map();
  for (const item of items) {
    if (!byDate.has(item.date)) byDate.set(item.date, []);
    byDate.get(item.date).push(item);
  }

  $('homeworkContent').innerHTML = [...byDate.entries()]
    .map(
      ([date, group]) => `<div class="card">
          <div class="card-title">${esc(longDate(date))}<span class="muted small">${group.length}</span></div>
          ${group.map((item) => row(item, items.indexOf(item))).join('')}
        </div>`
    )
    .join('');

  $('homeworkContent').querySelectorAll('[data-hw]').forEach((element) => {
    element.addEventListener('click', () => open(items[Number(element.dataset.hw)]));
  });
}

function row(item, index) {
  const files = item.attachments.length ? ` <span class="muted small">📎 ${item.attachments.length}</span>` : '';
  return `<div class="hw-item" data-hw="${index}">
      <div class="hw-subject">${esc(item.subject)}${files}</div>
      <div class="hw-text">${esc(item.text) || '—'}</div>
    </div>`;
}

function open(item) {
  openSheet(
    item.subject,
    `<div class="row"><span class="label">Срок</span><span>${esc(longDate(item.date))}</span></div>
     <div style="margin-top:12px">${escRich(item.text) || '<span class="muted">Без текста</span>'}</div>
     ${attachmentsHtml(item.attachments)}`
  );
}
