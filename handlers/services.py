"""سرویس‌های من: وضعیت زنده، تمدید، حجم اضافه"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from html import escape as esc
from datetime import datetime, timezone
import logging

from config import settings
from database import (
    get_user, get_setting, get_plans, get_plan, update_balance,
    get_user_orders, get_order_by_id, get_volume_packs, get_volume_pack,
    is_user_blocked,
)
from keyboards import back_to_menu, low_balance_kb
from panel_api import get_client_from_db
from locks import acquire_user, release_user

router = Router()
logger = logging.getLogger(__name__)


def _admin(uid: int) -> bool:
    return uid in settings.admins


async def _blocked(uid: int) -> bool:
    return await is_user_blocked(uid)


def _fmt_bytes(n) -> str:
    try:
        n = float(n or 0)
    except Exception:
        return "—"
    if n <= 0:
        return "۰ / نامحدود"
    gb = n / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    mb = n / (1024 ** 2)
    return f"{mb:.1f} MB"


def _parse_expire(raw) -> datetime | None:
    if raw is None or raw == "" or raw == 0:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            if ts <= 0:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def service_actions_kb(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📡 وضعیت زنده", callback_data=f"svc:status:{order_id}"))
    b.row(
        InlineKeyboardButton(text="♻️ تمدید", callback_data=f"svc:renew:{order_id}"),
        InlineKeyboardButton(text="📶 حجم اضافه", callback_data=f"svc:vol:{order_id}"),
    )
    b.row(InlineKeyboardButton(text="🔗 لینک ساب", callback_data=f"svc:link:{order_id}"))
    b.row(InlineKeyboardButton(text="✨ همه سرویس‌ها", callback_data="mysubs"))
    b.row(InlineKeyboardButton(text="🏠 منو", callback_data="menu"))
    return b.as_markup()


def renew_plans_kb(order_id: int, plans: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in plans:
        b.row(InlineKeyboardButton(
            text=f"♻️ {p['title']} — {p['price']:,} ت ({p['days']} روز)",
            callback_data=f"svc:do_renew:{order_id}:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"svc:open:{order_id}"))
    return b.as_markup()


def volume_packs_kb(order_id: int, packs: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in packs:
        b.row(InlineKeyboardButton(
            text=f"📶 {p['title']} — {p['price']:,} ت ({p['gb']}GB)",
            callback_data=f"svc:do_vol:{order_id}:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"svc:open:{order_id}"))
    return b.as_markup()


@router.callback_query(F.data == "mysubs")
async def cb_mysubs(callback: CallbackQuery):
    if await _blocked(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    rows = await get_user_orders(callback.from_user.id, 20)
    if not rows:
        try:
            await callback.message.edit_text(
                "✨ هنوز سرویسی ندارید.\nاز بخش خرید اشتراک شروع کنید.",
                reply_markup=back_to_menu(),
            )
        except Exception:
            pass
        await callback.answer()
        return
    b = InlineKeyboardBuilder()
    for r in rows:
        uname = r.get("panel_username") or f"#{r['id']}"
        b.row(InlineKeyboardButton(
            text=f"🔷 {uname}",
            callback_data=f"svc:open:{r['id']}",
        ))
    b.row(InlineKeyboardButton(text="🏠 منو", callback_data="menu"))
    text = (
        "╭─ ✨ <b>سرویس‌های من</b>\n"
        "│ یکی را انتخاب کنید:\n"
        "│ وضعیت • تمدید • حجم اضافه\n"
        "╰─"
    )
    try:
        await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("svc:open:"))
async def svc_open(callback: CallbackQuery):
    oid = int(callback.data.split(":")[2])
    order = await get_order_by_id(oid)
    if not order or order.get("user_id") != callback.from_user.id:
        await callback.answer("سرویس یافت نشد", show_alert=True)
        return
    uname = esc(str(order.get("panel_username") or "—"))
    sub = esc(str(order.get("sub_url") or "—"))
    text = (
        f"╭─ 🔷 <b>سرویس</b>\n"
        f"│ یوزرنیم: <code>{uname}</code>\n"
        f"│ لینک:\n"
        f"│ <code>{sub}</code>\n"
        f"╰─ از دکمه‌ها استفاده کنید"
    )
    try:
        await callback.message.edit_text(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("svc:link:"))
async def svc_link(callback: CallbackQuery):
    oid = int(callback.data.split(":")[2])
    order = await get_order_by_id(oid)
    if not order or order.get("user_id") != callback.from_user.id:
        await callback.answer("نیست", show_alert=True)
        return
    sub = order.get("sub_url") or ""
    await callback.message.answer(f"🔗 لینک اشتراک:\n<code>{esc(sub)}</code>", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("svc:status:"))
async def svc_status(callback: CallbackQuery):
    if (await get_setting("status_enabled", "1")) != "1":
        await callback.answer("این بخش غیرفعال است", show_alert=True)
        return
    oid = int(callback.data.split(":")[2])
    order = await get_order_by_id(oid)
    if not order or order.get("user_id") != callback.from_user.id:
        await callback.answer("نیست", show_alert=True)
        return
    uname = order.get("panel_username") or ""
    client = await get_client_from_db()
    if not client:
        await callback.answer("پنل متصل نیست", show_alert=True)
        return
    data, err = await client.get_user(uname)
    await client.close()
    if err or not data:
        await callback.answer(f"خطا: {err or 'نامشخص'}", show_alert=True)
        return

    used = data.get("used_traffic") or data.get("upload", 0) + data.get("download", 0)
    limit = data.get("data_limit") or 0
    expire = _parse_expire(data.get("expire"))
    status = data.get("status") or "—"
    now = datetime.now(timezone.utc)
    if expire:
        left = expire - now
        days_left = max(int(left.total_seconds() // 86400), 0)
        exp_s = expire.strftime("%Y-%m-%d %H:%M") + f" UTC ({days_left} روز مانده)"
    else:
        exp_s = "نامحدود"

    text = (
        f"╭─ 📡 <b>وضعیت زنده</b>\n"
        f"│ یوزرنیم: <code>{esc(uname)}</code>\n"
        f"│ وضعیت: <b>{esc(str(status))}</b>\n"
        f"│ مصرف: <b>{_fmt_bytes(used)}</b>\n"
        f"│ سقف حجم: <b>{_fmt_bytes(limit)}</b>\n"
        f"│ انقضا: <b>{esc(exp_s)}</b>\n"
        f"╰─"
    )
    try:
        await callback.message.edit_text(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("svc:renew:"))
async def svc_renew_menu(callback: CallbackQuery):
    if (await get_setting("renew_enabled", "1")) != "1":
        await callback.answer("تمدید غیرفعال است", show_alert=True)
        return
    oid = int(callback.data.split(":")[2])
    order = await get_order_by_id(oid)
    if not order or order.get("user_id") != callback.from_user.id:
        await callback.answer("نیست", show_alert=True)
        return
    plans = await get_plans(active_only=True)
    if not plans:
        await callback.answer("پلنی نیست", show_alert=True)
        return
    text = (
        f"♻️ <b>تمدید سرویس</b>\n"
        f"<code>{esc(str(order.get('panel_username')))}</code>\n\n"
        f"مدت تمدید را انتخاب کنید (از موجودی کیف پول کسر می‌شود):"
    )
    try:
        await callback.message.edit_text(text, reply_markup=renew_plans_kb(oid, plans), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=renew_plans_kb(oid, plans), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("svc:do_renew:"))
async def svc_do_renew(callback: CallbackQuery):
    if (await get_setting("renew_enabled", "1")) != "1":
        await callback.answer("غیرفعال", show_alert=True)
        return
    uid = callback.from_user.id
    if not await acquire_user(uid):
        await callback.answer("⏳ در حال پردازش…", show_alert=True)
        return
    try:
        parts = callback.data.split(":")
        oid, plan_id = int(parts[2]), int(parts[3])
        order = await get_order_by_id(oid)
        plan = await get_plan(plan_id)
        u = await get_user(uid)
        if not order or order.get("user_id") != uid or not plan or not u:
            await callback.answer("خطا", show_alert=True)
            return
        if not plan.get("is_active", 1):
            await callback.answer("پلن غیرفعال", show_alert=True)
            return
        price = max(int(plan["price"]), 0)
        days = max(int(plan["days"]), 0)
        if days <= 0 or price < 0:
            await callback.answer("پلن نامعتبر", show_alert=True)
            return
        ok = await update_balance(uid, -price)
        if not ok:
            try:
                await callback.message.edit_text(
                    f"⚠️ موجودی کافی نیست.\nنیاز: {price:,}",
                    reply_markup=low_balance_kb(),
                )
            except Exception:
                pass
            await callback.answer("موجودی کافی نیست", show_alert=True)
            return
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        client = await get_client_from_db()
        if not client:
            await update_balance(uid, price)
            await callback.answer("پنل متصل نیست", show_alert=True)
            return
        success, err = await client.modify_user(str(order["panel_username"]), extra_days=days, extra_gb=0)
        await client.close()
        if not success:
            await update_balance(uid, price)
            await callback.answer(f"خطای پنل: {err}", show_alert=True)
            return
        text = (
            f"✅ <b>تمدید موفق</b>\n"
            f"+{days} روز روی <code>{esc(str(order['panel_username']))}</code>\n"
            f"مبلغ: {price:,} تومان"
        )
        try:
            await callback.message.edit_text(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
        await callback.answer("تمدید شد ✅")
    finally:
        await release_user(uid)


@router.callback_query(F.data.startswith("svc:vol:"))
async def svc_vol_menu(callback: CallbackQuery):
    if (await get_setting("volume_enabled", "1")) != "1":
        await callback.answer("حجم اضافه غیرفعال است", show_alert=True)
        return
    oid = int(callback.data.split(":")[2])
    order = await get_order_by_id(oid)
    if not order or order.get("user_id") != callback.from_user.id:
        await callback.answer("نیست", show_alert=True)
        return
    packs = await get_volume_packs(active_only=True)
    if not packs:
        await callback.answer("پکیج حجمی تعریف نشده. از ادمین بخواهید.", show_alert=True)
        return
    text = (
        f"📶 <b>خرید حجم اضافه</b>\n"
        f"<code>{esc(str(order.get('panel_username')))}</code>\n\n"
        f"پکیج را انتخاب کنید:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=volume_packs_kb(oid, packs), parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=volume_packs_kb(oid, packs), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("svc:do_vol:"))
async def svc_do_vol(callback: CallbackQuery):
    if (await get_setting("volume_enabled", "1")) != "1":
        await callback.answer("غیرفعال", show_alert=True)
        return
    uid = callback.from_user.id
    if not await acquire_user(uid):
        await callback.answer("⏳ در حال پردازش…", show_alert=True)
        return
    try:
        parts = callback.data.split(":")
        oid, pack_id = int(parts[2]), int(parts[3])
        order = await get_order_by_id(oid)
        pack = await get_volume_pack(pack_id)
        u = await get_user(uid)
        if not order or order.get("user_id") != uid or not pack or not u:
            await callback.answer("خطا", show_alert=True)
            return
        if not pack.get("is_active", 1):
            await callback.answer("پکیج غیرفعال", show_alert=True)
            return
        price = max(int(pack["price"]), 0)
        gb = max(int(pack["gb"]), 0)
        if gb <= 0:
            await callback.answer("پکیج نامعتبر", show_alert=True)
            return
        ok = await update_balance(uid, -price)
        if not ok:
            try:
                await callback.message.edit_text(
                    f"⚠️ موجودی کافی نیست.\nنیاز: {price:,}",
                    reply_markup=low_balance_kb(),
                )
            except Exception:
                pass
            await callback.answer("موجودی کافی نیست", show_alert=True)
            return
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        client = await get_client_from_db()
        if not client:
            await update_balance(uid, price)
            await callback.answer("پنل متصل نیست", show_alert=True)
            return
        success, err = await client.modify_user(str(order["panel_username"]), extra_days=0, extra_gb=gb)
        await client.close()
        if not success:
            await update_balance(uid, price)
            await callback.answer(f"خطای پنل: {err}", show_alert=True)
            return
        text = (
            f"✅ <b>حجم اضافه شد</b>\n"
            f"+{gb} GB روی <code>{esc(str(order['panel_username']))}</code>\n"
            f"مبلغ: {price:,} تومان"
        )
        try:
            await callback.message.edit_text(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=service_actions_kb(oid), parse_mode="HTML")
        await callback.answer("انجام شد ✅")
    finally:
        await release_user(uid)
