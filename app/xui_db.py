from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import get_settings


def _path() -> Path:
    return Path(get_settings().xui_db_path)


def is_configured() -> bool:
    return bool(get_settings().xui_db_path.strip())


def exists() -> bool:
    return is_configured() and _path().exists()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_path())
    conn.row_factory = sqlite3.Row
    return conn


def _json_loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def schema_summary() -> dict[str, Any]:
    if not exists():
        return {"exists": False, "tables": {}}
    with _connect() as conn:
        tables = [
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        ]
        return {"exists": True, "tables": {table: sorted(_columns(conn, table)) for table in tables}}


def _find_inbound(conn: sqlite3.Connection) -> sqlite3.Row:
    columns = _columns(conn, "inbounds")
    required = {"id", "port", "protocol", "settings"}
    if not required.issubset(columns):
        raise RuntimeError(f"x-ui table inbounds is missing required columns: {sorted(required - columns)}")

    settings = get_settings()
    row = conn.execute(
        "SELECT * FROM inbounds WHERE port = ? AND protocol = ? LIMIT 1",
        (settings.vpn_port, settings.vpn_protocol),
    ).fetchone()
    if not row:
        raise RuntimeError(f"x-ui inbound not found: protocol={settings.vpn_protocol} port={settings.vpn_port}")
    return row


def _stream_settings(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    for name in ("stream_settings", "streamSettings"):
        if name in keys:
            return _json_loads(row[name], {})
    return {}


def ws_path_from_db() -> str:
    if not exists():
        return ""
    with _connect() as conn:
        row = _find_inbound(conn)
        stream_settings = _stream_settings(row)
        if stream_settings.get("network") != "ws":
            return ""
        return str((stream_settings.get("wsSettings") or {}).get("path") or "")


def _client_payload(user: dict) -> dict[str, Any]:
    client = {
        "id": user["uuid"],
        "email": f"telegram_{user['telegram_id']}",
        "enable": True,
        "totalGB": 0,
        "expiryTime": 0,
        "limitIp": 0,
    }
    if get_settings().vpn_security_value() == "reality" and get_settings().vpn_flow.strip():
        client["flow"] = get_settings().vpn_flow.strip()
    return client


def add_client(user: dict) -> dict[str, Any]:
    if not exists():
        raise RuntimeError(f"x-ui database not found: {_path()}")
    with _connect() as conn:
        row = _find_inbound(conn)
        settings_json = _json_loads(row["settings"], {})
        clients = settings_json.setdefault("clients", [])
        if not isinstance(clients, list):
            raise RuntimeError("x-ui inbound settings.clients is not a list")
        if any(str(client.get("id")) == str(user["uuid"]) for client in clients):
            return {"status": "ok", "added": 0, "backend": "xui_db", "reason": "client already exists"}
        clients.append(_client_payload(user))
        conn.execute(
            "UPDATE inbounds SET settings = ? WHERE id = ?",
            (_json_dumps(settings_json), row["id"]),
        )
        conn.commit()
    return {"status": "ok", "added": 1, "backend": "xui_db"}


def has_client(uuid_value: str) -> bool:
    if not exists():
        return False
    with _connect() as conn:
        row = _find_inbound(conn)
        settings_json = _json_loads(row["settings"], {})
        clients = settings_json.get("clients") or []
        return any(str(client.get("id")) == str(uuid_value) for client in clients)


def remove_client(uuid_value: str) -> dict[str, Any]:
    if not exists():
        return {"status": "skipped", "reason": f"x-ui database not found: {_path()}"}
    with _connect() as conn:
        row = _find_inbound(conn)
        settings_json = _json_loads(row["settings"], {})
        clients = settings_json.get("clients") or []
        if not isinstance(clients, list):
            return {"status": "skipped", "reason": "x-ui inbound settings.clients is not a list"}
        before = len(clients)
        settings_json["clients"] = [client for client in clients if str(client.get("id")) != str(uuid_value)]
        removed = before - len(settings_json["clients"])
        if removed:
            conn.execute(
                "UPDATE inbounds SET settings = ? WHERE id = ?",
                (_json_dumps(settings_json), row["id"]),
            )
            conn.commit()
    return {"status": "ok", "removed": removed, "backend": "xui_db"}
