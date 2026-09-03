// Точка входа: вкладки, шапка, интеграция с Telegram.
'use strict';

import { $, banner, school, state, student, tg } from './core.js';
import { initDiary, loadDiary } from './diary.js';
import { loadGrades } from './grades.js';
import { loadHomework } from './homework.js';
import { loadMail } from './mail.js';
import { loadCalc } from './calc.js';
import { applyStoredTheme, loadProfile, openChildSwitch } from './profile.js';
import { closeSheet, initSheet } from './sheet.js';

const TABS = {
  diary: { title: 'Дневник', load: loadDiary },
  grades: { title: 'Оценки', load: loadGrades },
  homework: { title: 'Домашние задания', load: loadHomework },
  mail: { title: 'Почта', load: loadMail },
  calc: { title: 'Калькулятор', load: loadCalc },
  profile: { title: 'Ещё', load: loadProfile },
};

function switchTab(name) {
  state.tab = name;
  document.querySelectorAll('.panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === `panel-${name}`);
  });
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.tab === name);
  });
  $('topTitle').textContent = name === 'diary' ? student || TABS[name].title : TABS[name].title;
  banner('');
  TABS[name].load();
  updateBackButton();
}

function updateBackButton() {
  if (!tg?.BackButton) return;
  // Аппаратная кнопка «назад» внутри Telegram закрывает приложение целиком,
  // поэтому свою навигацию отдаём его кнопке.
  if (state.tab === 'diary') tg.BackButton.hide();
  else tg.BackButton.show();
}

function initTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();

  const theme = tg.themeParams || {};
  const root = document.documentElement.style;
  if (theme.bg_color) root.setProperty('--bg', theme.bg_color);
  if (theme.secondary_bg_color) root.setProperty('--card', theme.secondary_bg_color);
  if (theme.text_color) root.setProperty('--text', theme.text_color);
  if (theme.hint_color) root.setProperty('--text2', theme.hint_color);

  tg.BackButton.onClick(() => {
    if (!$('sheet').hidden) closeSheet();
    else switchTab('diary');
  });
}

function initChrome() {
  document.querySelectorAll('.nav-item').forEach((item) => {
    item.addEventListener('click', () => switchTab(item.dataset.tab));
  });

  $('refreshBtn').addEventListener('click', async () => {
    const button = $('refreshBtn');
    button.classList.add('spinning');
    banner('');
    // Сбрасываем кэш текущей вкладки, остальные обновятся при переходе.
    state[state.tab === 'calc' ? 'grades' : state.tab] = null;
    await TABS[state.tab].load(true);
    button.classList.remove('spinning');
  });

  $('childBtn').addEventListener('click', openChildSwitch);
}

async function start() {
  applyStoredTheme();
  initTelegram();
  initSheet();
  initDiary();
  initChrome();

  $('topTitle').textContent = student || 'Дневник';
  switchTab('diary');

  // Профиль подгружаем сразу, но тихо: от него зависит кнопка выбора
  // ребёнка в шапке, а ждать открытия вкладки «Ещё» ради этого незачем.
  try {
    await loadProfile();
    if ((state.profile?.students || []).length > 1) $('childBtn').hidden = false;
  } catch {
    /* профиль не критичен для остальных экранов */
  }
}

start();
