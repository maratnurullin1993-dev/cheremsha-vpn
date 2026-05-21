from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, Request

from app import db
from app.config import get_settings


def _validate_init_data(init_data: str, bot_token: str) -> dict:
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing Telegram hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="Invalid Telegram init data")

    user_raw = parsed.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="Missing Telegram user")
    return json.loads(user_raw)


async def current_user(
    request: Request,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    init_data = x_telegram_init_data or request.query_params.get("initData")

    if init_data and settings.bot_token:
        tg_user = _validate_init_data(init_data, settings.bot_token)
        telegram_id = int(tg_user["id"])
        return db.upsert_user(
            telegram_id=telegram_id,
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
            is_admin=telegram_id == settings.admin_id,
        )

    if settings.dev_mode:
        telegram_id = int(request.query_params.get("telegram_id", settings.admin_id or 10001))
        return db.upsert_user(
            telegram_id=telegram_id,
            username="dev_admin" if telegram_id == settings.admin_id else "dev_user",
            first_name="Dev",
            is_admin=telegram_id == settings.admin_id,
        )

    raise HTTPException(status_code=401, detail="Telegram WebApp auth required")


async def require_telegram_admin_user(
    request: Request,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    init_data = x_telegram_init_data or request.query_params.get("initData")
    if not init_data or not settings.bot_token:
        raise HTTPException(status_code=401, detail="Telegram WebApp auth required")

    tg_user = _validate_init_data(init_data, settings.bot_token)
    telegram_id = int(tg_user["id"])
    if not settings.admin_id or telegram_id != settings.admin_id:
        raise HTTPException(status_code=403, detail="Admin access required")

    return db.upsert_user(
        telegram_id=telegram_id,
        username=tg_user.get("username"),
        first_name=tg_user.get("first_name"),
        is_admin=True,
    )


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.admin_api_token or x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=403, detail="Admin token required")
