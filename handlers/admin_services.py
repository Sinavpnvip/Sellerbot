"""مدیریت کامل سرویس‌ها توسط ادمین روی پنل JinX/PasarGuard"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from html import escape as esc
from datetime import datetime, timezone

from config import settings
from database import get_user, get_user_orders, get_order_by_id, search_users
from keyboards import admin_menu, back_admin
from panel_api import get_client_from_db

router = Router()


class AdmSvcStates(StatesGroup):
    find = State()
    add_days = State()
    sub_days = State()
    add_gb = State()
    sub_gb = State()
    set_gb = State()
    set_days = State()
    by_username = State()


def _adm(uid: int) -> bool:
    return uid in settings.admins


def _fmt_bytes(n) -> str:
    try:
        n = float(n or 0)
    except Exception:
        return "—"
    if n <= 0:
        return "۰/نامحدود"
    gb = n / (1024 ** 3)
    return f"{gb:.2f} GB" if gb >= 1 else f"{n/(1024**2):.1f} MB"


def _exp(raw) -> str:
    if not raw:
        return "نامحدود"
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000
            if ts <= 0:
                return "—"
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        left = dt - datetime.now(timezone.utc)
        d = int(left.total_seconds() // 86400)
        return dt.strftime("%Y-%m-%d %H:%M") + f" ({d}d)"
    except Exception:
        return str(raw)


def svc_manage_kb(uname: str, oid: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    u = uname  # in callback we use order id preferred
    prefix = f"as:{oid}:{uname}" if oid else f"as:0:{uname}"
    b.row(InlineKeyboardButton(text="📡 وضعیت پنل", callback_data=f"{prefix}:status"))
    b.row(
        InlineKeyboardButton(text="➕ روز", callback_data=f"{prefix}:addd"),
        InlineKeyboardButton(text="➖ روز", callback_data=f"{prefix}:subd"),
    )
    b.row(
        InlineKeyboardButton(text="➕ حجم GB", callback_data=f"{prefix}:addg"),
        InlineKeyboardButton(text="➖ حجم GB", callback_data=f"{prefix}:subg"),
    )
    b.row(
        InlineKeyboardButton(text="📅 تنظیم روز مانده", callback_data=f"{prefix}:setd"),
        InlineKeyboardButton(text="📊 تنظیم سقف GB", callback_data=f"{prefix}:setg"),
    )
    b.row(
        InlineKeyboardButton(text="🟢 فعال", callback_data=f"{prefix}:on"),
        InlineKeyboardButton(text="🔴 غیرفعال", callback_data=f"{prefix}:off"),
    )
    b.row(InlineKeyboardButton(text="🗑 حذف از پنل", callback_data=f"{prefix}:del"))
    b.row(InlineKeyboardButton(text="⬅️ پنل ادمین", callback_data="admin"))
    return b.as_markup()


@router.callback_query(F.data == "adm:svc")
async def adm_svc_entry(cb: CallbackQuery, state: FSMContext):
    if not _adm(cb.from_user.id):
        return
    await state.set_state(AdmSvcStates.find)
    await cb.message.edit_text(
        "🛠 <b>مدیریت سرویس پنل</b>\n\n"
        "آیدی عددی تلگرام کاربر، یا یوزرنیم پنل را بفرستید:\n"
        "مثال: <code>123456789</code>\n"
        "یا: <code>u123456789_abc</code>",
        parse_mode="HTML",
        reply_markup=back_admin(),
    )
    await cb.answer()


@router.message(AdmSvcStates.find)
async def adm_svc_find(msg: Message, state: FSMContext):
    if not _adm(msg.from_user.id):
        return
    q = (msg.text or "").strip()
    await state.clear()
    # numeric = telegram id
    if q.isdigit():
        uid = int(q)
        orders = await get_user_orders(uid, 30)
        if not orders:
            await msg.answer("سفارشی برای این کاربر نیست. یوزرنیم پنل را بفرستید یا از منو دوباره.", reply_markup=admin_menu())
            return
        b = InlineKeyboardBuilder()
        for o in orders:
            un = o.get("panel_username") or "?"
            b.row(InlineKeyboardButton(
                text=f"🔷 {un}",
                callback_data=f"as:{o['id']}:{un}:menu",
            ))
        b.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin"))
        await msg.answer(f"سرویس‌های کاربر <code>{uid}</code>:", parse_mode="HTML", reply_markup=b.as_markup())
        return
    # treat as panel username
    uname = q.lstrip("@")
    await msg.answer(
        f"مدیریت <code>{esc(uname)}</code>:",
        parse_mode="HTML",
        reply_markup=svc_manage_kb(uname, 0),
    )


def _parse_as(data: str):
    # as:{oid}:{uname}:{action}
    parts = data.split(":", 3)
    if len(parts) < 4:
        return None
    _, oid_s, uname, action = parts
    return int(oid_s), uname, action


@router.callback_query(F.data.startswith("as:"))
async def adm_svc_actions(cb: CallbackQuery, state: FSMContext):
    if not _adm(cb.from_user.id):
        return
    parsed = _parse_as(cb.data)
    if not parsed:
        await cb.answer("داده نامعتبر")
        return
    oid, uname, action = parsed

    if action == "menu":
        await cb.message.edit_text(
            f"🛠 مدیریت <code>{esc(uname)}</code>",
            parse_mode="HTML",
            reply_markup=svc_manage_kb(uname, oid),
        )
        await cb.answer()
        return

    client = await get_client_from_db()
    if not client and action != "menu":
        await cb.answer("پنل متصل نیست", show_alert=True)
        return

    if action == "status":
        data, err = await client.get_user(uname)
        await client.close()
        if err or not data:
            await cb.answer(err or "خطا", show_alert=True)
            return
        text = (
            f"📡 <b>{esc(uname)}</b>\n"
            f"وضعیت: <b>{esc(str(data.get('status')))}</b>\n"
            f"مصرف: {_fmt_bytes(data.get('used_traffic') or 0)}\n"
            f"سقف: {_fmt_bytes(data.get('data_limit') or 0)}\n"
            f"انقضا: {_exp(data.get('expire'))}\n"
        )
        await cb.message.edit_text(text, parse_mode="HTML", reply_markup=svc_manage_kb(uname, oid))
        await cb.answer()
        return

    if action == "on":
        ok, err = await client.set_status(uname, "active")
        await client.close()
        await cb.answer("فعال شد ✅" if ok else err, show_alert=not ok)
        return
    if action == "off":
        ok, err = await client.set_status(uname, "disabled")
        await client.close()
        await cb.answer("غیرفعال شد" if ok else err, show_alert=not ok)
        return
    if action == "del":
        ok, err = await client.delete_user(uname)
        await client.close()
        if ok:
            await cb.message.edit_text(f"🗑 حذف شد: <code>{esc(uname)}</code>", parse_mode="HTML", reply_markup=admin_menu())
        await cb.answer("حذف شد" if ok else err, show_alert=not ok)
        return

    # need number input
    map_state = {
        "addd": (AdmSvcStates.add_days, "چند روز اضافه شود؟ (عدد)"),
        "subd": (AdmSvcStates.sub_days, "چند روز کم شود؟ (عدد)"),
        "addg": (AdmSvcStates.add_gb, "چند گیگ اضافه؟ (عدد)"),
        "subg": (AdmSvcStates.sub_gb, "چند گیگ کم؟ (عدد)"),
        "setd": (AdmSvcStates.set_days, "انقضا چند روز از الان؟ (عدد)"),
        "setg": (AdmSvcStates.set_gb, "سقف حجم چند گیگ باشد؟ (0=نامحدود)"),
    }
    if action in map_state:
        await client.close()
        st, prompt = map_state[action]
        await state.set_state(st)
        await state.update_data(svc_uname=uname, svc_oid=oid)
        await cb.message.answer(prompt)
        await cb.answer()
        return

    await client.close()
    await cb.answer("نامشخص")


async def _apply_num(msg: Message, state: FSMContext, kind: str):
    if not _adm(msg.from_user.id):
        return
    try:
        n = int((msg.text or "").strip())
    except Exception:
        await msg.answer("عدد معتبر بفرستید.")
        return
    data = await state.get_data()
    uname = data.get("svc_uname")
    await state.clear()
    if not uname:
        await msg.answer("نشست منقضی. دوباره از مدیریت سرویس.", reply_markup=admin_menu())
        return
    client = await get_client_from_db()
    if not client:
        await msg.answer("پنل متصل نیست.", reply_markup=admin_menu())
        return
    ok, err = False, "—"
    if kind == "addd":
        ok, err = await client.admin_adjust_days(uname, abs(n))
    elif kind == "subd":
        ok, err = await client.admin_adjust_days(uname, -abs(n))
    elif kind == "addg":
        ok, err = await client.admin_adjust_gb(uname, abs(n))
    elif kind == "subg":
        ok, err = await client.admin_adjust_gb(uname, -abs(n))
    elif kind == "setd":
        ok, err = await client.admin_set_expire_days(uname, abs(n))
    elif kind == "setg":
        ok, err = await client.admin_set_data_gb(uname, n)
    await client.close()
    if ok:
        await msg.answer(f"✅ انجام شد روی <code>{esc(uname)}</code>", parse_mode="HTML", reply_markup=svc_manage_kb(uname, int(data.get("svc_oid") or 0)))
    else:
        await msg.answer(f"❌ خطا: {err}", reply_markup=admin_menu())


@router.message(AdmSvcStates.add_days)
async def adm_add_days(m: Message, s: FSMContext):
    await _apply_num(m, s, "addd")

@router.message(AdmSvcStates.sub_days)
async def adm_sub_days(m: Message, s: FSMContext):
    await _apply_num(m, s, "subd")

@router.message(AdmSvcStates.add_gb)
async def adm_add_gb(m: Message, s: FSMContext):
    await _apply_num(m, s, "addg")

@router.message(AdmSvcStates.sub_gb)
async def adm_sub_gb(m: Message, s: FSMContext):
    await _apply_num(m, s, "subg")

@router.message(AdmSvcStates.set_days)
async def adm_set_days(m: Message, s: FSMContext):
    await _apply_num(m, s, "setd")

@router.message(AdmSvcStates.set_gb)
async def adm_set_gb(m: Message, s: FSMContext):
    await _apply_num(m, s, "setg")
