from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db, payments, vpn
from app.auth import current_user, require_admin_token, require_telegram_admin_user
from app.config import get_settings
from app.qr import make_qr_png
from app.scheduler import create_scheduler


class DaysPayload(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class CreateKeyPayload(DaysPayload):
    traffic_limit: int | None = Field(default=None, ge=1)


class InvoicePayload(BaseModel):
    plan_id: str


class TrafficPayload(BaseModel):
    gb: int = Field(default=10, ge=1, le=10_000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler = create_scheduler()
    scheduler.start()

    bot_task = None
    settings = get_settings()
    if settings.bot_token:
        from app.bot import run_bot

        print(f"Telegram bot startup: polling enabled, WEBAPP_URL={settings.webapp_url}")
        bot_task = asyncio.create_task(run_bot())
        bot_task.add_done_callback(_log_bot_task_result)
    else:
        print("Telegram bot startup: BOT_TOKEN is empty, backend runs without bot.")

    yield

    scheduler.shutdown(wait=False)
    if bot_task:
        print("Telegram bot shutdown: stopping polling task.")
        if not bot_task.done():
            bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            print("Telegram bot shutdown: polling task stopped.")
        except Exception as error:
            print(f"Telegram bot shutdown: polling task already stopped with error: {error!r}")


def _log_bot_task_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error:
        print(f"Telegram bot startup: polling task stopped with error: {error!r}")
    else:
        print("Telegram bot startup: polling task finished.")


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.dev_mode else [settings.webapp_url.rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/public-config")
async def public_config() -> dict:
    return {"telegram_open_url": settings.telegram_open_url()}


@app.get("/api/me")
async def me(user: dict = Depends(current_user)) -> dict:
    node = vpn.node_status()
    return {
        "user": user,
        "node": node,
        "key": decorate_vpn_user(user) if user.get("uuid") else None,
        "capacity": capacity_summary(),
    }


@app.post("/api/keys")
async def create_key(payload: CreateKeyPayload, user: dict = Depends(current_user)) -> dict:
    if not settings.dev_mode:
        raise HTTPException(status_code=402, detail="Payment required")
    if payload.traffic_limit:
        user["traffic_limit"] = payload.traffic_limit
    try:
        updated = vpn.activate_or_extend_user_key(user, days=payload.days, traffic_limit_gb=payload.traffic_limit)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"key": decorate_vpn_user(updated), "xray_client": vpn.xray_client_payload(updated)}


@app.post("/api/admin/grant-test-access")
async def admin_grant_test_access(user: dict = Depends(require_telegram_admin_user)) -> dict:
    try:
        updated = vpn.activate_or_extend_user_key(user, days=7, traffic_limit_gb=10)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    db.log_event(
        event_type="admin_test_access",
        user_id=updated["id"],
        uuid_value=updated.get("uuid"),
        message="Admin test access granted or reused",
    )
    return {"key": decorate_vpn_user(updated), "xray_client": vpn.xray_client_payload(updated)}


@app.get("/api/admin/panel/users")
async def admin_panel_users(admin: dict = Depends(require_telegram_admin_user)) -> dict:
    users = db.search_users()
    return {
        "users": [admin_user_summary(user) for user in users],
        "capacity": capacity_summary(),
    }


@app.get("/api/admin/panel/debug")
async def admin_panel_debug(admin: dict = Depends(require_telegram_admin_user)) -> dict:
    return {
        "env": vpn.config_status(),
        "latest_key": vpn.latest_key_debug(),
        "last_provisioning_error": vpn.last_provisioning_error(),
    }


@app.get("/api/admin/panel/users/{user_id}")
async def admin_panel_user(user_id: int, admin: dict = Depends(require_telegram_admin_user)) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": admin_user_detail(user)}


@app.post("/api/admin/panel/users/{user_id}/grant-test-access")
async def admin_panel_grant_test_access(user_id: int, admin: dict = Depends(require_telegram_admin_user)) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        updated = vpn.activate_or_extend_user_key(user, days=7, traffic_limit_gb=10)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    db.log_event(
        event_type="admin_panel_test_access",
        user_id=updated["id"],
        uuid_value=updated.get("uuid"),
        message="Admin panel test access granted or reused",
    )
    return {"user": admin_user_detail(updated)}


@app.post("/api/admin/panel/users/{user_id}/renew-7d")
async def admin_panel_renew_7d(user_id: int, admin: dict = Depends(require_telegram_admin_user)) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        updated = vpn.activate_or_extend_user_key(user, days=7)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    db.log_event(
        event_type="admin_panel_renew_7d",
        user_id=updated["id"],
        uuid_value=updated.get("uuid"),
        message="Admin panel renewed VPN access for 7 days",
    )
    return {"user": admin_user_detail(updated)}


@app.post("/api/admin/panel/users/{user_id}/recreate-key")
async def admin_panel_recreate_key(user_id: int, admin: dict = Depends(require_telegram_admin_user)) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        updated = vpn.recreate_user_key(user, days=7, traffic_limit_gb=10)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    db.log_event(
        event_type="admin_panel_recreate_key",
        user_id=updated["id"],
        uuid_value=updated.get("uuid"),
        message="Admin panel recreated VPN key after backend/config error",
    )
    return {"user": admin_user_detail(updated)}


@app.post("/api/admin/panel/users/{user_id}/disable")
async def admin_panel_disable(user_id: int, admin: dict = Depends(require_telegram_admin_user)) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updated = vpn.disable_user_key(user)
    db.log_event(
        event_type="admin_panel_disable",
        user_id=updated["id"],
        uuid_value=user.get("uuid"),
        message="Admin panel disabled VPN access",
    )
    return {"user": admin_user_detail(updated)}


@app.delete("/api/admin/panel/users/{user_id}/key")
async def admin_panel_delete_key(user_id: int, admin: dict = Depends(require_telegram_admin_user)) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updated = vpn.disable_user_key(user)
    db.log_event(
        event_type="admin_panel_delete_key_safe_disable",
        user_id=updated["id"],
        uuid_value=user.get("uuid"),
        message="Admin panel safe-disabled VPN device/key",
    )
    return {"user": admin_user_detail(updated)}


@app.get("/api/keys/current")
async def current_key(user: dict = Depends(current_user)) -> dict:
    if db.user_vpn_status(user) != "active":
        raise HTTPException(status_code=404, detail="Access is not active")
    return {"key": decorate_vpn_user(user), "xray_client": vpn.xray_client_payload(user)}


@app.get("/api/payments/plans")
async def payment_plans(user: dict = Depends(current_user)) -> dict:
    capacity = capacity_summary()
    return {
        "plans": [payments.get_plan("7d"), payments.get_plan("30d")],
        "capacity": capacity,
        "support_url": settings.support_url,
    }


@app.post("/api/payments/invoice")
async def payment_invoice(payload: InvoicePayload, user: dict = Depends(current_user)) -> dict:
    plan = payments.get_plan(payload.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    try:
        return await payments.create_stars_invoice(user, payload.plan_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram API error: {exc.response.text}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/keys/{key_id}/renew")
async def renew_key(key_id: int, payload: DaysPayload, user: dict = Depends(current_user)) -> dict:
    if key_id != user["id"]:
        raise HTTPException(status_code=404, detail="Key not found")
    try:
        renewed = vpn.activate_or_extend_user_key(user, payload.days)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"key": decorate_vpn_user(renewed), "xray_client": vpn.xray_client_payload(renewed)}


@app.post("/api/keys/{key_id}/disable")
async def disable_key(key_id: int, user: dict = Depends(current_user)) -> dict:
    if key_id != user["id"]:
        raise HTTPException(status_code=404, detail="Key not found")
    updated = vpn.disable_user_key(user)
    return {"key": decorate_vpn_user(updated), "xray_client": vpn.xray_client_payload(updated)}


@app.delete("/api/keys/{key_id}")
async def delete_key(key_id: int, user: dict = Depends(current_user)) -> dict:
    if key_id != user["id"]:
        raise HTTPException(status_code=404, detail="Key not found")
    updated = vpn.delete_user_key(user)
    return {"key": decorate_vpn_user(updated)}


@app.get("/api/keys/{key_id}/qr")
async def key_qr(key_id: int, user: dict = Depends(current_user)) -> Response:
    if key_id != user["id"] or not user.get("uuid"):
        raise HTTPException(status_code=404, detail="Key not found")
    if db.user_vpn_status(user) != "active":
        raise HTTPException(status_code=403, detail="VPN inactive")
    png = make_qr_png(vpn.build_access_uri(user))
    return Response(content=png, media_type="image/png")


@app.get("/api/keys/{key_id}/subscription")
async def key_subscription_url(key_id: int, user: dict = Depends(current_user)) -> dict:
    if key_id != user["id"] or not user.get("subscription_token"):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"subscription_url": vpn.subscription_url(user["subscription_token"])}


@app.get("/api/devices")
async def devices() -> dict:
    return {
        "devices": [
            {
                "id": "iphone",
                "title": "iPhone",
                "app": "",
                "steps": "Отсканируй QR-код или вставь скопированную ссылку, затем включи подключение.",
            },
            {
                "id": "android",
                "title": "Android",
                "app": "",
                "steps": "Вставь скопированную ссылку в приложение для VPN и включи подключение.",
            },
            {
                "id": "windows",
                "title": "Windows",
                "app": "",
                "steps": "Добавь скопированную ссылку в приложение для VPN и нажми подключиться.",
            },
        ]
    }


@app.get("/sub/{token}")
async def subscription(token: str) -> PlainTextResponse:
    user = db.get_user_by_subscription_token(token)
    if not user or db.user_vpn_status(user) != "active":
        raise HTTPException(status_code=404, detail="Subscription not found")
    return PlainTextResponse(vpn.build_subscription(user))


@app.get("/api/admin/users", dependencies=[Depends(require_admin_token)])
async def admin_users(q: str | None = Query(default=None)) -> dict:
    users = db.search_users(q)
    return {"users": [decorate_vpn_user(user) for user in users], "capacity": capacity_summary()}


@app.post("/api/admin/users/{user_id}/premium", dependencies=[Depends(require_admin_token)])
async def admin_premium(user_id: int, payload: DaysPayload) -> dict:
    user = db.grant_premium(user_id, payload.days)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}


@app.post("/api/admin/users/{user_id}/renew", dependencies=[Depends(require_admin_token)])
async def admin_renew_user(user_id: int, payload: DaysPayload) -> dict:
    existing = db.get_user(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user = vpn.activate_or_extend_user_key(existing, payload.days)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.log_event(
        event_type="admin_renew",
        user_id=user["id"],
        uuid_value=user.get("uuid"),
        message=f"Admin renewed VPN access for {payload.days} days",
    )
    return {"user": decorate_vpn_user(user), "xray_client": vpn.xray_client_payload(user)}


@app.post("/api/admin/users/{user_id}/traffic", dependencies=[Depends(require_admin_token)])
async def admin_add_traffic(user_id: int, payload: TrafficPayload) -> dict:
    user = db.add_user_traffic_limit(user_id, payload.gb)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.log_event(
        event_type="admin_add_traffic",
        user_id=user["id"],
        uuid_value=user.get("uuid"),
        message=f"Admin added {payload.gb} GB traffic",
    )
    return {"user": decorate_vpn_user(user), "capacity": capacity_summary()}


@app.post("/api/admin/users/{user_id}/disable", dependencies=[Depends(require_admin_token)])
async def admin_disable_user(user_id: int) -> dict:
    existing = db.get_user(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")
    user = vpn.disable_user_key(existing)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": decorate_vpn_user(user), "xray_client": vpn.xray_client_payload(user)}


@app.delete("/api/admin/users/{user_id}/key", dependencies=[Depends(require_admin_token)])
async def admin_delete_user_key(user_id: int) -> dict:
    existing = db.get_user(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")
    user = vpn.delete_user_key(existing)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": decorate_vpn_user(user)}


@app.post("/api/admin/users/{user_id}/key", dependencies=[Depends(require_admin_token)])
async def admin_create_user_key(user_id: int, payload: CreateKeyPayload) -> dict:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.traffic_limit:
        user["traffic_limit"] = payload.traffic_limit
    try:
        updated = vpn.activate_or_extend_user_key(user, days=payload.days, traffic_limit_gb=payload.traffic_limit)
    except vpn.VpnProvisioningError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"user": decorate_vpn_user(updated), "xray_client": vpn.xray_client_payload(updated)}


def decorate_key(key: dict | None) -> dict | None:
    if not key:
        return None
    decorated = dict(key)
    decorated["vless_uri"] = vpn.build_access_uri(key)
    decorated["subscription_url"] = vpn.subscription_url(key["subscription_token"])
    decorated["is_active"] = key["disabled_at"] is None
    return decorated


def decorate_vpn_user(user: dict | None) -> dict | None:
    if not user:
        return None
    decorated = dict(user)
    status = db.user_vpn_status(user)
    decorated["status"] = status
    decorated["is_active"] = status == "active"
    decorated["label"] = vpn.label_for_user(user)
    limit = user.get("traffic_limit")
    used = user.get("used_traffic") or 0
    decorated["traffic_limit_gb"] = limit
    decorated["used_traffic_gb"] = used
    decorated["remaining_traffic_gb"] = None if limit is None else max(limit - used, 0)
    if user.get("uuid"):
        try:
            decorated["vless_uri"] = vpn.build_access_uri(decorated)
        except (vpn.VpnProvisioningError, RuntimeError) as error:
            decorated["status"] = "config_error"
            decorated["is_active"] = False
            decorated["vless_uri"] = None
            decorated["config_error"] = str(error)
    else:
        decorated["vless_uri"] = None
    if user.get("subscription_token"):
        decorated["subscription_url"] = vpn.subscription_url(user["subscription_token"])
    else:
        decorated["subscription_url"] = None
    return decorated


def admin_user_summary(user: dict) -> dict:
    decorated = decorate_vpn_user(user)
    return {
        "id": user["id"],
        "telegram_user_id": user["telegram_id"],
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "status": decorated["status"],
        "expires_at": user.get("expires_at"),
        "traffic_limit_gb": decorated["traffic_limit_gb"],
        "used_traffic_gb": decorated["used_traffic_gb"],
        "key_id": user["id"],
        "device_id": user.get("uuid"),
    }


def admin_user_detail(user: dict) -> dict:
    decorated = decorate_vpn_user(user)
    return {
        **admin_user_summary(user),
        "remaining_traffic_gb": decorated["remaining_traffic_gb"],
        "vless_uri": decorated["vless_uri"],
        "subscription_url": decorated["subscription_url"],
    }


def capacity_summary() -> dict:
    active = db.active_keys_count()
    max_keys = settings.max_users
    return {
        "active": active,
        "max": max_keys,
        "available": max(max_keys - active, 0),
        "is_full": active >= max_keys,
    }
