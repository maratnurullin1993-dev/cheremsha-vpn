from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.config import get_settings


def _load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_config(path: Path, config: dict[str, Any]) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def add_client(user: dict) -> dict[str, Any]:
    settings = get_settings()
    if not settings.xray_config_path:
        raise RuntimeError("XRAY_CONFIG_PATH is required to create a real Xray client")
    if not settings.xray_restart_command.strip():
        raise RuntimeError("XRAY_RESTART_COMMAND is required to activate a real Xray client")

    path = Path(settings.xray_config_path)
    if not path.exists():
        raise RuntimeError(f"Xray config not found: {path}")

    config = _load_config(path)
    client = {
        "id": user["uuid"],
        "email": f"telegram_{user['telegram_id']}",
        "flow": settings.vpn_flow,
    }
    added = 0
    already_present = False
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") not in (None, "vless"):
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
        raise RuntimeError("No Xray inbound with settings.clients was found")

    if added:
        _save_config(path, config)
        restart_result = restart_xray()
        if restart_result["status"] != "ok":
            raise RuntimeError(f"Xray restart failed: {restart_result}")
    else:
        restart_result = {"status": "skipped", "reason": "client already exists"}

    return {"status": "ok", "added": added, "restart": restart_result}


def has_client(uuid_value: str) -> bool:
    settings = get_settings()
    if not settings.xray_config_path:
        return False

    path = Path(settings.xray_config_path)
    if not path.exists():
        return False

    config = _load_config(path)
    for inbound in config.get("inbounds", []):
        clients = inbound.get("settings", {}).get("clients")
        if not isinstance(clients, list):
            continue
        if any(client.get("id") == uuid_value for client in clients):
            return True
    return False


def remove_client(uuid_value: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.xray_config_path:
        return {"status": "skipped", "reason": "XRAY_CONFIG_PATH is empty"}

    path = Path(settings.xray_config_path)
    if not path.exists():
        return {"status": "skipped", "reason": f"Xray config not found: {path}"}

    config = _load_config(path)
    removed = 0
    for inbound in config.get("inbounds", []):
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
    if not command:
        return {"status": "skipped", "reason": "XRAY_RESTART_COMMAND is empty"}

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
