# Адал қоғам AI — бот-навигатор по внутренней политике РК

Telegram-бот на основе RAG: находит в официальных источниках (Конституция 2026, законы, Послания, концепции) ответ на вопрос
на русском или казахском, ссылается на первоисточник и честно сообщает, если подтверждённой информации нет.

## Архитектура

```
Telegram ─► aiogram (app/bot.py) ─► RAG (app/rag.py) ─► PostgreSQL + pgvector (чанки, документы, query_log)
                  │                        │
              голос (ogg)             Gemini: эмбеддинги + генерация (app/llm.py)
                  └─► Gemini транскрибация
```

- **Frontend:** Telegram-клиент (текст и голос).
- **Backend:** Python, aiogram 3.
- **Database:** PostgreSQL 16 + pgvector (HNSW, косинусная дистанция). Таблицы: `documents`, `chunks`, `query_log`.
- **AI:** Gemini (`gemini-embedding-001` для поиска, `gemini-2.5-flash` для ответа и распознавания речи).

## Логика ответа
1. Определяем язык вопроса (kk/ru).
2. Эмбеддинг вопроса → top-K фрагментов из pgvector.
3. Отбрасываем фрагменты с дистанцией > `MAX_DISTANCE`. Если ничего не осталось — ответ «нет данных» без обращения к LLM.
4. LLM получает только найденные фрагменты и обязан отвечать по ним со ссылками [n]; если ответа нет — `NO_INFO`.
5. Для понятий из Конституции 2026 бот обязан указать статью/раздел.
6. Запрос пишется в `query_log` (аналитика, команда `/stats` для админов).

## Запуск
```bash
cp .env.example .env            # заполнить TELEGRAM_BOT_TOKEN и GEMINI_API_KEY
docker compose up -d            # PostgreSQL + pgvector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# положить документы в data/sources/ (см. data/sources/README.md)
python -m app.ingest            # загрузка базы знаний
python -m app.bot               # запуск бота
```

## Безопасность
- Секреты только в `.env` (в `.gitignore`).
- Ответы строго из базы источников; без подтверждения — отказ отвечать.
- Ограничение длины вопроса, обработка ошибок API/БД, `/stats` только для `ADMIN_IDS`.
- В `query_log` хранится id пользователя Telegram и текст вопроса (персональные данные не собираются).

## Источники
Только официальные: adilet.zan.kz, akorda.kz, egov.kz (список — в `data/sources/`).
