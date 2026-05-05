# Jarfish Bot — Персональный AI-ассистент

**Бот:** [@epicfish_bot](https://t.me/epicfish_bot)  
**Пользователь:** Kirill  
**Часовой пояс:** Азия/Хошимин (UTC+7, Дананг)  

## Назначение

Jarfish — персональный Telegram-бот, работающий как AI-ассистент в стиле Iron Man. Понимает естественный язык (русский), управляет задачами, календарём, напоминаниями и заметками. Есть CLI-мост для управления из командной строки.

## Архитектура

```
Things/
├── jarvis_bot.py          # Точка входа
├── config.py              # Загрузка .env
├── launch.bat             # Авто-перезапуск при падении
├── .env                   # Токены и секреты (НЕ КОММИТИТЬ!)
├── .env.example           # Шаблон конфига
├── JARFISH.md             # Этот файл
├── jarvis.db              # SQLite база
├── google_token.pickle    # OAuth токен Google Calendar
├── oauth_google.json      # OAuth клиент Google (НЕ КОММИТИТЬ!)
│
├── db/
│   ├── schema.sql         # DDL (5 таблиц + 2 view)
│   ├── database.py        # Async SQLite + миграции
│   └── repository.py      # CRUD операции
│
├── bot/
│   ├── handlers.py        # Обработчики команд, текста, голоса, фото, кнопок
│   ├── commands.py        # Бизнес-логика команд
│   ├── formatting.py      # HTML-форматирование
│   └── menu.py            # Клавиатуры и меню
│
├── cli/
│   └── console.py         # Async stdin/stdout мост
│
├── services/
│   ├── nl_parser.py       # DeepSeek NL парсер (извлекает JSON из текста)
│   ├── calendar_service.py# Google Calendar API (OAuth)
│   ├── reminder_service.py# Напоминания (reschedule повторов)
│   ├── proactive.py       # Утренний/вечерний брифинг, проверка просрочек
│   ├── idea_agent.py      # Ежедневный анализ логов и идеи по улучшению
│   ├── speech.py          # Whisper (распознавание речи)
│   ├── vision.py          # DeepSeek Vision (распознавание изображений)
│   └── affirmation.py     # Ежедневная пацанская мудрость
│
└── utils/
    └── time_utils.py      # Парсинг русских выражений времени
```

## База данных (SQLite)

5 таблиц:
- **projects** — проекты (active/paused/completed)
- **tasks** — задачи (todo/in_progress/done/blocked/cancelled) с приоритетом, due_date, тегами
- **reminders** — напоминания с триггер-временем и повторами
- **notes** — заметки с поиском
- **messages** — лог всех входящих/исходящих сообщений
- **thoughts** — лента мыслей (текст, голос, фото)

2 view:
- **v_overdue_tasks** — просроченные задачи
- **v_upcoming_reminders** — напоминания на ближайшие 24ч

## Обработка сообщений

### Команды (`/команда`)

| Команда | Действие |
|---------|----------|
| `/start` | Приветствие |
| `/help` | Список команд |
| `/tasks` | Список задач (фильтр по статусу/проекту) |
| `/task_add` | Добавить задачу |
| `/task_done` | Отметить выполненной |
| `/task_edit` | Редактировать задачу |
| `/project_add` | Создать проект |
| `/projects` | Список проектов |
| `/remind` | Создать напоминание |
| `/reminders` | Список напоминаний |
| `/remind_del` | Удалить напоминание |
| `/note` | Сохранить заметку |
| `/notes` | Поиск/список заметок |
| `/summary` | Сводка на сегодня |
| `/overdue` | Просроченные задачи |

### Свободный текст (NL-парсинг через DeepSeek LLM)

Любое не-командное сообщение отправляется в DeepSeek API с системным промптом. LLM извлекает структурированный JSON с полями:
- `events` — события для Google Calendar
- `tasks` — задачи в БД
- `reminders` — напоминания
- `notes` — заметки
- `query` — если это вопрос к данным
- `reply` — естественный ответ на русском

**Поток обработки:**
1. DeepSeek парсит сообщение → возвращает JSON
2. Если есть действия (events/tasks/reminders) → **подтверждение с кнопками OK/Нет**
3. OK → выполняет все действия, присылает результат
4. Нет → «Пришлите новый промпт», ничего не делает
5. Если только вопрос → сразу извлекает данные из БД и отвечает

### Голосовые сообщения
- Whisper (tiny model) → текст
- Дальше как свободный текст (NL-парсинг + подтверждение)

### Фотографии
- DeepSeek Vision → описание на русском
- Сохраняется в заметки

## Интеграции

### Google Calendar
- OAuth 2.0 (desktop flow)
- Создание событий с напоминаниями
- Дефолтные напоминания: popup за 30 и 10 минут
- Timezone: Asia/Ho_Chi_Minh
- При отсутствии OAuth токена → фолбэк в БД-задачи

### DeepSeek API
- **NL Parser:** модель `deepseek-chat`, temperature 0.1, max_tokens 1000
- **Vision:** модель `deepseek-chat` с image_url
- **Idea Agent:** модель `deepseek-chat`, temperature 0.7, max_tokens 1500
- **Affirmation:** модель `deepseek-chat`, temperature 1.2, max_tokens 80

### Whisper
- Локальная модель tiny для быстрого распознавания русской речи на CPU

## Проактивные функции

| Время | Событие |
|-------|---------|
| 00:05 | Перенос незавершённых задач на сегодня |
| 08:00 | Утренний брифинг (задачи на сегодня, просрочки, напоминания) |
| 09:00 | Ежедневная пацанская мудрость |
| 12:00 | Idea Agent (анализ логов + идеи по улучшению) |
| 21:00 | Вечерний обзор (что сделано, что осталось) |
| Каждые 4ч | Проверка просроченных задач |

## CLI Мост

Два asyncio.Queue между Telegram и консолью. Всё что пишется в Telegram → в консоль. Всё что пишется в консоль → обрабатывается и в консоль + в Telegram.

## Запуск

```bash
# 1. Установка зависимостей
pip install "python-telegram-bot[job-queue]>=21.9" aiosqlite httpx openai-whisper google-api-python-client google-auth-oauthlib colorama

# 2. Создать .env из .env.example и заполнить реальными ключами
cp .env.example .env

# 3. Запуск
python jarvis_bot.py
```

Для авто-перезапуска при падении: `launch.bat`

## Требования

- Python 3.13
- `python-telegram-bot[job-queue]>=21.9`
- `aiosqlite`
- `httpx`
- `openai-whisper`
- `google-api-python-client`
- `google-auth-oauthlib`
- `colorama`

## Логи

`jarvis.log` — все события, ошибки, LLM-запросы.
