from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import db, vpn


def _disable_user(user: dict, event_type: str, message: str) -> None:
    result = vpn.remove_backend_key(user["uuid"])
    db.mark_user_disabled(user["id"])
    db.log_event(
        event_type=event_type,
        user_id=user["id"],
        uuid_value=user["uuid"],
        message=message,
        metadata=str(result),
    )


def enforce_vpn_limits() -> int:
    vpn.update_traffic_usage()
    expired_users = db.list_expired_active_users()
    over_limit_users = db.list_over_limit_active_users()

    handled_ids = set()
    for user in expired_users:
        handled_ids.add(user["id"])
        _disable_user(user, "vpn_expired", "VPN access expired and was disabled")

    for user in over_limit_users:
        if user["id"] in handled_ids:
            continue
        handled_ids.add(user["id"])
        _disable_user(user, "vpn_traffic_limit", "VPN traffic limit reached and was disabled")

    return len(handled_ids)


def expire_vpn_keys() -> int:
    return enforce_vpn_limits()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(enforce_vpn_limits, "interval", minutes=5, id="enforce_vpn_limits", replace_existing=True)
    return scheduler
