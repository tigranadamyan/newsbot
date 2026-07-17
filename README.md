# NewsBot — Personal Anti-Doomscrolling Digest

Минималистичный Telegram-бот. Слушает канал Meduza через Telethon, анализирует новости
и отправляет утренний/вечерний дайджест — без бесконечной ленты.

## Как это работает

```
Telegram Channel (Meduza)
        │
        ▼
  Telethon Listener ──► SQLite
        │
        ▼
  News Analyzer (категории, важность, анти-кликбейт)
        │
        ▼
  Digest Generator
        │
        ▼
  aiogram Bot ──► Ваш Telegram (09:00 / 20:00 UTC)
```

## Быстрый старт (Docker)

```bash
# 1. Склонировать
git clone <repo> && cd newsbot

# 2. Создать .env (см. ниже)
cp .env.example .env

# 3. Запустить
docker compose up -d
```

## Быстрый старт (без Docker)

```bash
pip install -r requirements.txt
cp .env.example .env
# Заполнить .env
python main.py
```

## Настройка

Нужны **два** набора Telegram-данных:

### 1. Бот (aiogram) — отправляет дайджесты вам

Создайте бота через [@BotFather](https://t.me/BotFather):
```
BOT_TOKEN=123456:ABC-DEF...
```

### 2. Клиент (Telethon) — читает канал Meduza

Получите `api_id` и `api_hash` на [my.telegram.org/apps](https://my.telegram.org/apps):
```
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
MEDUZA_CHANNEL=meduzalive
```

При первом запуске Telethon запросит номер телефона и код подтверждения
(сохраняется в сессионный файл `data/newsbot_session.session`).

### 3. Ваш user ID

Узнайте через [@userinfobot](https://t.me/userinfobot):
```
TELEGRAM_USER_ID=123456789
```

### 4. LLM (опционально)

```
LLM_PROVIDER=openai          # или ollama
OPENAI_API_KEY=sk-...        # для OpenAI
```

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие |
| `/news`  | Последние важные новости |
| `/digest` | Дайджест прямо сейчас |

## Структура

```
.
├── main.py                     # python main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── app/
    ├── main.py                 # Точка входа: DB → scheduler → Telethon → aiogram
    ├── config.py               # Конфигурация из .env
    ├── bot/
    │   └── telegram.py         # aiogram-бот
    ├── database/
    │   ├── db.py               # Async SQLAlchemy + SQLite
    │   └── models.py           # Модель News
    ├── services/
    │   ├── telethon_listener.py # Слушатель канала Meduza
    │   ├── news_analyzer.py    # Анализ + LLM-адаптер
    │   └── digest.py           # Генератор дайджестов
    ├── scheduler/
    │   └── tasks.py            # APScheduler (анализ + дайджесты)
    └── utils/
```

## Принципы

- Один процесс, одна команда, никаких микросервисов
- SQLite — без PostgreSQL/Redis
- Telethon читает канал, aiogram отправляет дайджест
- Только важное, никакого скроллинга
