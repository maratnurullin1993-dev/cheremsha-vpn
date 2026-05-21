from __future__ import annotations

import base64
import secrets
import uuid
from urllib.parse import quote, urlencode

from app.config import get_settings
from app import db, xray


def build_vless_uri(key: dict) -> str:
    label = quote(key.get("label") or label_for_user(key))
    params = {
        "type": "tcp",
        "security": "reality",
        "pbk": key.get("public_key") or get_settings().vpn_public_key,
        "fp": "chrome",
        "sni": key.get("sni") or get_settings().vpn_server_name,
        "sid": key.get("short_id") or get_settings().vpn_short_id,
        "spx": "/",
        "flow": key.get("flow") or get_settings().vpn_flow,
        "encryption": "none",
    }
    query = urlencode(params)
    host = key.get("server_host") or get_settings().vpn_host
    port = key.get("server_port") or get_settings().vpn_port
    return f"vless://{key['uuid']}@{host}:{port}?{query}#{label}"


def build_subscription(key: dict) -> str:
    payload = build_vless_uri(key).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def subscription_url(token: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/sub/{token}"


def label_for_user(user: dict) -> str:
    settings = get_settings()
    label_name = user.get("username") or user.get("first_name") or f"user-{user['telegram_id']}"
    return f"{settings.vpn_node_name} | {label_name}"


def create_vless_key(user: dict, days: int | None = None) -> dict:
    settings = get_settings()
    key_uuid = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    label_name = user.get("username") or user.get("first_name") or f"user-{user['telegram_id']}"
    label = f"{settings.vpn_node_name} | {label_name}"
    return db.create_key(
        user_id=user["id"],
        uuid_value=key_uuid,
        label=label,
        subscription_token=token,
        server_host=settings.vpn_host,
        server_port=settings.vpn_port,
        sni=settings.vpn_server_name,
        public_key=settings.vpn_public_key,
        short_id=settings.vpn_short_id,
        flow=settings.vpn_flow,
        days=days or settings.default_days,
    )


def ensure_active_key(user: dict) -> dict:
    existing = db.get_active_key(user["id"])
    if existing:
        return existing
    return create_vless_key(user)


def create_or_replace_user_key(user: dict, days: int | None = None, traffic_limit_gb: int | None = None) -> dict:
    settings = get_settings()
    if db.user_vpn_status(user) == "active" and user.get("uuid"):
        return db.extend_user_access(user["id"], days or settings.default_days, traffic_limit_gb)

    if user.get("uuid"):
        xray.remove_client(user["uuid"])
        db.mark_user_disabled(user["id"])

    key_uuid = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    active_days = days or settings.default_days
    limit_gb = traffic_limit_gb if traffic_limit_gb is not None else user.get("traffic_limit")
    updated = db.set_user_key(
        user_id=user["id"],
        uuid_value=key_uuid,
        subscription_token=token,
        days=active_days,
        traffic_limit=limit_gb,
    )
    db.create_key(
        user_id=user["id"],
        uuid_value=key_uuid,
        label=label_for_user(user),
        subscription_token=token,
        server_host=settings.vpn_host,
        server_port=settings.vpn_port,
        sni=settings.vpn_server_name,
        public_key=settings.vpn_public_key,
        short_id=settings.vpn_short_id,
        flow=settings.vpn_flow,
        days=active_days,
        traffic_limit_gb=limit_gb,
    )
    xray.add_client(updated)
    return updated


def activate_or_extend_user_key(user: dict, days: int | None = None, traffic_limit_gb: int | None = None) -> dict:
    active_days = days or get_settings().default_days
    if db.user_vpn_status(user) == "active" and user.get("uuid"):
        return db.extend_user_access(user["id"], active_days, traffic_limit_gb)
    return create_or_replace_user_key(user, active_days, traffic_limit_gb)


def disable_user_key(user: dict) -> dict:
    if user.get("uuid"):
        xray.remove_client(user["uuid"])
    return db.mark_user_disabled(user["id"])


def delete_user_key(user: dict) -> dict:
    if user.get("uuid"):
        xray.remove_client(user["uuid"])
    db.mark_user_disabled(user["id"])
    return db.delete_user_key(user["id"])


def update_traffic_usage() -> list[dict]:
    """Dev/mock traffic refresh hook. Replace this with Xray stats API later."""
    if not get_settings().dev_mode:
        return []
    return []


def ensure_user_key(user: dict) -> dict:
    status = db.user_vpn_status(user)
    if status == "active" and user.get("uuid"):
        return user
    raise RuntimeError("Active VPN key is missing")


def xray_client_payload(user: dict) -> dict:
    return {
        "id": user["uuid"],
        "flow": get_settings().vpn_flow,
        "email": f"telegram_{user['telegram_id']}",
        "limitIp": 0,
        "totalGB": user.get("traffic_limit") or 0,
        "expiryTime": user.get("expires_at"),
        "enable": db.user_vpn_status(user) == "active",
    }


def node_status() -> dict:
    settings = get_settings()
    return {
        "name": settings.vpn_node_name,
        "country": settings.vpn_country,
        "host": settings.vpn_host,
        "ping_ms": 42,
        "online": True,
    }
