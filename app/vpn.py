from __future__ import annotations

import base64
import secrets
import uuid
from urllib.parse import quote, urlencode

from app.config import get_settings
from app import db, outline_file, xray


class VpnProvisioningError(RuntimeError):
    pass


_last_provisioning_error: str | None = None


def set_last_provisioning_error(error: Exception | str | None) -> None:
    global _last_provisioning_error
    _last_provisioning_error = None if error is None else str(error)


def last_provisioning_error() -> str | None:
    return _last_provisioning_error


def config_status() -> dict:
    settings = get_settings()
    if settings.vpn_backend_value() == "outline_file":
        return outline_file.config_status()
    values = {
        "VPN_BACKEND": settings.vpn_backend_value(),
        "VPN_PROTOCOL": settings.vpn_protocol.strip(),
        "VPN_HOST": settings.vpn_host.strip(),
        "VPN_PORT": settings.vpn_port,
        "VPN_NETWORK": settings.vpn_network_value(),
        "VPN_SECURITY": settings.vpn_security_value(),
        "XRAY_CONFIG_PATH": settings.xray_config_path.strip(),
        "WEBAPP_URL": settings.webapp_url.strip(),
    }
    if settings.vpn_security_value() == "reality":
        values.update(
            {
                "VPN_PUBLIC_KEY": settings.vpn_public_key.strip(),
                "VPN_SHORT_ID": settings.vpn_short_id.strip(),
                "VPN_SNI": settings.reality_sni(),
            }
        )
    missing = [key for key, value in values.items() if value in ("", None)]
    value_status = {key: bool(value) for key, value in values.items()}
    value_status["VPN_FLOW"] = bool(settings.vpn_flow.strip())
    value_status["VPN_WS_PATH"] = bool(settings.vpn_ws_path.strip() or xray.ws_path_from_config())
    return {
        "ok": not missing,
        "missing": missing,
        "values": value_status,
    }


def validate_vpn_config() -> None:
    status = config_status()
    if not status["ok"]:
        missing = ", ".join(status["missing"])
        raise VpnProvisioningError(f"VPN configuration is incomplete: {missing}")


def build_access_uri(key: dict) -> str:
    if get_settings().vpn_backend_value() == "outline_file":
        return build_outline_uri(key)
    return build_vless_uri(key)


def build_outline_uri(key: dict) -> str:
    label = key.get("label") or label_for_user(key)
    outline_key = {
        **key,
        "password": key.get("password") or key.get("public_key"),
        "method": key.get("method") or key.get("flow") or outline_file.DEFAULT_METHOD,
        "host": key.get("host") or key.get("server_host"),
        "port": key.get("port") or key.get("server_port"),
    }
    if key.get("uuid") and not outline_key.get("password"):
        user_id = key.get("user_id") or key.get("id")
        persisted = db.get_active_key(user_id) if user_id else None
        runtime_key = outline_file.access_key_by_id(key["uuid"])
        if persisted:
            outline_key.update(
                {
                    "password": persisted.get("public_key"),
                    "method": persisted.get("flow") or outline_key["method"],
                    "host": persisted.get("server_host") or outline_key.get("host"),
                    "port": persisted.get("server_port") or outline_key.get("port"),
                }
            )
        if runtime_key:
            outline_key.update(runtime_key)
    return outline_file.build_ss_uri(outline_key, label)


def build_vless_uri(key: dict) -> str:
    settings = get_settings()
    label = quote(key.get("label") or label_for_user(key))
    host = settings.vpn_host or key.get("server_host")
    port = settings.vpn_port or key.get("server_port")
    path = settings.vpn_ws_path.strip() or xray.ws_path_from_config() or "/"
    if not key.get("uuid") or not host or not port:
        raise VpnProvisioningError("Generated VLESS URI is invalid")
    params = {
        "type": "ws",
        "security": "none",
        "path": path,
        "encryption": "none",
    }
    query = urlencode(params)
    return f"vless://{key['uuid']}@{host}:{port}?{query}#{label}"


def build_subscription(key: dict) -> str:
    payload = build_access_uri(key).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def subscription_url(token: str) -> str:
    base = get_settings().webapp_url.strip().rstrip("/")
    return f"{base}/sub/{token}"


def label_for_user(user: dict) -> str:
    settings = get_settings()
    label_name = user.get("username") or user.get("first_name") or f"user-{user['telegram_id']}"
    return f"{settings.vpn_node_name} | {label_name}"


def create_vless_key(user: dict, days: int | None = None) -> dict:
    settings = get_settings()
    validate_vpn_config()
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
        sni=settings.reality_sni(),
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
    validate_vpn_config()
    if db.user_vpn_status(user) == "active" and user.get("uuid"):
        ensure_configured_key(user)
        return db.extend_user_access(user["id"], days or settings.default_days, traffic_limit_gb)

    if user.get("uuid"):
        remove_backend_key(user["uuid"])
        db.mark_user_disabled(user["id"])

    token = secrets.token_urlsafe(32)
    active_days = days or settings.default_days
    limit_gb = traffic_limit_gb if traffic_limit_gb is not None else user.get("traffic_limit")
    label = label_for_user(user)
    try:
        if settings.vpn_backend_value() == "outline_file":
            backend_key = outline_file.add_access_key(user)
            key_uuid = str(backend_key["id"])
            server_host = backend_key["host"]
            server_port = backend_key["port"]
            public_key = backend_key["password"]
            flow = backend_key["method"]
            short_id = ""
            sni = ""
        else:
            key_uuid = str(uuid.uuid4())
            pending_user = {
                **user,
                "uuid": key_uuid,
                "subscription_token": token,
                "traffic_limit": limit_gb,
            }
            xray.add_client(pending_user)
            server_host = settings.vpn_host
            server_port = settings.vpn_port
            public_key = settings.vpn_public_key
            flow = settings.vpn_flow
            short_id = settings.vpn_short_id
            sni = settings.reality_sni()
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
            label=label,
            subscription_token=token,
            server_host=server_host,
            server_port=server_port,
            sni=sni,
            public_key=public_key,
            short_id=short_id,
            flow=flow,
            days=active_days,
            traffic_limit_gb=limit_gb,
        )
    except Exception as error:
        if "key_uuid" in locals():
            remove_backend_key(key_uuid)
        set_last_provisioning_error(error)
        raise
    ensure_configured_key(updated)
    set_last_provisioning_error(None)
    return updated


def ensure_configured_key(user: dict) -> None:
    if not user.get("uuid"):
        raise VpnProvisioningError("VPN key UUID is missing")
    uri = build_access_uri(user)
    if get_settings().vpn_backend_value() == "outline_file":
        if not uri.startswith("ss://"):
            raise VpnProvisioningError("Generated Outline URI is invalid")
    else:
        if f"@:{get_settings().vpn_port}" in uri:
            raise VpnProvisioningError("Generated VLESS URI is invalid")
        if get_settings().vpn_security_value() != "reality" and any(part in uri for part in ("pbk=", "sni=", "sid=", "flow=")):
            raise VpnProvisioningError("Generated non-Reality VLESS URI contains Reality-only parameters")
        if get_settings().vpn_security_value() == "reality" and ("pbk=&" in uri or "sni=&" in uri or "sid=&" in uri):
            raise VpnProvisioningError("Generated Reality VLESS URI is invalid")
    if not has_backend_key(user["uuid"]):
        raise VpnProvisioningError("VPN backend client is missing")


def latest_key_debug() -> dict | None:
    key = db.latest_key()
    if not key:
        return None
    decorated = dict(key)
    try:
        decorated["vless_uri"] = build_access_uri(key)
    except Exception as error:
        decorated["vless_error"] = str(error)
    return decorated


def activate_or_extend_user_key(user: dict, days: int | None = None, traffic_limit_gb: int | None = None) -> dict:
    active_days = days or get_settings().default_days
    if db.user_vpn_status(user) == "active" and user.get("uuid"):
        if not has_backend_key(user["uuid"]):
            return recreate_user_key(user, active_days, traffic_limit_gb)
        return db.extend_user_access(user["id"], active_days, traffic_limit_gb)
    return create_or_replace_user_key(user, active_days, traffic_limit_gb)


def recreate_user_key(user: dict, days: int | None = None, traffic_limit_gb: int | None = None) -> dict:
    if user.get("uuid"):
        remove_backend_key(user["uuid"])
        db.mark_user_disabled(user["id"])
        user = db.get_user(user["id"]) or user
    return create_or_replace_user_key(user, days, traffic_limit_gb)


def disable_user_key(user: dict) -> dict:
    if user.get("uuid"):
        remove_backend_key(user["uuid"])
    return db.mark_user_disabled(user["id"])


def delete_user_key(user: dict) -> dict:
    if user.get("uuid"):
        remove_backend_key(user["uuid"])
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


def remove_backend_key(key_id: str) -> dict:
    if get_settings().vpn_backend_value() == "outline_file":
        return outline_file.remove_access_key(key_id)
    return xray.remove_client(key_id)


def has_backend_key(key_id: str) -> bool:
    if get_settings().vpn_backend_value() == "outline_file":
        return outline_file.has_access_key(key_id)
    return xray.has_client(key_id)


def node_status() -> dict:
    settings = get_settings()
    return {
        "name": settings.vpn_node_name,
        "country": settings.vpn_country,
        "host": settings.vpn_host,
        "ping_ms": 42,
        "online": True,
    }
