from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def db_path() -> Path:
    path = Path(get_settings().database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                uuid TEXT UNIQUE,
                subscription_token TEXT UNIQUE,
                expires_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 0,
                traffic_limit INTEGER,
                used_traffic INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0,
                premium_until TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vpn_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                uuid TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                subscription_token TEXT NOT NULL UNIQUE,
                server_host TEXT NOT NULL,
                server_port INTEGER NOT NULL,
                sni TEXT NOT NULL,
                public_key TEXT NOT NULL,
                short_id TEXT NOT NULL,
                flow TEXT NOT NULL,
                traffic_limit_gb INTEGER,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                disabled_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                payload TEXT NOT NULL UNIQUE,
                plan_id TEXT NOT NULL,
                days INTEGER NOT NULL,
                stars INTEGER NOT NULL,
                traffic_limit_gb INTEGER,
                currency TEXT NOT NULL DEFAULT 'XTR',
                status TEXT NOT NULL DEFAULT 'pending',
                invoice_link TEXT,
                telegram_payment_charge_id TEXT,
                provider_payment_charge_id TEXT,
                created_at TEXT NOT NULL,
                paid_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id INTEGER,
                uuid TEXT,
                message TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_vpn_keys_user_id ON vpn_keys(user_id);
            CREATE INDEX IF NOT EXISTS idx_vpn_keys_token ON vpn_keys(subscription_token);
            CREATE INDEX IF NOT EXISTS idx_payments_payload ON payments(payload);
            CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at);
            """
        )
        _ensure_user_columns(conn)


def _ensure_user_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    columns = {
        "uuid": "TEXT",
        "subscription_token": "TEXT",
        "expires_at": "TEXT",
        "is_active": "INTEGER NOT NULL DEFAULT 0",
        "traffic_limit": "INTEGER",
        "used_traffic": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

    payment_existing = {row["name"] for row in conn.execute("PRAGMA table_info(payments)").fetchall()}
    if "traffic_limit_gb" not in payment_existing:
        conn.execute("ALTER TABLE payments ADD COLUMN traffic_limit_gb INTEGER")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def upsert_user(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    with connect() as conn:
        existing = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        admin_flag = 1 if is_admin else 0
        if existing:
            conn.execute(
                """
                UPDATE users
                SET username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name),
                    is_admin = MAX(is_admin, ?)
                WHERE telegram_id = ?
                """,
                (username, first_name, admin_flag, telegram_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (telegram_id, username, first_name, admin_flag, iso(utcnow())),
            )
        return row_to_dict(
            conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        )


def get_user_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(
            conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        )


def list_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT users.*
            FROM users
            ORDER BY users.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def search_users(query: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if query:
            pattern = f"%{query.lower()}%"
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE lower(COALESCE(username, '')) LIKE ?
                   OR CAST(telegram_id AS TEXT) LIKE ?
                ORDER BY created_at DESC
                """,
                (pattern, pattern),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]


def get_user(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_subscription_token(token: str) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(
            conn.execute("SELECT * FROM users WHERE subscription_token = ?", (token,)).fetchone()
        )


def set_user_key(
    user_id: int,
    uuid_value: str,
    subscription_token: str,
    days: int,
    traffic_limit: int | None = None,
) -> dict[str, Any] | None:
    now = utcnow()
    expires = now + timedelta(days=days)
    with connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET uuid = ?,
                subscription_token = ?,
                expires_at = ?,
                is_active = 1,
                traffic_limit = ?,
                used_traffic = 0
            WHERE id = ?
            """,
            (uuid_value, subscription_token, iso(expires), traffic_limit, user_id),
        )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def disable_user_key(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def delete_user_key(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET uuid = NULL,
                subscription_token = NULL,
                expires_at = NULL,
                is_active = 0,
                traffic_limit = NULL,
                used_traffic = 0
            WHERE id = ?
            """,
            (user_id,),
        )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def renew_user_key(user_id: int, days: int) -> dict[str, Any] | None:
    now = utcnow()
    user = get_user(user_id)
    if not user:
        return None
    base = parse_dt(user["expires_at"]) or now
    if base < now:
        base = now
    expires = base + timedelta(days=days)
    with connect() as conn:
        conn.execute(
            "UPDATE users SET expires_at = ?, is_active = 1 WHERE id = ?",
            (iso(expires), user_id),
        )
        if user.get("uuid"):
            conn.execute(
                """
                UPDATE vpn_keys
                SET expires_at = ?, disabled_at = NULL
                WHERE user_id = ? AND uuid = ?
                """,
                (iso(expires), user_id, user["uuid"]),
            )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def extend_user_access(user_id: int, days: int, traffic_limit_gb: int | None = None) -> dict[str, Any] | None:
    now = utcnow()
    user = get_user(user_id)
    if not user:
        return None
    base = parse_dt(user["expires_at"]) or now
    if base < now:
        base = now
    expires = base + timedelta(days=days)
    with connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET expires_at = ?,
                is_active = 1,
                traffic_limit = CASE
                    WHEN ? IS NULL THEN traffic_limit
                    ELSE COALESCE(traffic_limit, 0) + ?
                END
            WHERE id = ?
            """,
            (iso(expires), traffic_limit_gb, traffic_limit_gb, user_id),
        )
        if user.get("uuid"):
            conn.execute(
                """
                UPDATE vpn_keys
                SET expires_at = ?,
                    traffic_limit_gb = CASE
                        WHEN ? IS NULL THEN traffic_limit_gb
                        ELSE COALESCE(traffic_limit_gb, 0) + ?
                    END
                WHERE user_id = ? AND uuid = ? AND disabled_at IS NULL
                """,
                (iso(expires), traffic_limit_gb, traffic_limit_gb, user_id, user["uuid"]),
            )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def user_vpn_status(user: dict) -> str:
    if not user.get("uuid"):
        return "missing"
    expires_at = parse_dt(user.get("expires_at"))
    if expires_at and expires_at <= utcnow():
        return "expired"
    traffic_limit = user.get("traffic_limit")
    if user.get("is_active") and traffic_limit is not None and user.get("used_traffic", 0) >= traffic_limit:
        return "traffic_exhausted"
    if not user.get("is_active"):
        return "disabled"
    return "active"


def active_keys_count() -> int:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM users
            WHERE uuid IS NOT NULL
              AND is_active = 1
              AND datetime(expires_at) > datetime('now')
              AND (traffic_limit IS NULL OR used_traffic < traffic_limit)
            """
        ).fetchone()
        return int(row["count"])


def users_count() -> int:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])


def log_event(
    event_type: str,
    message: str,
    user_id: int | None = None,
    uuid_value: str | None = None,
    metadata: str | None = None,
) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO logs (event_type, user_id, uuid, message, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_type, user_id, uuid_value, message, metadata, iso(utcnow())),
        )
        return row_to_dict(conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 1").fetchone())


def list_expired_active_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM users
            WHERE uuid IS NOT NULL
              AND is_active = 1
              AND datetime(expires_at) <= datetime('now')
            ORDER BY expires_at ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def list_over_limit_active_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM users
            WHERE uuid IS NOT NULL
              AND is_active = 1
              AND traffic_limit IS NOT NULL
              AND used_traffic >= traffic_limit
            ORDER BY used_traffic DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def mark_user_expired(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.execute(
            """
            UPDATE vpn_keys
            SET disabled_at = COALESCE(disabled_at, ?)
            WHERE user_id = ? AND disabled_at IS NULL AND datetime(expires_at) <= datetime('now')
            """,
            (iso(utcnow()), user_id),
        )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def mark_user_disabled(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.execute(
            """
            UPDATE vpn_keys
            SET disabled_at = COALESCE(disabled_at, ?)
            WHERE user_id = ? AND disabled_at IS NULL
            """,
            (iso(utcnow()), user_id),
        )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def update_user_traffic(user_id: int, used_traffic_gb: int) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET used_traffic = MAX(used_traffic, ?) WHERE id = ?",
            (used_traffic_gb, user_id),
        )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def add_user_traffic_limit(user_id: int, gb: int) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET traffic_limit = COALESCE(traffic_limit, 0) + ?,
                is_active = CASE
                    WHEN uuid IS NOT NULL AND datetime(expires_at) > datetime('now') THEN 1
                    ELSE is_active
                END
            WHERE id = ?
            """,
            (gb, user_id),
        )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def create_payment(
    user_id: int,
    payload: str,
    plan_id: str,
    days: int,
    stars: int,
    traffic_limit_gb: int,
) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO payments (user_id, payload, plan_id, days, stars, traffic_limit_gb, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, payload, plan_id, days, stars, traffic_limit_gb, iso(utcnow())),
        )
        return row_to_dict(conn.execute("SELECT * FROM payments WHERE payload = ?", (payload,)).fetchone())


def attach_invoice_link(payment_id: int, invoice_link: str) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("UPDATE payments SET invoice_link = ? WHERE id = ?", (invoice_link, payment_id))
        return row_to_dict(conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone())


def get_payment_by_payload(payload: str) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(conn.execute("SELECT * FROM payments WHERE payload = ?", (payload,)).fetchone())


def complete_payment(
    payload: str,
    telegram_payment_charge_id: str | None,
    provider_payment_charge_id: str | None,
) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE payments
            SET status = 'paid',
                telegram_payment_charge_id = ?,
                provider_payment_charge_id = ?,
                paid_at = COALESCE(paid_at, ?)
            WHERE payload = ?
            """,
            (telegram_payment_charge_id, provider_payment_charge_id, iso(utcnow()), payload),
        )
        return row_to_dict(conn.execute("SELECT * FROM payments WHERE payload = ?", (payload,)).fetchone())


def create_key(
    user_id: int,
    uuid_value: str,
    label: str,
    subscription_token: str,
    server_host: str,
    server_port: int,
    sni: str,
    public_key: str,
    short_id: str,
    flow: str,
    days: int,
    traffic_limit_gb: int | None = None,
) -> dict[str, Any]:
    now = utcnow()
    expires = now + timedelta(days=days)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO vpn_keys (
                user_id, uuid, label, subscription_token, server_host, server_port,
                sni, public_key, short_id, flow, traffic_limit_gb, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                uuid_value,
                label,
                subscription_token,
                server_host,
                server_port,
                sni,
                public_key,
                short_id,
                flow,
                traffic_limit_gb,
                iso(now),
                iso(expires),
            ),
        )
        return row_to_dict(conn.execute("SELECT * FROM vpn_keys WHERE uuid = ?", (uuid_value,)).fetchone())


def get_active_key(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(
            conn.execute(
                """
                SELECT * FROM vpn_keys
                WHERE user_id = ? AND disabled_at IS NULL AND datetime(expires_at) > datetime('now')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        )


def get_key(key_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(conn.execute("SELECT * FROM vpn_keys WHERE id = ?", (key_id,)).fetchone())


def get_key_by_token(token: str) -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(
            conn.execute("SELECT * FROM vpn_keys WHERE subscription_token = ?", (token,)).fetchone()
        )


def list_keys() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT vpn_keys.*, users.telegram_id, users.username, users.first_name
            FROM vpn_keys
            JOIN users ON users.id = vpn_keys.user_id
            ORDER BY vpn_keys.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def latest_key() -> dict[str, Any] | None:
    with connect() as conn:
        return row_to_dict(
            conn.execute(
                """
                SELECT vpn_keys.*, users.telegram_id, users.username, users.first_name
                FROM vpn_keys
                JOIN users ON users.id = vpn_keys.user_id
                ORDER BY vpn_keys.created_at DESC
                LIMIT 1
                """
            ).fetchone()
        )


def disable_key(key_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute(
            "UPDATE vpn_keys SET disabled_at = ? WHERE id = ?",
            (iso(utcnow()), key_id),
        )
        return row_to_dict(conn.execute("SELECT * FROM vpn_keys WHERE id = ?", (key_id,)).fetchone())


def renew_key(key_id: int, days: int) -> dict[str, Any] | None:
    now = utcnow()
    key = get_key(key_id)
    if not key:
        return None
    base = parse_dt(key["expires_at"]) or now
    if base < now:
        base = now
    expires = base + timedelta(days=days)
    with connect() as conn:
        conn.execute("UPDATE vpn_keys SET expires_at = ? WHERE id = ?", (iso(expires), key_id))
        return row_to_dict(conn.execute("SELECT * FROM vpn_keys WHERE id = ?", (key_id,)).fetchone())


def grant_premium(user_id: int, days: int) -> dict[str, Any] | None:
    now = utcnow()
    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            return None
        current = parse_dt(user["premium_until"]) or now
        if current < now:
            current = now
        premium_until = current + timedelta(days=days)
        conn.execute(
            "UPDATE users SET premium_until = ? WHERE id = ?",
            (iso(premium_until), user_id),
        )
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def mark_expired_keys() -> int:
    with connect() as conn:
        keys_cursor = conn.execute(
            """
            UPDATE vpn_keys
            SET disabled_at = COALESCE(disabled_at, ?)
            WHERE disabled_at IS NULL AND datetime(expires_at) <= datetime('now')
            """,
            (iso(utcnow()),),
        )
        users_cursor = conn.execute(
            """
            UPDATE users
            SET is_active = 0
            WHERE uuid IS NOT NULL
              AND is_active = 1
              AND datetime(expires_at) <= datetime('now')
            """
        )
        return keys_cursor.rowcount + users_cursor.rowcount
