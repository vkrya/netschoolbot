// Школьная почта: список и чтение письма.
'use strict';

import {
  $, api, attachmentsHtml, errorCard, esc, escRich, shortDate, skeleton, state,
} from './core.js';
import { openSheet } from './sheet.js';

export async function loadMail(force = false) {
  const container = $('mailContent');
  if (!state.mail || force) {
    container.innerHTML = skeleton();
    try {
      const { data } = await api('/api/mail');
      state.mail = data;
    } catch (error) {
      container.innerHTML = errorCard(error, 'mailRetry');
      $('mailRetry')?.addEventListener('click', () => loadMail(true));
      return;
    }
  }
  render();
}

function render() {
  const messages = state.mail.messages || [];
  if (!messages.length) {
    $('mailContent').innerHTML = '<div class="card"><div class="empty">Писем нет</div></div>';
    return;
  }

  $('mailContent').innerHTML = `<div class="card">${messages.map(row).join('')}</div>`;
  $('mailContent').querySelectorAll('[data-mail]').forEach((element) => {
    element.addEventListener('click', () => open(element.dataset.mail));
  });
}

function row(message) {
  return `<div class="mail-item ${message.read ? 'read' : ''}" data-mail="${esc(message.id)}">
      <span class="mail-dot ${message.read ? 'read' : ''}"></span>
      <div class="mail-main">
        <div class="mail-subject">${esc(message.subject)}</div>
        <div class="mail-from">${esc(message.author)}</div>
      </div>
      <span class="mail-date">${message.sent ? esc(shortDate(message.sent.slice(0, 10))) : ''}</span>
    </div>`;
}

async function open(id) {
  const body = openSheet('Письмо', skeleton(4));
  try {
    const { data } = await api(`/api/mail/${encodeURIComponent(id)}`);
    $('sheetTitle').textContent = data.subject || 'Письмо';
    body.innerHTML = `
      <div class="row"><span class="label">От кого</span><span>${esc(data.author)}</span></div>
      ${data.sent ? `<div class="row"><span class="label">Дата</span><span>${esc(shortDate(data.sent.slice(0, 10)))}</span></div>` : ''}
      <div style="margin-top:12px">${escRich(data.text) || '<span class="muted">Пустое письмо</span>'}</div>
      ${attachmentsHtml(data.attachments)}`;

    // Письмо прочитано — отметка в списке, чтобы не перезагружать его целиком.
    const message = (state.mail.messages || []).find((item) => String(item.id) === String(id));
    if (message && !message.read) {
      message.read = true;
      render();
    }
  } catch (error) {
    body.innerHTML = errorCard(error);
  }
}
