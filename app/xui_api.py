from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_settings


class XuiApiError(RuntimeError):
    pass


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.xui_api_base_url.strip())


def _base_url() -> str:
    return get_settings().xui_api_base_url.strip().rstrip("/")


def _client_payload(user: dict) -> dict[str, Any]:
    limit_gb = user.get("traffic_limit") or 0
    client = {
        "id": user["uuid"],
        "flow": "",
        "email": f"telegram_{user['telegram_id']}",
        "limitIp": 0,
        "totalGB": int(limit_gb) * (1024**3) if limit_gb else 0,
        "expiryTime": 0,
        "enable": True,
        "tgId": "",
        "subId": "",
    }
    if get_settings().vpn_security_value() == "reality" and get_settings().vpn_flow.strip():
        client["flow"] = get_settings().vpn_flow.strip()
    return client


def _request_ok(data: dict[str, Any]) -> bool:
    if "success" in data:
        return bool(data["success"])
    if "ok" in data:
        return bool(data["ok"])
    return True


def _raise_for_api_response(response: httpx.Response, action: str) -> dict[str, Any]:
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as error:
        raise XuiApiError(f"x-ui API {action} returned non-JSON response") from error
    if not _request_ok(data):
        message = data.get("msg") or data.get("message") or data.get("error") or str(data)
        raise XuiApiError(f"x-ui API {action} failed: {message}")
    return data


def _login(client: httpx.Client) -> None:
    settings = get_settings()
    if not settings.xui_api_username or not settings.xui_api_password:
        raise XuiApiError("XUI_API_USERNAME and XUI_API_PASSWORD are required")
    response = client.post(
        f"{_base_url()}/login",
        data={"username": settings.xui_api_username, "password": settings.xui_api_password},
    )
    _raise_for_api_response(response, "login")


def _with_client() -> httpx.Client:
    if not is_configured():
        raise XuiApiError("XUI_API_BASE_URL is required")
    return httpx.Client(base_url=_base_url(), timeout=15, follow_redirects=True)


def _obj(data: dict[str, Any]) -> Any:
    return data.get("obj", data.get("data"))


def _parse_json_object(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _inbound_matches(inbound: dict[str, Any]) -> bool:
    settings = get_settings()
    if settings.xui_api_inbound_id is not None and int(inbound.get("id", -1)) == settings.xui_api_inbound_id:
        return True
    return int(inbound.get("port", -1)) == settings.vpn_port and str(inbound.get("protocol", "")).lower() == settings.vpn_protocol


def _find_inbound(inbounds: list[dict[str, Any]]) -> dict[str, Any]:
    for inbound in inbounds:
        if _inbound_matches(inbound):
            return inbound
    settings = get_settings()
    raise XuiApiError(f"x-ui inbound not found: id={settings.xui_api_inbound_id} protocol={settings.vpn_protocol} port={settings.vpn_port}")


def list_inbounds() -> list[dict[str, Any]]:
    try:
        with _with_client() as client:
            _login(client)
            response = client.get("/panel/api/inbounds/list")
            data = _raise_for_api_response(response, "list inbounds")
    except httpx.HTTPError as error:
        raise XuiApiError(f"x-ui API is unavailable: {error}") from error
    obj = _obj(data)
    if not isinstance(obj, list):
        raise XuiApiError("x-ui API list inbounds returned invalid payload")
    return obj


def target_inbound() -> dict[str, Any]:
    return _find_inbound(list_inbounds())


def _settings_clients(inbound: dict[str, Any]) -> list[dict[str, Any]]:
    settings_json = _parse_json_object(inbound.get("settings"), {})
    clients = settings_json.get("clients") or []
    if not isinstance(clients, list):
        raise XuiApiError("x-ui inbound settings.clients is not a list")
    return clients


def ws_path_from_api() -> str:
    inbound = target_inbound()
    stream_settings = _parse_json_object(inbound.get("streamSettings") or inbound.get("stream_settings"), {})
    if stream_settings.get("network") != "ws":
        return ""
    return str((stream_settings.get("wsSettings") or {}).get("path") or "")


def has_client(uuid_value: str) -> bool:
    inbound = target_inbound()
    return any(str(client.get("id")) == str(uuid_value) for client in _settings_clients(inbound))


def add_client(user: dict) -> dict[str, Any]:
    inbound = target_inbound()
    inbound_id = int(inbound["id"])
    if any(str(client.get("id")) == str(user["uuid"]) for client in _settings_clients(inbound)):
        return {"status": "ok", "added": 0, "backend": "xui_api", "reason": "client already exists"}
    payload = {
        "id": inbound_id,
        "settings": json.dumps({"clients": [_client_payload(user)]}, ensure_ascii=False, separators=(",", ":")),
    }
    try:
        with _with_client() as client:
            _login(client)
            response = client.post("/panel/api/inbounds/addClient", json=payload)
            _raise_for_api_response(response, "add client")
    except httpx.HTTPError as error:
        raise XuiApiError(f"x-ui API is unavailable: {error}") from error
    if not has_client(user["uuid"]):
        raise XuiApiError("x-ui API addClient succeeded but client was not found after verification")
    return {"status": "ok", "added": 1, "backend": "xui_api", "inbound_id": inbound_id}


def remove_client(uuid_value: str) -> dict[str, Any]:
    inbound = target_inbound()
    inbound_id = int(inbound["id"])
    if not any(str(client.get("id")) == str(uuid_value) for client in _settings_clients(inbound)):
        return {"status": "ok", "removed": 0, "backend": "xui_api", "reason": "client was not present"}
    try:
        with _with_client() as client:
            _login(client)
            response = client.post(f"/panel/api/inbounds/{inbound_id}/delClient/{uuid_value}")
            _raise_for_api_response(response, "delete client")
    except httpx.HTTPError as error:
        raise XuiApiError(f"x-ui API is unavailable: {error}") from error
    if has_client(uuid_value):
        raise XuiApiError("x-ui API delClient succeeded but client still exists after verification")
    return {"status": "ok", "removed": 1, "backend": "xui_api", "inbound_id": inbound_id}
