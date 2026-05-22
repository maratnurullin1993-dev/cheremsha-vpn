# Deploy Guide

## Local Run On Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Mini app:

```text
http://127.0.0.1:8000
```

Health check:

```powershell
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## Create `.env`

Copy the example file:

```powershell
Copy-Item .env.example .env
```

On Linux/VPS:

```bash
cp .env.example .env
```

Then edit `.env` and set real values:

```env
BOT_TOKEN=your_bot_token
BOT_USERNAME=cheremsha_connect_bot
TELEGRAM_BOT_URL=https://t.me/your_bot_username
TELEGRAM_PROXY_URL=
ADMIN_ID=your_telegram_user_id
ADMIN_IDS=218032420,996045307
ADMIN_API_TOKEN=change_me_to_long_random_value
WEBAPP_URL=https://your-domain.example
PUBLIC_BASE_URL=https://your-domain.example
VPN_PROTOCOL=vless
VPN_HOST=78.17.76.184
VPN_PORT=8443
VPN_NETWORK=ws
VPN_SECURITY=none
VPN_WS_PATH=/
VPN_FLOW=
XRAY_CONFIG_PATH=/usr/local/x-ui/bin/config.json
XUI_DB_PATH=/etc/x-ui/x-ui.db
XUI_API_BASE_URL=http://host.docker.internal:2053
XUI_API_USERNAME=your_xui_username
XUI_API_PASSWORD=your_xui_password
XUI_API_INBOUND_ID=1
XRAY_RESTART_COMMAND=
MAX_USERS=20
```

Use `DEV_MODE=true` only for local development. On VPS use `DEV_MODE=false`.

`TELEGRAM_PROXY_URL` is optional. If it is empty, the bot connects to Telegram directly.

For local testing in Russia, you can set it to your local SOCKS proxy from v2rayN, for example:

```env
TELEGRAM_PROXY_URL=socks5://127.0.0.1:10808
```

This local proxy is only for development on your Windows machine. On VPS/Docker, usually leave it empty:

```env
TELEGRAM_PROXY_URL=
```

## Run On VPS With Docker

Install Docker and Docker Compose plugin, clone the repository, then create `.env`:

```bash
git clone <your-github-repo-url>
cd <project-folder>
cp .env.example .env
nano .env
```

Build and start:

```bash
docker compose up -d --build
```

Open:

```text
http://your-server-ip:8000
```

For production Telegram Mini App, `WEBAPP_URL` should be a public HTTPS URL.
In Docker/VPS it is read from `.env` through `docker-compose.yml`.

## Personal VPN Keys

Each Telegram user has at most one active VPN UUID. The active UUID is stored on the user record in SQLite and is used to build the user's personal VLESS link, QR code, expiry date, and traffic counters.

When a user already has an active key, the app reuses that UUID and shows the existing key data. It must not create a new UUID on every login or every mini app open: doing that would leave old clients in Xray, break existing device profiles, and inflate the active key count.

When access is expired or disabled, a new paid activation can create a new UUID. On creation the app logs in to x-ui Web API, calls `addClient` for `XUI_API_INBOUND_ID`, verifies that the client exists, stores the key in SQLite, and returns the personal VLESS link. Direct DB/config writes are fallback/debug only and must not be the production path.

For the current x-ui VLESS over WebSocket inbound, use:

```env
VPN_PROTOCOL=vless
VPN_HOST=78.17.76.184
VPN_PORT=8443
VPN_NETWORK=ws
VPN_SECURITY=none
VPN_WS_PATH=/
VPN_FLOW=
XRAY_CONFIG_PATH=/usr/local/x-ui/bin/config.json
XUI_DB_PATH=/etc/x-ui/x-ui.db
XUI_API_BASE_URL=http://host.docker.internal:2053
XUI_API_USERNAME=your_xui_username
XUI_API_PASSWORD=your_xui_password
XUI_API_INBOUND_ID=1
```

The app does not create or modify inbounds. It only uses the x-ui Web API to append/remove clients in the existing inbound `id=1`, `protocol=vless`, `port=8443`.

Generated link format:

```text
vless://UUID@78.17.76.184:8443?type=ws&security=none&path=%2F&encryption=none#NAME
```

## Test Admin Access Without Stars

Set your Telegram user id in `.env`:

```env
ADMIN_ID=123456789
ADMIN_IDS=123456789,987654321
```

Open the Mini App from that Telegram account. The app will show an `Админ` block with the `Выдать тестовый доступ` button.

The button calls:

```http
POST /api/admin/grant-test-access
```

The endpoint validates Telegram Mini App `initData`, compares the authenticated `telegram_user_id` with `ADMIN_IDS` plus legacy `ADMIN_ID`, and grants test access without Telegram Stars.

Test access parameters:

```text
7 days
10 GB
```

If the admin already has an active VPN key, the endpoint does not create a second UUID. It returns the existing key, QR, expiry date, traffic balance, and connection instructions through the normal Mini App UI.

## Admin Panel

The Mini App shows the `Админ` button only to Telegram accounts whose `telegram_user_id` is listed in `ADMIN_IDS` from `.env`. Legacy `ADMIN_ID` also works as a fallback.

Admin panel endpoints use Telegram Mini App `initData` authentication and also compare the authenticated Telegram user id with `ADMIN_IDS` plus legacy `ADMIN_ID`. Regular users do not see the admin button and receive `403` from admin panel API calls.

The panel shows users with:

- `telegram_user_id`
- `username` / `first_name`
- access status
- expiry date
- traffic limit
- used traffic
- device/key id

User card actions:

- grant test access
- renew for 7 days
- disable access
- delete VPN key/device
- show/copy VPN key

The delete action disables the device/key through the existing VPN disable path and removes the UUID from the x-ui inbound `settings.clients` array.

## Update Through `git pull`

```bash
cd <project-folder>
git pull
docker compose up -d --build
```

## Rebuild Container

```bash
docker compose build --no-cache
docker compose up -d
```

## View Logs

```bash
docker compose logs -f vpn-mini-app
```

Last 100 lines:

```bash
docker compose logs --tail=100 vpn-mini-app
```

## Restart Service

```bash
docker compose restart vpn-mini-app
```

Stop and start:

```bash
docker compose down
docker compose up -d
```

## Dev/Test Checklist

- Check `/health`: `curl http://127.0.0.1:8000/health`
- Check mini app: open `http://127.0.0.1:8000`
- Check bot `/start` in Telegram
- Check key generation
- Check QR generation
