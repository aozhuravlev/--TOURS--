# tours.batumi Instagram Automation

Автоматизированная система генерации и публикации контента для Instagram-канала **tours.batumi**.

## Возможности

- **Ежедневные Stories** — видео (фото + грузинская музыка) с Ken Burns эффектом
- **Посты в ленту** — развёрнутые тексты с хештегами
- **Умный подбор тем** — 12 категорий, 87+ подтем с защитой от повторов
- **Актуальные факты** — интеграция с Perplexity API для поиска информации
- **Живые тексты** — DeepSeek API с двухэтапной генерацией (создание + humanization)
- **Модерация** — Telegram-бот для проверки контента перед публикацией
- **Планировщик** — автоматическая генерация и публикация по расписанию

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка

Скопируйте `.env.example` в `.env` и заполните API ключи:

```bash
cp .env.example .env
```

Обязательные ключи:
- `PERPLEXITY_API_KEY` — для поиска актуальной информации
- `DEEPSEEK_API_KEY` — для генерации текста

Опциональные (для полной автоматизации):
- `TELEGRAM_BOT_TOKEN` — токен бота для модерации
- `TELEGRAM_MODERATOR_CHAT_ID` — ID чата модератора
- `INSTAGRAM_*` — креды для Instagram Graph API

### 3. Добавьте медиа-контент

```
media/
├── photos/           # Фото по категориям
│   ├── Горная Аджария/
│   ├── Архитектура/
│   ├── Кухня/
│   └── ...
└── music/            # Грузинские мелодии (15-30 сек)
```

### 4. Запуск

```bash
# Сгенерировать Story сейчас
python main.py generate

# Сгенерировать Post
python main.py generate --post

# Без Ken Burns эффекта (статичное фото)
python main.py generate --static

# Показать статистику
python main.py stats

# Запустить полную систему
python main.py run
```

## Архитектура

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Topic Selector │────▶│  News Fetcher   │────▶│ Text Generator  │
│   (topics.json) │     │  (Perplexity)   │     │   (DeepSeek)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                         │
┌─────────────────┐     ┌─────────────────┐              │
│  Media Manager  │────▶│ Video Composer  │◀─────────────┘
│  (photos/music) │     │    (FFmpeg)     │
└─────────────────┘     └─────────────────┘
                                │
                                ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Content History │◀────│   Orchestrator  │────▶│  Telegram Bot   │
│  (anti-repeat)  │     │                 │     │  (moderation)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │    Publisher    │
                        │  (Instagram)    │
                        └─────────────────┘
```

## Workflow

1. **Утро День 1 (08:00-09:00):** Система генерирует контент на завтра
2. **Модерация (~24 часа):** Модератор проверяет контент в Telegram
3. **Утро День 2 (08:00-09:00):** Система публикует одобренный контент
4. **Fallback:** Если модератор не ответил — автопубликация

## Структура проекта

```
tours-batumi-bot/
├── main.py                 # Точка входа
├── .env                    # API ключи (не в git!)
├── requirements.txt        # Зависимости
│
├── config/
│   ├── settings.py         # Загрузка конфигурации
│   └── topics.json         # Темы и подтемы
│
├── prompts/                # Редактируемые промты
│   ├── story_generator.txt
│   ├── story_humanizer.txt
│   ├── post_generator.txt
│   └── post_humanizer.txt
│
├── src/
│   ├── orchestrator.py     # Главный координатор
│   ├── scheduler.py        # Планировщик
│   └── modules/
│       ├── topic_selector.py
│       ├── news_fetcher.py
│       ├── text_generator.py
│       ├── media_manager.py
│       ├── video_composer.py
│       ├── content_history.py
│       ├── telegram_bot.py
│       └── publisher.py
│
├── media/
│   ├── photos/             # Фото по категориям
│   └── music/              # Музыкальные треки
│
├── output/                 # Сгенерированные видео
├── data/
│   └── content_history.json
├── logs/
└── docs/
```

## Настройка промтов

Промты хранятся в `prompts/*.txt` и легко редактируются:

- `story_generator.txt` — генерация текста для Story (до 100 символов)
- `story_humanizer.txt` — "очеловечивание" текста Story
- `post_generator.txt` — генерация поста (500-800 символов + хештеги)
- `post_humanizer.txt` — "очеловечивание" поста

Переменные в промтах:
- `{topic}` — название категории
- `{subtopic}` — название подтемы
- `{facts}` — факты от Perplexity
- `{raw_text}` — сгенерированный текст (для humanizer)

## Anti-Repeat система

Система предотвращает повторы:

| Элемент | Cooldown |
|---------|----------|
| Подтема | 7 дней |
| Фото | 30 дней |
| Музыка | 14 дней |

Настраивается в `.env`:
```
SUBTOPIC_COOLDOWN_DAYS=7
PHOTO_COOLDOWN_DAYS=30
MUSIC_COOLDOWN_DAYS=14
```

## API

### Perplexity (поиск фактов)
- Модель: `sonar` (с онлайн-поиском)
- Использование: ~1-2 запроса на генерацию

### DeepSeek (генерация текста)
- Модель: `deepseek-chat`
- Использование: 2 запроса на генерацию (raw + humanize)

## Лицензия

Private project for tours.batumi
