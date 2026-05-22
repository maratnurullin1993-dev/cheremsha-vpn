from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app import xui_db
from app.config import get_settings

SAFE_NOOP_COMMANDS = {"", "systemctl restart x-ui"}


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_config(path: Path, config: dict[str, Any]) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _matches_target_inbound(inbound: dict[str, Any]) -> bool:
    settings = get_settings()
    protocol = settings.vpn_protocol.strip().lower()
    if protocol and str(inbound.get("protocol", "")).lower() != protocol:
        return False
    if settings.vpn_port and inbound.get("port") != settings.vpn_port:
        return False

    stream_settings = inbound.get("streamSettings", {})
    network = settings.vpn_network_value()
    security = settings.vpn_security_value()
    if network and stream_settings and str(stream_settings.get("network", "")).lower() != network:
        return False
    if security and stream_settings and str(stream_settings.get("security", "")).lower() != security:
        return False
    return True


def add_client(user: dict) -> dict[str, Any]:
    settings = get_settings()
    if xui_db.is_configured():
        if not xui_db.exists():
            raise RuntimeError(f"x-ui database not found: {settings.xui_db_path}")
        result = xui_db.add_client(user)
        restart_result = restart_xray()
        if restart_result["status"] not in ("ok", "skipped"):
            raise RuntimeError(f"x-ui restart failed: {restart_result}")
        return {**result, "restart": restart_result}

    if not settings.xray_config_path:
        raise RuntimeError("XRAY_CONFIG_PATH is required to create a real Xray client")
    path = Path(settings.xray_config_path)
    if not path.exists():
        raise RuntimeError(f"Xray config not found: {path}")

    config = _load_config(path)
    client = {
        "id": user["uuid"],
        "email": f"telegram_{user['telegram_id']}",
    }
    if settings.vpn_security_value() == "reality" and settings.vpn_flow.strip():
        client["flow"] = settings.vpn_flow.strip()
    added = 0
    already_present = False
    for inbound in config.get("inbounds", []):
        if not _matches_target_inbound(inbound):
            continue
        clients = inbound.get("settings", {}).get("clients")
        if not isinstance(clients, list):
            continue
        if any(existing.get("id") == user["uuid"] for existing in clients):
            already_present = True
            continue
        clients.append(client.copy())
        added += 1

    if not added and not already_present:
        raise RuntimeError("No matching Xray inbound with settings.clients was found")

    if added:
        _save_config(path, config)
        restart_result = restart_xray()
        if restart_result["status"] not in ("ok", "skipped"):
            raise RuntimeError(f"Xray restart failed: {restart_result}")
    else:
        restart_result = {"status": "skipped", "reason": "client already exists"}

    return {"status": "ok", "added": added, "restart": restart_result}


def ws_path_from_config() -> str:
    if xui_db.exists():
        return xui_db.ws_path_from_db()

    settings = get_settings()
    if not settings.xray_config_path:
        return ""

    path = Path(settings.xray_config_path)
    if not path.exists():
        return ""

    config = _load_config(path)
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") != "vless":
            continue
        stream_settings = inbound.get("streamSettings", {})
        if stream_settings.get("network") != "ws":
            continue
        ws_settings = stream_settings.get("wsSettings", {})
        return str(ws_settings.get("path") or "")
    return ""


def has_client(uuid_value: str) -> bool:
    if xui_db.is_configured():
        return xui_db.has_client(uuid_value)

    settings = get_settings()
    if not settings.xray_config_path:
        return False

    path = Path(settings.xray_config_path)
    if not path.exists():
        return False

    config = _load_config(path)
    for inbound in config.get("inbounds", []):
        if not _matches_target_inbound(inbound):
            continue
        clients = inbound.get("settings", {}).get("clients")
        if not isinstance(clients, list):
            continue
        if any(client.get("id") == uuid_value for client in clients):
            return True
    return False


def remove_client(uuid_value: str) -> dict[str, Any]:
    if xui_db.is_configured():
        result = xui_db.remove_client(uuid_value)
        if result.get("removed"):
            restart_result = restart_xray()
        else:
            restart_result = {"status": "skipped", "reason": result.get("reason", "client was not present")}
        return {**result, "restart": restart_result}

    settings = get_settings()
    if not settings.xray_config_path:
        return {"status": "skipped", "reason": "XRAY_CONFIG_PATH is empty"}

    path = Path(settings.xray_config_path)
    if not path.exists():
        return {"status": "skipped", "reason": f"Xray config not found: {path}"}

    config = _load_config(path)
    removed = 0
    for inbound in config.get("inbounds", []):
        if not _matches_target_inbound(inbound):
            continue
        clients = inbound.get("settings", {}).get("clients")
        if not isinstance(clients, list):
            continue
        before = len(clients)
        inbound["settings"]["clients"] = [client for client in clients if client.get("id") != uuid_value]
        removed += before - len(inbound["settings"]["clients"])

    if removed:
        _save_config(path, config)
        restart_result = restart_xray()
    else:
        restart_result = {"status": "skipped", "reason": "client was not present"}

    return {"status": "ok", "removed": removed, "restart": restart_result}


def restart_xray() -> dict[str, Any]:
    command = get_settings().xray_restart_command.strip()
    if command in SAFE_NOOP_COMMANDS:
        return {"status": "skipped", "reason": "XRAY_RESTART_COMMAND is empty or not docker-safe"}

    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return {
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout": result.stdout[-500:],
        "stderr": result.stderr[-500:],
    }
