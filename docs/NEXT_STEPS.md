# План дальнейших действий

## Статус: Интеграции настроены

Система полностью функциональна:
- Генерация Stories с Ken Burns эффектом
- Генерация Posts
- Anti-repeat система
- История публикаций
- **Telegram Bot: `@tours_batumi_mod_bot`** - НАСТРОЕН
- **Instagram API: `@tours.batumi`** - НАСТРОЕН
- **Media hosting: `adatranslate.com/tours-media/`** - НАСТРОЕН

---

## Приоритет 1: Наполнение медиа-контентом

### 1.1. Фото (цель: 500+ штук)

| Категория | Папка | Минимум фото | Статус |
|-----------|-------|--------------|--------|
| Горная Аджария | `mountain_adjara/` или `Горная Аджария/` | 50 | |
| Архитектура | `architecture/` или `Архитектура/` | 50 | |
| Кухня | `cuisine/` или `Кухня/` | 50 | |
| Природа | `nature/` или `Природа/` | 50 | |
| Транспорт | `transport/` или `Транспорт/` | 30 | |
| Пляжи | `beaches/` или `Пляжи/` | 40 | |
| ... | ... | ... | |

Требования к фото:
- Минимум 1080px по ширине
- Вертикальные (9:16) предпочтительнее
- JPEG качество 85%+

### 1.2. Музыка (цель: 30-50 треков)

```
media/music/
├── traditional/     # Народные мелодии
├── modern/          # Современная грузинская
└── instrumental/    # Инструментальная
```

Требования:
- Длительность: 15-30 секунд
- Формат: MP3, 256 kbps+
- Плавные fade in/out
- Royalty-free

---

## Приоритет 2: Финальные настройки на сервере

### 2.1. Перезагрузить nginx (применить конфиг)

```bash
# На сервере adatranslate.com
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

### 2.2. Добавить cron для очистки старых файлов

```bash
# На сервере, в crontab:
0 4 * * * find /opt/translator/tours-media -type f -mtime +3 -delete
```

---

## Приоритет 3: Тестовая публикация

После загрузки медиа-контента:

```bash
# Сгенерировать тестовую Story
python main.py generate

# Если всё ок — тест публикации
python main.py publish-test
```

---

## Приоритет 4: Деплой

### 4.1. Сервер

Минимальные требования:
- 1 CPU, 2GB RAM
- 20GB SSD (для медиа)
- Ubuntu 22.04

Рекомендации:
- VPS от Hetzner, DigitalOcean, или аналоги
- ~$5-10/месяц

### 4.2. Docker

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py", "run"]
```

### 4.3. Systemd сервис (альтернатива Docker)

```ini
[Unit]
Description=tours.batumi Instagram Bot
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/tours-batumi
ExecStart=/opt/tours-batumi/venv/bin/python main.py run
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Приоритет 5: Мониторинг

### 5.1. Логирование

Текущее: файл `logs/app.log`

Улучшение: отправка критических ошибок в Telegram модератору.

### 5.2. Алерты

Добавить уведомления при:
- Ошибке генерации
- Ошибке публикации
- Исчерпании пула фото/музыки
- Истечении токена Instagram

---

## Чеклист перед запуском

- [ ] 500+ фото по категориям
- [ ] 30+ музыкальных треков
- [x] Telegram бот настроен и работает
- [x] Instagram API токен получен (long-lived, 60 дней)
- [x] Хостинг для видео настроен
- [x] Nginx перезагружен на сервере (CI/CD deploy)
- [x] Cron для очистки добавлен (файлы старше 3 дней)
- [x] Тестовая публикация успешна ✅ (ID: 18039064748726858)
- [ ] Сервер развёрнут
- [ ] Мониторинг настроен

---

## Phase 2 (Future)

### Reels
- Слайдшоу из нескольких фото
- Crossfade переходы
- Субтитры

### Аналитика
- Трекинг охвата и вовлечённости
- A/B тестирование времени публикации
- Отчёты в Telegram

### Английская версия
- Отдельный канал
- Промты на английском
- Перевод через API

---

*Обновлено: 2026-01-13*
