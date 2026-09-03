// Оценки: список предметов со средним баллом и разбор по предмету.
'use strict';

import {
  $, api, avgClass, errorCard, esc, markClass, shortDate, skeleton, state,
} from './core.js';
import { openSheet } from './sheet.js';

const QUARTERS = [
  ['all', 'Все'],
  ['q1', '1 четв.'],
  ['q2', '2 четв.'],
  ['q3', '3 четв.'],
  ['q4', '4 четв.'],
];

export async function loadGrades(force = false) {
  const container = $('gradesContent');
  if (!state.grades || force) {
    container.innerHTML = skeleton();
    try {
      const { data } = await api('/api/marks');
      state.grades = data;
      // При первом открытии показываем текущую четверть, а не всё подряд:
      // за год оценок слишком много, чтобы что-то в них разглядеть.
      if (state.gradeFilter === 'all' && data.current_quarter) {
        state.gradeFilter = data.current_quarter;
      }
    } catch (error) {
      container.innerHTML = errorCard(error, 'gradesRetry');
      $('gradesRetry')?.addEventListener('click', () => loadGrades(true));
      return;
    }
  }
  renderGrades();
}

/** Оценки предмета, отфильтрованные по выбранной четверти. */
function filtered(subject) {
  if (state.gradeFilter === 'all') return subject.marks;
  return subject.marks.filter((mark) => mark.quarter === state.gradeFilter);
}

function average(marks) {
  let total = 0;
  let weights = 0;
  for (const mark of marks) {
    const value = Number(mark.mark);
    if (!Number.isFinite(value) || value < 1 || value > 10) continue;
    const weight = Number(mark.weight) > 0 ? Number(mark.weight) : 1;
    total += value * weight;
    weights += weight;
  }
  return weights ? total / weights : null;
}

function renderGrades() {
  const chips = QUARTERS.map(
    ([key, label]) =>
      `<button class="chip ${state.gradeFilter === key ? 'active' : ''}" data-quarter="${key}">${label}</button>`
  ).join('');

  const subjects = state.grades.subjects
    .map((subject) => ({ subject, marks: filtered(subject) }))
    .filter((item) => item.marks.length);

  const body = subjects.length
    ? `<div class="card">${subjects.map(subjectRow).join('')}</div>`
    : '<div class="card"><div class="empty">За выбранный период оценок нет</div></div>';

  $('gradesContent').innerHTML = `<div class="chips">${chips}</div>${body}`;

  $('gradesContent').querySelectorAll('[data-quarter]').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.gradeFilter = chip.dataset.quarter;
      renderGrades();
    });
  });
  $('gradesContent').querySelectorAll('[data-subject]').forEach((row) => {
    row.addEventListener('click', () => openSubject(row.dataset.subject));
  });
}

function subjectRow({ subject, marks }) {
  const avg = average(marks);
  const badges = marks
    .slice(-6)
    .map((mark) => `<span class="${markClass(mark.mark)}">${esc(mark.mark)}</span>`)
    .join('');
  return `<div class="subject-row" data-subject="${esc(subject.subject)}">
      <span class="subject-name">${esc(subject.subject)}</span>
      <span class="subject-marks">${badges}</span>
      <span class="avg ${avgClass(avg)}">${avg ? avg.toFixed(2) : '—'}</span>
    </div>`;
}

function openSubject(name) {
  const subject = state.grades.subjects.find((item) => item.subject === name);
  if (!subject) return;
  const marks = filtered(subject);
  const avg = average(marks);

  const rows = marks
    .slice()
    .sort((a, b) => (a.date < b.date ? 1 : -1))
    .map(
      (mark) => `<div class="row">
          <span>${esc(shortDate(mark.date))} · ${esc(mark.title)}${
            mark.weight > 1 ? ` <span class="muted small">вес ${mark.weight}</span>` : ''
          }</span>
          <span class="${markClass(mark.mark)}">${esc(mark.mark)}</span>
        </div>`
    )
    .join('');

  openSheet(
    name,
    `<div class="row"><span class="label">Средний балл</span>
       <span class="avg ${avgClass(avg)}">${avg ? avg.toFixed(2) : '—'}</span></div>
     <div class="row"><span class="label">Всего оценок</span><span>${marks.length}</span></div>
     <div class="card-title" style="margin-top:14px">Все оценки</div>${rows}`
  );
}
