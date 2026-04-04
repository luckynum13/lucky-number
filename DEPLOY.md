# Lucky Number Bot — Инструкция по деплою
==========================================

## Что у тебя в этой папке:

```
lucky-number-bot/
├── main.py          — главный файл бота
├── payments.py      — интеграция Smart Glocal
├── database.py      — база данных
├── rooms.py         — логика комнат и игры
├── requirements.txt — зависимости Python
├── Dockerfile       — инструкция сборки
├── fly.toml         — конфиг для Fly.io
├── .env.example     — шаблон переменных (заполни сам)
├── .gitignore       — защита секретов
└── DEPLOY.md        — эта инструкция
```

---

## ШАГ 1 — GitHub (приватный репозиторий)

1. Зайди на **github.com** → Sign in / Sign up
2. Нажми **New repository** (зелёная кнопка)
3. Название: `lucky-number-bot`
4. Выбери **Private** ← ОБЯЗАТЕЛЬНО приватный!
5. Нажми **Create repository**
6. Загрузи все файлы из этой папки через кнопку **"uploading an existing file"**
7. НЕ загружай файл `.env` — он в .gitignore

---

## ШАГ 2 — Fly.io аккаунт

1. Зайди на **fly.io** → Sign Up
2. Войди через GitHub аккаунт (удобнее всего)
3. Добавь карту оплаты (нужна для активации, снимают ~$5/мес)

---

## ШАГ 3 — Создать приложение на Fly.io

1. На fly.io нажми **"Launch an App"**
2. Выбери **"Deploy from GitHub"**
3. Выбери репозиторий `lucky-number-bot`
4. Region: **Amsterdam (ams)** ← выбери именно его
5. Fly.io начнёт деплой автоматически

---

## ШАГ 4 — Установить секретные переменные

На странице твоего приложения на Fly.io:
1. Перейди в раздел **Secrets**
2. Добавь по одному (кнопка "Add Secret"):

| Имя                  | Значение                              |
|----------------------|---------------------------------------|
| BOT_TOKEN            | токен от @BotFather                   |
| WEBHOOK_URL          | https://lucky-number-bot.fly.dev      |
| SMART_GLOCAL_TOKEN   | токен от @BotFather (Smart Glocal)    |
| WEBHOOK_SECRET       | любой случайный текст (мин. 32 символа)|
| DATABASE_URL         | sqlite+aiosqlite:///data/lucky.db     |
| MINI_APP_URL         | https://yourusername.github.io/lucky-number |

3. После добавления всех секретов — нажми **Deploy**

---

## ШАГ 5 — Проверить что бот работает

1. Открой Telegram → найди своего бота
2. Отправь `/start`
3. Должен ответить с приветствием

Если не отвечает — смотри логи на Fly.io в разделе **Monitoring → Logs**

---

## ШАГ 6 — Подключить Smart Glocal к боту

1. Открой @BotFather в Telegram
2. /mybots → выбери бота → Payments
3. Выбери **Smart Glocal**
4. Следуй инструкциям — получишь `provider_token`
5. Добавь его в Fly.io Secrets как `SMART_GLOCAL_TOKEN`
6. Задеплой снова (Fly.io → Deployments → Deploy)

---

## ШАГ 7 — Настроить Smart Glocal вебхук

Скажи своему менеджеру Smart Glocal:
"Please send payment webhooks to: https://lucky-number-bot.fly.dev/webhook/smart-glocal"

---

## Обновление кода

Когда меняешь файлы — просто загрузи их на GitHub.
Fly.io автоматически задеплоит новую версию.

---

## Поддержка

Если что-то не работает:
- Логи: fly.io → твоё приложение → Monitoring
- Telegram webhook статус: https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo
