from __future__ import annotations

import base64
import json
import secrets
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.config import get_settings

DEFAULT_METHOD = "chacha20-ietf-poly1305"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _paths() -> tuple[Path, Path]:
    settings = get_settings()
    return Path(settings.outline_server_config_path), Path(settings.outline_config_path)


def _method_field(config: dict[str, Any]) -> str:
    access_keys = config.get("accessKeys") or []
    for key in access_keys:
        if "method" in key:
            return "method"
        if "encryptionMethod" in key:
            return "encryptionMethod"
    return "encryptionMethod"


def _server_value(config: dict[str, Any], name: str) -> Any:
    value = config.get(name)
    if value is not None:
        return value
    server = config.get("server") or {}
    return server.get(name)


def config_status() -> dict:
    settings = get_settings()
    values = {
        "VPN_BACKEND": settings.vpn_backend_value(),
        "OUTLINE_SERVER_CONFIG_PATH": settings.outline_server_config_path.strip(),
        "OUTLINE_CONFIG_PATH": settings.outline_config_path.strip(),
        "WEBAPP_URL": settings.webapp_url.strip(),
    }
    missing = [key for key, value in values.items() if value in ("", None)]
    if not missing:
        server_path, config_path = _paths()
        if not server_path.exists():
            missing.append("OUTLINE_SERVER_CONFIG_PATH:file")
        if not config_path.exists():
            missing.append("OUTLINE_CONFIG_PATH:file")
    return {
        "ok": not missing,
        "missing": missing,
        "values": {key: bool(value) for key, value in values.items()},
    }


def validate_config() -> None:
    status = config_status()
    if not status["ok"]:
        raise RuntimeError(f"Outline file configuration is incomplete: {', '.join(status['missing'])}")


def add_access_key(user: dict) -> dict[str, Any]:
    validate_config()
    server_path, config_path = _paths()
    server_config = _load_json(server_path)
    config = _load_json(config_path)
    access_keys = config.setdefault("accessKeys", [])
    next_id = int(config.get("nextId") or 0)
    key_id = str(next_id)
    password = secrets.token_urlsafe(24)
    method_field = _method_field(config)
    method = DEFAULT_METHOD
    name = user.get("username") or user.get("first_name") or str(user["telegram_id"])
    host = str(_server_value(server_config, "hostname") or "")
    port = int(_server_value(server_config, "portForNewAccessKeys") or 0)
    if not host or not port:
        raise RuntimeError("Outline server config must include hostname and portForNewAccessKeys")

    access_key = {
        "id": key_id,
        "name": name,
        "password": password,
        "port": port,
        method_field: method,
    }
    access_keys.append(access_key)
    config["nextId"] = next_id + 1
    _save_json(config_path, config)
    restart_result = restart_outline()
    if restart_result["status"] not in ("ok", "skipped"):
        raise RuntimeError(f"Outline restart failed: {restart_result}")
    return {
        **access_key,
        "method": method,
        "host": host,
        "restart": restart_result,
    }


def remove_access_key(key_id: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.outline_config_path:
        return {"status": "skipped", "reason": "OUTLINE_CONFIG_PATH is empty"}
    config_path = Path(settings.outline_config_path)
    if not config_path.exists():
        return {"status": "skipped", "reason": f"Outline config not found: {config_path}"}

    config = _load_json(config_path)
    access_keys = config.get("accessKeys")
    if not isinstance(access_keys, list):
        return {"status": "skipped", "reason": "accessKeys list was not found"}
    before = len(access_keys)
    config["accessKeys"] = [key for key in access_keys if str(key.get("id")) != str(key_id)]
    removed = before - len(config["accessKeys"])
    if removed:
        _save_json(config_path, config)
        restart_result = restart_outline()
    else:
        restart_result = {"status": "skipped", "reason": "access key was not present"}
    return {"status": "ok", "removed": removed, "restart": restart_result}


def has_access_key(key_id: str) -> bool:
    settings = get_settings()
    if not settings.outline_config_path:
        return False
    config_path = Path(settings.outline_config_path)
    if not config_path.exists():
        return False
    config = _load_json(config_path)
    access_keys = config.get("accessKeys") or []
    return any(str(key.get("id")) == str(key_id) for key in access_keys)


def access_key_by_id(key_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.outline_config_path or not settings.outline_server_config_path:
        return None
    config_path = Path(settings.outline_config_path)
    server_path = Path(settings.outline_server_config_path)
    if not config_path.exists() or not server_path.exists():
        return None
    config = _load_json(config_path)
    server_config = _load_json(server_path)
    host = str(_server_value(server_config, "hostname") or "")
    for key in config.get("accessKeys") or []:
        if str(key.get("id")) == str(key_id):
            method = key.get("method") or key.get("encryptionMethod") or DEFAULT_METHOD
            return {**key, "method": method, "host": host}
    return None


def build_ss_uri(key: dict, label: str) -> str:
    method = key.get("method") or key.get("encryptionMethod") or DEFAULT_METHOD
    password = key.get("password") or key.get("public_key")
    host = key.get("host") or key.get("server_host")
    port = key.get("port") or key.get("server_port")
    if not password or not host or not port:
        raise RuntimeError("Generated Shadowsocks URI is invalid")
    userinfo = base64.urlsafe_b64encode(f"{method}:{password}".encode("utf-8")).decode("ascii").rstrip("=")
    return f"ss://{userinfo}@{host}:{port}#{quote(label)}"


def restart_outline() -> dict[str, Any]:
    command = get_settings().outline_restart_command.strip()
    if not command:
        return {"status": "skipped", "reason": "OUTLINE_RESTART_COMMAND is empty"}
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=20)
    return {
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": result.stdout[-500:],
        "stderr": result.stderr[-500:],
    }
