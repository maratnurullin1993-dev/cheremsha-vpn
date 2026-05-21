# ЧЕРЕМША VPN Mini App

Telegram bot + Telegram Mini App для выдачи VPN-доступа.

Стек: Python, FastAPI, aiogram, SQLite, HTML/CSS/JS, `.env`.

## Локальный запуск backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Mini app будет доступен локально:

```text
http://127.0.0.1:8000
```

Если `BOT_TOKEN` не задан, backend все равно запускается в dev mode. В этом режиме Telegram bot просто не стартует.

## Настройка Telegram bot и Mini App

Открой `.env` и заполни:

```env
BOT_TOKEN=токен_бота_из_BotFather
TELEGRAM_PROXY_URL=
ADMIN_ID=твой_telegram_user_id
WEBAPP_URL=http://127.0.0.1:8000
PUBLIC_BASE_URL=http://127.0.0.1:8000
MAX_ACTIVE_KEYS=20
```

`TELEGRAM_PROXY_URL` опционален. Если он пустой, бот подключается к Telegram напрямую.

Для локального теста в РФ можно указать SOCKS proxy от v2rayN:

```env
BOT_TOKEN=8844542021:...
TELEGRAM_PROXY_URL=socks5://127.0.0.1:10808
ADMIN_ID=218032420
WEBAPP_URL=http://127.0.0.1:8000
```

На VPS/Docker обычно оставь:

```env
TELEGRAM_PROXY_URL=
```

Не коммить `.env`: файл уже добавлен в `.gitignore`.

## Запуск бота

В отдельном терминале:

```powershell
.\.venv\Scripts\Activate.ps1
python run_bot.py
```

Команда `/start` отвечает:

```text
ЧЕРЕМША VPN
```

и показывает кнопку `Открыть VPN`, которая открывает URL из `WEBAPP_URL`.

## Admin

Команда `/admin` доступна только пользователю с `ADMIN_ID`.

Она показывает:

- активных ключей `N / MAX_ACTIVE_KEYS`;
- пользователей в базе;
- кнопку `Обновить`;
- кнопку `Отключить пользователя позже`.

## BotFather

Для production Telegram Mini App обычно нужен публичный HTTPS URL.

В `@BotFather`:

1. `/mybots`
2. Выбери бота.
3. `Bot Settings` -> `Configure Mini App` или `Menu Button`.
4. Укажи публичный `WEBAPP_URL`.

Для локальной проверки можно держать `WEBAPP_URL=http://127.0.0.1:8000`, но открытие внутри Telegram на реальном устройстве обычно потребует HTTPS-туннель или VPS.

## Полезные переменные

```env
DEV_MODE=true
DATABASE_PATH=data/app.sqlite3
ADMIN_API_TOKEN=change_me_long_random_token
SUPPORT_URL=https://t.me/your_username
DEFAULT_7D_TRAFFIC_GB=10
DEFAULT_30D_TRAFFIC_GB=50
```

## Персональные VPN-ключи

У каждого Telegram user может быть максимум один активный VPN UUID. Если активный ключ уже есть, mini app показывает существующую VLESS-ссылку, QR, срок действия и остаток трафика, не создавая новый UUID при каждом входе.

Новый UUID создаётся только когда доступа ещё нет, либо старый доступ истёк или отключён. В production новый UUID сохраняется в SQLite, добавляется в Xray config из `XRAY_CONFIG_PATH`, после чего выполняется `XRAY_RESTART_COMMAND`. Для локальной разработки можно оставить `XRAY_CONFIG_PATH=` пустым: тогда ключ создаётся только в SQLite.

В production поставь:

```env
DEV_MODE=false
WEBAPP_URL=https://your-domain.example
PUBLIC_BASE_URL=https://your-domain.example
```
