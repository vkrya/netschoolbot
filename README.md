# NetSchool Bot 🎓

Telegram-бот и PWA-приложение для «Сетевого города. Образование»: дневник, оценки,
домашние задания, расписание, школьная почта и уведомления о новых оценках.

Выделен из проекта [max_tg_forw_sch](https://github.com/vkrya/max_tg_forw_sch) —
там остался только форвардер Max↔Telegram с общим чекером оценок в группу.

Домен: **https://netschool.ikrya.ru**

## Возможности

### Бот
- Вход в «Сетевой город»: логин/пароль, Госуслуги (в т.ч. с MFA) и вход по QR-коду
- Выбор региона и школы — **у каждого пользователя своя школа**, значения по умолчанию нет
- Уведомления о новых оценках, их изменениях и удалениях
- Домашние задания с вложениями, расписание, звонки, школьная почта
- Статистика: средние баллы, недельная сводка, калькулятор нужных оценок
- Несколько детей в одном аккаунте — переключение между учениками
- Фильтры по типам работ и предметам, тихие часы, настраиваемый интервал проверки

### Мини-приложение (PWA)
- Дневник, оценки, итоговые отметки, почта с вложениями
- Установка на домашний экран, свои иконки и галерея иконок
- Web push-уведомления (VAPID)
- Вход по постоянной PWA-ссылке с подтверждением кодом в Telegram

### Школа выбирается пользователем
Школы и региона по умолчанию нет: при `/login` человек выбирает свой регион
и школу сам. Общий чекер класса («в группу») остался в `max_tg_forw_sch`.

### Веб-панель
Терминал, просмотр логов службы, файловый менеджер, управление сервисом.

## Структура

```
run.py                        точка входа (бот + веб)
netschoolbot/
├── config.py                 все настройки из окружения
├── logging_setup.py          логи + отправка админу в Telegram
├── storage.py                пользователи, токены, коды, галерея
├── utils.py                  даты, нормализация, форматирование
├── webpush.py                web push (VAPID)
├── netschool/
│   ├── client.py             сессии «Сетевого города», ошибки, ученики
│   ├── grades.py             сбор и рендер оценок/ДЗ/расписания
│   └── notifier.py           GradeNotifier — цикл проверки
├── bot/
│   ├── app.py                сборка и запуск бота
│   ├── runtime.py            общее состояние (боты, задачи, кэши)
│   ├── tasks.py              чекеры пользователей, повтор входа
│   ├── keyboards.py          клавиатуры
│   ├── helpers.py            общие операции обработчиков
│   ├── esia.py               коды подтверждения Госуслуг
│   └── handlers/             auth, diary, menu, settings, gallery
└── web/
    ├── app.py                Flask, авторизация панели
    ├── miniapp.py            PWA и API мини-приложения
    ├── files.py              файловый менеджер
    ├── terminal.py           PTY, логи, управление службой
    └── templates.py          HTML-шаблоны
```

## Установка

```bash
git clone https://github.com/vkrya/netschoolbot.git /opt/netschoolbot
cd /opt/netschoolbot
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env
./venv/bin/python scripts/generate_vapid_keys.py   # ключи для push
./venv/bin/python run.py
```

### Перенос данных из старого проекта

```bash
./venv/bin/python scripts/migrate_from_forwarder.py /opt/max_tg_forw_sch/forwarder_data
```

Переносятся пользователи, PWA-токены, иконки, сессии, кэш дневника и `sent_grades.json`.

### Сервер

```bash
cp deploy/systemd/netschoolbot.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now netschoolbot

cp deploy/nginx/netschool.ikrya.ru.conf /etc/nginx/sites-available/
ln -s /etc/nginx/sites-available/netschool.ikrya.ru.conf /etc/nginx/sites-enabled/
certbot --nginx -d netschool.ikrya.ru
nginx -t && systemctl reload nginx
```

Веб слушает `127.0.0.1:8283`, приложение смонтировано в корень домена
(`/mini/netschool`, `/api/mini/netschool/*`, `/socket.io/`).

## Команды бота

| Команда | Описание |
|---|---|
| `/start`, `/menu` | главное меню |
| `/login`, `/relogin`, `/logout` | вход и смена школы |
| `/dz`, `/rasp`, `/bell` | домашние задания, расписание, звонки |
| `/grades`, `/avg`, `/mystats`, `/weeksummary` | оценки и статистика |
| `/mail`, `/mail_on`, `/mail_off` | школьная почта |
| `/settings`, `/interval`, `/filter`, `/subjectfilter`, `/quiethours` | настройки |
| `/child` | переключение между детьми |
| `/status`, `/profile` | состояние и профиль |
| `/bugreport` | сообщить о проблеме |
| `/gallery`, `/revoke_icon` | админские: галерея иконок и отзыв доступа |

## Настройки

Все переменные описаны в [`.env.example`](.env.example). Ключевые:

- `NETSCHOOL_BOT_TOKEN` — токен бота (обязателен)
- `TG_ADMIN_ID` — админ: логи, галерея, багрепорты
- `NETSCHOOL_PUBLIC_URL` — публичный адрес (по умолчанию `https://netschool.ikrya.ru`)
- `NETSCHOOL_VAPID_*` — ключи web push
- `NETSCHOOL_DATA_DIR` — где хранить данные (по умолчанию `./data`)

Регионы, требующие прокси (например `sgo.volganet.ru`), настраиваются через
`VOLGOGRAD_PROXY` и `PROXY_REQUIRED_HOSTS` в `netschoolbot/config.py`.
