from __future__ import annotations

import secrets

import httpx

from app import db
from app.config import get_settings


def get_plan(plan_id: str) -> dict | None:
    settings = get_settings()
    plans = {
        "7d": {
            "days": 7,
            "stars": 50,
            "traffic_limit_gb": settings.default_7d_traffic_gb,
            "title": "7 дней",
        },
        "30d": {
            "days": 30,
            "stars": 150,
            "traffic_limit_gb": settings.default_30d_traffic_gb,
            "title": "30 дней",
        },
    }
    plan = plans.get(plan_id)
    if not plan:
        return None
    return {"id": plan_id, **plan}


async def create_stars_invoice(user: dict, plan_id: str) -> dict:
    settings = get_settings()
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError("Unknown plan")
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required for Telegram Stars invoices")
    if db.user_vpn_status(user) != "active":
        from app import vpn

        vpn.validate_vpn_config()

    payload = f"vpn:{user['telegram_id']}:{plan_id}:{secrets.token_urlsafe(12)}"
    payment = db.create_payment(
        user_id=user["id"],
        payload=payload,
        plan_id=plan_id,
        days=plan["days"],
        stars=plan["stars"],
        traffic_limit_gb=plan["traffic_limit_gb"],
    )
    body = {
        "title": f"ЧЕРЕМША VPN на {plan['title']}",
        "description": f"Частный VPN-доступ, {plan['traffic_limit_gb']} GB",
        "payload": payload,
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": plan["title"], "amount": plan["stars"]}],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{settings.bot_token}/createInvoiceLink",
            json=body,
        )
        response.raise_for_status()
        data = response.json()

    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram invoice error"))

    invoice_link = data["result"]
    payment = db.attach_invoice_link(payment["id"], invoice_link)
    return {"invoice_link": invoice_link, "payment": payment, "plan": plan}

