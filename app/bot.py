from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)

from app import db, vpn
from app.config import get_settings

router = Router()


def start_keyboard() -> InlineKeyboardMarkup:
    settings = get_settings()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть VPN", web_app=WebAppInfo(url=settings.webapp_url))]
        ]
    )


def main_keyboard() -> InlineKeyboardMarkup:
    settings = get_settings()
    rows = [
        [InlineKeyboardButton(text="РћС‚РєСЂС‹С‚СЊ VPN", web_app=WebAppInfo(url=settings.webapp_url))],
        [InlineKeyboardButton(text="РџРѕР»СѓС‡РёС‚СЊ РґРѕСЃС‚СѓРї", web_app=WebAppInfo(url=settings.webapp_url))],
        [InlineKeyboardButton(text="РњРѕРё СѓСЃС‚СЂРѕР№СЃС‚РІР°", callback_data="devices")],
        [
            InlineKeyboardButton(text="РРЅСЃС‚СЂСѓРєС†РёСЏ", callback_data="guide"),
            InlineKeyboardButton(text="РџРѕРґРґРµСЂР¶РєР°", url=settings.support_url),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="РћР±РЅРѕРІРёС‚СЊ", callback_data="admin_refresh")],
            [InlineKeyboardButton(text="РћС‚РєР»СЋС‡РёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РїРѕР·Р¶Рµ", callback_data="admin_disable_later")],
        ]
    )


def admin_text() -> str:
    settings = get_settings()
    return (
        "РђРґРјРёРЅ-РїР°РЅРµР»СЊ\n"
        f"РђРєС‚РёРІРЅС‹С… РєР»СЋС‡РµР№: {db.active_keys_count()} / {settings.max_users}\n"
        f"РџРѕР»СЊР·РѕРІР°С‚РµР»РµР№ РІ Р±Р°Р·Рµ: {db.users_count()}"
    )


def upsert_from_message(message: Message) -> dict:
    settings = get_settings()
    user = message.from_user
    return db.upsert_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        is_admin=settings.is_admin(user.id),
    )


def is_admin_message(message: Message) -> bool:
    settings = get_settings()
    return bool(message.from_user and settings.is_admin(message.from_user.id))


def is_admin_callback(callback: CallbackQuery) -> bool:
    settings = get_settings()
    return bool(callback.from_user and settings.is_admin(callback.from_user.id))


@router.message(CommandStart())
async def start(message: Message) -> None:
    upsert_from_message(message)
    await message.answer("ЧЕРЕМША VPN", reply_markup=start_keyboard())


@router.message(Command("admin"))
async def admin(message: Message) -> None:
    if not is_admin_message(message):
        return
    upsert_from_message(message)
    await message.answer(admin_text(), reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin_refresh")
async def admin_refresh(callback: CallbackQuery) -> None:
    if not is_admin_callback(callback):
        await callback.answer()
        return
    await callback.message.edit_text(admin_text(), reply_markup=admin_keyboard())
    await callback.answer("РћР±РЅРѕРІР»РµРЅРѕ")


@router.callback_query(F.data == "admin_disable_later")
async def admin_disable_later(callback: CallbackQuery) -> None:
    if not is_admin_callback(callback):
        await callback.answer()
        return
    await callback.answer("РџРѕР·Р¶Рµ РґРѕР±Р°РІРёРј РІС‹Р±РѕСЂ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ", show_alert=True)


@router.callback_query(F.data == "get_key")
async def get_key(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "РћС‚РєСЂРѕР№ mini app Рё РІС‹Р±РµСЂРё С‚Р°СЂРёС„. Р”РѕСЃС‚СѓРї РІС‹РґР°РµС‚СЃСЏ РїРѕСЃР»Рµ РѕРїР»Р°С‚С‹ Stars.",
        reply_markup=main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "devices")
async def devices(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "РЈСЃС‚СЂРѕР№СЃС‚РІР°:\n"
        "iPhone: FoXray РёР»Рё Streisand\n"
        "Android: v2rayNG\n"
        "Windows: Nekoray\n"
        "Mac: FoXray РёР»Рё V2Box\n\n"
        "РћС‚РєСЂРѕР№ mini app, С‚Р°Рј РµСЃС‚СЊ QR Рё РєРЅРѕРїРєРё РєРѕРїРёСЂРѕРІР°РЅРёСЏ.",
        reply_markup=main_keyboard(),
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    payment = db.get_payment_by_payload(query.invoice_payload)
    user = db.get_user_by_telegram_id(query.from_user.id)
    ok = (
        bool(payment)
        and bool(user)
        and payment["user_id"] == user["id"]
        and payment["status"] == "pending"
        and query.currency == "XTR"
        and query.total_amount == payment["stars"]
    )
    await query.answer(ok=ok, error_message="Tariff changed")


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    settings = get_settings()
    tg_user = message.from_user
    user = db.upsert_user(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        is_admin=settings.is_admin(tg_user.id),
    )
    payment_info = message.successful_payment
    payment = db.get_payment_by_payload(payment_info.invoice_payload)
    if not payment or payment["user_id"] != user["id"]:
        await message.answer(
            "РћРїР»Р°С‚Р° РїРѕР»СѓС‡РµРЅР°, РЅРѕ РїР»Р°С‚РµР¶ РЅРµ РЅР°Р№РґРµРЅ. РќР°РїРёС€Рё РІ РїРѕРґРґРµСЂР¶РєСѓ.",
            reply_markup=main_keyboard(),
        )
        return
    if payment["status"] == "paid" and db.user_vpn_status(user) == "active":
        try:
            vpn.build_client_config(user)
        except Exception as error:
            db.log_event(
                event_type="payment_active_config_failed",
                user_id=user["id"],
                uuid_value=user.get("uuid"),
                message=f"Active VPN config could not be built after Stars payment: {error}",
                metadata=payment_info.invoice_payload,
            )
            await message.answer(
                "РћРїР»Р°С‚Р° РїРѕР»СѓС‡РµРЅР°, РЅРѕ РєРѕРЅС„РёРі РЅРµ СЃРѕР±СЂР°Р»СЃСЏ РёР·-Р·Р° РѕС€РёР±РєРё РЅР°СЃС‚СЂРѕР№РєРё СЃРµСЂРІРµСЂР°. РќР°РїРёС€Рё РІ РїРѕРґРґРµСЂР¶РєСѓ.",
                reply_markup=main_keyboard(),
            )
            return
        await message.answer("Р”РѕСЃС‚СѓРї СѓР¶Рµ Р°РєС‚РёРІРµРЅ. РћС‚РєСЂРѕР№ mini app.", reply_markup=main_keyboard())
        return

    db.complete_payment(
        payload=payment_info.invoice_payload,
        telegram_payment_charge_id=payment_info.telegram_payment_charge_id,
        provider_payment_charge_id=payment_info.provider_payment_charge_id,
    )
    try:
        updated = vpn.activate_or_extend_user_key(
            user,
            days=payment["days"],
            traffic_limit_gb=payment["traffic_limit_gb"],
        )
        vpn.build_client_config(updated)
    except Exception as error:
        db.log_event(
            event_type="payment_access_failed",
            user_id=user["id"],
            uuid_value=user.get("uuid"),
            message=f"VPN access was not created after Stars payment: {error}",
            metadata=payment_info.invoice_payload,
        )
        await message.answer(
            "РћРїР»Р°С‚Р° РїРѕР»СѓС‡РµРЅР°, РЅРѕ РґРѕСЃС‚СѓРї РЅРµ Р±С‹Р» СЃРѕР·РґР°РЅ РёР·-Р·Р° РѕС€РёР±РєРё РЅР°СЃС‚СЂРѕР№РєРё СЃРµСЂРІРµСЂР°. РќР°РїРёС€Рё РІ РїРѕРґРґРµСЂР¶РєСѓ.",
            reply_markup=main_keyboard(),
        )
        return
    db.log_event(
        event_type="payment_access_created",
        user_id=user["id"],
        uuid_value=updated.get("uuid"),
        message=f"VPN access created after Stars payment for {payment['days']} days",
        metadata=payment_info.invoice_payload,
    )
    await message.answer(
        "РћРїР»Р°С‚Р° РїСЂРѕС€Р»Р°. Р”РѕСЃС‚СѓРї Р°РєС‚РёРІРёСЂРѕРІР°РЅ, QR Рё РєР»СЋС‡ СѓР¶Рµ РґРѕСЃС‚СѓРїРЅС‹ РІ mini app.",
        reply_markup=main_keyboard(),
    )


@router.callback_query(F.data == "guide")
async def guide(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "РРЅСЃС‚СЂСѓРєС†РёСЏ РєРѕСЂРѕС‚РєРѕ:\n"
        "1. РќР°Р¶РјРё В«РћС‚РєСЂС‹С‚СЊ VPNВ».\n"
        "2. РџРѕР»СѓС‡Рё РєР»СЋС‡.\n"
        "3. РЎРєРѕРїРёСЂСѓР№ СЃСЃС‹Р»РєСѓ РёР»Рё РѕС‚РєСЂРѕР№ QR.\n"
        "4. РРјРїРѕСЂС‚РёСЂСѓР№ РїСЂРѕС„РёР»СЊ РІ РїСЂРёР»РѕР¶РµРЅРёРµ РґР»СЏ СЃРІРѕРµРіРѕ СѓСЃС‚СЂРѕР№СЃС‚РІР°.",
        reply_markup=main_keyboard(),
    )
    await callback.answer()


async def run_bot() -> None:
    settings = get_settings()
    if not settings.bot_token:
        print("BOT_TOKEN is empty; Telegram bot is disabled in dev mode.")
        return
    print(f"Telegram bot startup: initializing dispatcher, WEBAPP_URL={settings.webapp_url}")
    db.init_db()
    session = None
    telegram_proxy_url = settings.telegram_proxy_url.strip()
    if telegram_proxy_url:
        print(f"Telegram bot startup: using proxy {telegram_proxy_url}")
        session = AiohttpSession(proxy=telegram_proxy_url)
    bot = Bot(settings.bot_token, session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        print("Telegram bot startup: deleting webhook before polling.")
        await bot.delete_webhook(drop_pending_updates=True)
        print("Telegram bot startup: polling started.")
        await dispatcher.start_polling(bot, handle_signals=False)
    finally:
        print("Telegram bot shutdown: closing bot session.")
        await bot.session.close()


