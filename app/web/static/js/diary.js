// Дневник: неделя, полоса дней, уроки с оценками и заданиями.
'use strict';

import {
  $, WEEKDAYS, api, attachmentsHtml, errorCard, esc, escRich, isoToday,
  longDate, markClass, parseIso, shortDate, skeleton, state,
} from './core.js';
import { openSheet } from './sheet.js';

export async function loadDiary(force = false) {
  const container = $('diaryContent');
  if (!state.diary || state.diary.week !== state.week || force) {
    container.innerHTML = skeleton();
    try {
      const { data } = await api(`/api/diary?week=${state.week}`);
      state.diary = data;
    } catch (error) {
      container.innerHTML = errorCard(error, 'diaryRetry');
      $('diaryRetry')?.addEventListener('click', () => loadDiary(true));
      renderWeekLabel();
      return;
    }
  }
  renderWeekLabel();
  renderDayStrip();
  renderDay();
}

/** Понедельник недели, смещённой на state.week от текущей. */
function weekStart() {
  const base = new Date();
  const shift = (base.getDay() + 6) % 7;
  base.setDate(base.getDate() - shift + state.week * 7);
  base.setHours(0, 0, 0, 0);
  return base;
}

function weekDates() {
  const monday = weekStart();
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date(monday);
    date.setDate(monday.getDate() + index);
    return date;
  });
}

function isoOf(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function renderWeekLabel() {
  const dates = weekDates();
  $('weekLabel').textContent = `${shortDate(isoOf(dates[0]))} — ${shortDate(isoOf(dates[6]))}`;
}

function dayByIso(iso) {
  return (state.diary?.days || []).find((day) => day.date === iso) || null;
}

function renderDayStrip() {
  const today = isoToday();
  const dates = weekDates();

  // Если выбранный день не из этой недели, выбираем разумный: сегодня,
  // либо первый день недели с уроками, либо понедельник.
  const visible = dates.map(isoOf);
  if (!state.day || !visible.includes(state.day)) {
    state.day =
      (visible.includes(today) && today) ||
      visible.find((iso) => (dayByIso(iso)?.lessons || []).length) ||
      visible[0];
  }

  $('dayStrip').innerHTML = dates
    .map((date, index) => {
      const iso = isoOf(date);
      const day = dayByIso(iso);
      const classes = [
        'day-cell',
        iso === state.day ? 'active' : '',
        iso === today ? 'today' : '',
      ].filter(Boolean).join(' ');
      const hasMarks = (day?.marks || []).length > 0;
      return `<button class="${classes}" data-day="${iso}">
          <span class="dow">${WEEKDAYS[index]}</span>
          <span class="num">${date.getDate()}</span>
          ${hasMarks ? '<span class="dot"></span>' : ''}
        </button>`;
    })
    .join('');

  $('dayStrip').querySelectorAll('[data-day]').forEach((button) => {
    button.addEventListener('click', () => {
      state.day = button.dataset.day;
      renderDayStrip();
      renderDay();
    });
  });
}

function renderDay() {
  const day = dayByIso(state.day);
  const lessons = day?.lessons || [];

  if (!lessons.length) {
    $('diaryContent').innerHTML =
      `<div class="card"><div class="card-title">${esc(longDate(state.day))}</div>
       <div class="empty">Уроков нет</div></div>`;
    return;
  }

  $('diaryContent').innerHTML = `
    <div class="card">
      <div class="card-title">${esc(longDate(state.day))}</div>
      ${lessons.map(lessonRow).join('')}
    </div>`;

  $('diaryContent').querySelectorAll('[data-lesson]').forEach((row) => {
    row.addEventListener('click', () => openLesson(Number(row.dataset.lesson)));
  });
}

function lessonRow(lesson, index) {
  const meta = [lesson.time, lesson.room && `каб. ${lesson.room}`]
    .filter(Boolean)
    .join(' · ');
  const homework = lesson.homework.map((item) => item.text).filter(Boolean).join('; ');
  const marks = lesson.marks
    .map((mark) => `<span class="${markClass(mark.mark)}">${esc(mark.mark)}</span>`)
    .join('');

  return `<div class="lesson" data-lesson="${index}">
      <span class="lesson-num">${lesson.number ?? ''}</span>
      <div class="lesson-main">
        <div class="lesson-subject">${esc(lesson.subject)}</div>
        ${meta ? `<div class="lesson-meta">${esc(meta)}</div>` : ''}
        ${homework ? `<div class="lesson-hw">📝 ${esc(homework)}</div>` : ''}
      </div>
      <div class="lesson-marks">${marks}</div>
    </div>`;
}

function openLesson(index) {
  const lesson = (dayByIso(state.day)?.lessons || [])[index];
  if (!lesson) return;

  const rows = [
    ['Дата', longDate(state.day)],
    ['Урок', lesson.number ? `№ ${lesson.number}` : ''],
    ['Время', lesson.time],
    ['Кабинет', lesson.room],
    ['Учитель', lesson.teacher],
  ]
    .filter(([, value]) => value)
    .map(([label, value]) => `<div class="row"><span class="label">${label}</span><span>${esc(value)}</span></div>`)
    .join('');

  const marks = lesson.marks.length
    ? `<div class="card-title" style="margin-top:14px">Оценки</div>` +
      lesson.marks
        .map(
          (mark) => `<div class="row">
              <span>${esc(mark.title)}${mark.weight > 1 ? ` <span class="muted small">вес ${mark.weight}</span>` : ''}</span>
              <span class="${markClass(mark.mark)}">${esc(mark.mark)}</span>
            </div>`
        )
        .join('')
    : '';

  const homework = lesson.homework.length
    ? `<div class="card-title" style="margin-top:14px">Задание</div>` +
      lesson.homework
        .map(
          (item) =>
            `<div style="margin-bottom:8px">${escRich(item.text) || '<span class="muted">Без текста</span>'}
             ${attachmentsHtml(item.attachments)}</div>`
        )
        .join('')
    : '';

  openSheet(lesson.subject, rows + marks + homework);
}

export function initDiary() {
  $('weekPrev').addEventListener('click', () => {
    state.week -= 1;
    state.day = null;
    loadDiary();
  });
  $('weekNext').addEventListener('click', () => {
    state.week += 1;
    state.day = null;
    loadDiary();
  });
  $('weekLabel').addEventListener('click', () => {
    // Возврат к текущей неделе одним нажатием: пролистав месяц назад,
    // искать дорогу обратно стрелками неудобно.
    state.week = 0;
    state.day = null;
    loadDiary();
  });
}
