"""قابلیت‌های اضافی ادمین: کد تخفیف، کاربران، پیام همگانی، تست، کانال اجباری، درصد دعوت"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import asyncio

from config import settings
from database import (
    get_setting, set_setting, get_user, set_user_balance, set_user_blocked,
    search_users, count_users, get_all_user_ids, update_balance,
    add_coupon, list_coupons, get_coupon, delete_coupon,
    has_used_trial, mark_trial_used,
)
from keyboards import admin_menu, back_admin, coupons_admin_kb, user_manage_kb, back_to_menu
from panel_api import get_client_from_db
import secrets
import json

router = Router()


class ExtraStates(StatesGroup):
    coupon_code = State()
    coupon_type = State()
    coupon_value = State()
    coupon_max = State()
    search_user = State()
    set_balance = State()
    add_balance = State()
    broadcast = State()
    ref_percent = State()
    trial_days = State()
    trial_gb = State()
    force_channel = State()
    custom_name = State()


def _admin(uid: int) -> bool:
    return uid in settings.admins


# ---------- کد تخفیف ----------
@router.callback_query(F.data == "adm:coupons")
async def adm_coupons(cb: CallbackQuery):
    if not _admin(cb.from_user.id):
        return
    coupons = await list_coupons()
    text = "🎟 <b>کدهای تخفیف</b>\n\n" + (f"{len(coupons)} کد ثبت شده." if coupons else "هنوز کدی نیست.")
    await cb.message.edit_text(text, reply_markup=coupons_admin_kb(coupons), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "adm:addcoupon")
async def adm_addcoupon(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    await state.set_state(ExtraStates.coupon_code)
    await cb.message.edit_text("کد تخفیف را وارد کنید (مثال: OFF20):", reply_markup=back_admin())
    await cb.answer()


@router.message(ExtraStates.coupon_code)
async def coupon_code(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    code = msg.text.strip().upper()
    if await get_coupon(code):
        await msg.answer("این کد از قبل وجود دارد. کد دیگری بفرستید.")
        return
    await state.update_data(code=code)
    await state.set_state(ExtraStates.coupon_type)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="درصدی %", callback_data="cptype:percent")],
        [InlineKeyboardButton(text="مبلغی (تومان)", callback_data="cptype:fixed")],
    ])
    await msg.answer("نوع تخفیف را انتخاب کنید:", reply_markup=kb)


@router.callback_query(F.data.startswith("cptype:"))
async def coupon_type(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    dtype = cb.data.split(":")[1]
    await state.update_data(discount_type=dtype)
    await state.set_state(ExtraStates.coupon_value)
    unit = "درصد (مثلاً 20)" if dtype == "percent" else "مبلغ به تومان (مثلاً 10000)"
    await cb.message.edit_text(f"مقدار تخفیف را وارد کنید:\n{unit}")
    await cb.answer()


@router.message(ExtraStates.coupon_value)
async def coupon_value(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    try:
        val = int(msg.text.strip().replace(",", ""))
    except Exception:
        await msg.answer("عدد معتبر وارد کنید.")
        return
    await state.update_data(discount_value=val)
    await state.set_state(ExtraStates.coupon_max)
    await msg.answer("حداکثر تعداد استفاده را وارد کنید (0 = نامحدود):")


@router.message(ExtraStates.coupon_max)
async def coupon_max(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    try:
        mx = int(msg.text.strip())
    except Exception:
        await msg.answer("عدد معتبر وارد کنید.")
        return
    data = await state.get_data()
    cid = await add_coupon(
        data["code"], data["discount_type"], data["discount_value"], max_uses=mx
    )
    await state.clear()
    await msg.answer(f"✅ کد تخفیف `{data['code']}` ساخته شد (آیدی {cid}).", reply_markup=admin_menu(), parse_mode="Markdown")


@router.callback_query(F.data.startswith("adm:couponinfo:"))
async def coupon_info(cb: CallbackQuery):
    if not _admin(cb.from_user.id):
        return
    from database import list_coupons
    cid = int(cb.data.split(":")[2])
    coupons = await list_coupons()
    c = next((x for x in coupons if x["id"] == cid), None)
    if not c:
        await cb.answer("پیدا نشد")
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 حذف", callback_data=f"adm:delcoupon:{cid}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:coupons")],
    ])
    dtype = "%" if c["discount_type"] == "percent" else " تومان"
    text = (
        f"کد: <code>{c['code']}</code>\n"
        f"تخفیف: {c['discount_value']}{dtype}\n"
        f"استفاده: {c['used_count']} / {c['max_uses'] or '∞'}"
    )
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:delcoupon:"))
async def del_coupon(cb: CallbackQuery):
    if not _admin(cb.from_user.id):
        return
    cid = int(cb.data.split(":")[2])
    await delete_coupon(cid)
    await cb.answer("حذف شد")
    coupons = await list_coupons()
    await cb.message.edit_text("🎟 کدهای تخفیف", reply_markup=coupons_admin_kb(coupons))


# ---------- مدیریت کاربران ----------
@router.callback_query(F.data == "adm:users")
async def adm_users(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    total = await count_users()
    await state.set_state(ExtraStates.search_user)
    await cb.message.edit_text(
        f"👥 تعداد کل کاربران: <b>{total}</b>\n\n"
        f"آیدی عددی یا یوزرنیم کاربر را برای جستجو ارسال کنید:",
        reply_markup=back_admin(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(ExtraStates.search_user)
async def search_user_msg(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    q = msg.text.strip().lstrip("@")
    users = await search_users(q)
    if not users:
        # اگر فقط عدد بود مستقیم بگیر
        try:
            uid = int(q)
            u = await get_user(uid)
            if u:
                users = [u]
        except Exception:
            pass
    if not users:
        await msg.answer("کاربری پیدا نشد. دوباره جستجو کنید یا /cancel")
        return
    await state.clear()
    if len(users) == 1:
        u = users[0]
        text = (
            f"👤 <b>{u.get('full_name') or '—'}</b>\n"
            f"آیدی: <code>{u['tg_id']}</code>\n"
            f"یوزرنیم: @{u.get('username') or '—'}\n"
            f"موجودی: <b>{u.get('balance', 0):,}</b> تومان\n"
            f"مسدود: {'بله 🚫' if u.get('is_blocked') else 'خیر'}\n"
            f"معرف: {u.get('ref_by') or '—'}"
        )
        await msg.answer(text, reply_markup=user_manage_kb(u["tg_id"]), parse_mode="HTML")
    else:
        lines = [f"نتایج ({len(users)}):"]
        for u in users[:15]:
            lines.append(f"• {u['tg_id']} | @{u.get('username') or '—'} | {u.get('balance', 0):,}")
        await msg.answer("\n".join(lines) + "\n\nآیدی دقیق را بفرستید تا مدیریت شود.", reply_markup=back_admin())


@router.callback_query(F.data.startswith("adm:setbal:"))
async def adm_setbal(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[2])
    await state.update_data(target_uid=uid)
    await state.set_state(ExtraStates.set_balance)
    await cb.message.answer(f"موجودی جدید کاربر {uid} را به تومان وارد کنید:")
    await cb.answer()


@router.message(ExtraStates.set_balance)
async def set_balance_msg(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    try:
        bal = int(msg.text.strip().replace(",", ""))
    except Exception:
        await msg.answer("عدد معتبر وارد کنید.")
        return
    data = await state.get_data()
    uid = data["target_uid"]
    await set_user_balance(uid, bal)
    await state.clear()
    try:
        await msg.bot.send_message(uid, f"💰 موجودی شما توسط ادمین به {bal:,} تومان تغییر کرد.")
    except Exception:
        pass
    await msg.answer(f"✅ موجودی کاربر {uid} = {bal:,} تومان", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("adm:addbal:"))
async def adm_addbal(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[2])
    await state.update_data(target_uid=uid)
    await state.set_state(ExtraStates.add_balance)
    await cb.message.answer(f"مبلغی که می‌خواهید به موجودی کاربر {uid} اضافه شود:")
    await cb.answer()


@router.message(ExtraStates.add_balance)
async def add_balance_msg(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    try:
        amount = int(msg.text.strip().replace(",", ""))
    except Exception:
        await msg.answer("عدد معتبر وارد کنید.")
        return
    data = await state.get_data()
    uid = data["target_uid"]
    await update_balance(uid, amount)
    await state.clear()
    try:
        await msg.bot.send_message(uid, f"💰 {amount:,} تومان به موجودی شما اضافه شد.")
    except Exception:
        pass
    await msg.answer(f"✅ {amount:,} تومان به کاربر {uid} اضافه شد.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("adm:block:"))
async def adm_block(cb: CallbackQuery):
    if not _admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[2])
    await set_user_blocked(uid, True)
    await cb.answer("مسدود شد")
    await cb.message.answer(f"🚫 کاربر {uid} مسدود شد.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("adm:unblock:"))
async def adm_unblock(cb: CallbackQuery):
    if not _admin(cb.from_user.id):
        return
    uid = int(cb.data.split(":")[2])
    await set_user_blocked(uid, False)
    await cb.answer("رفع مسدودی")
    await cb.message.answer(f"✅ مسدودی کاربر {uid} برداشته شد.", reply_markup=admin_menu())


# ---------- درصد دعوت ----------
@router.callback_query(F.data == "adm:ref_percent")
async def adm_ref(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    cur = await get_setting("ref_percent", "20")
    await state.set_state(ExtraStates.ref_percent)
    await cb.message.edit_text(
        f"درصد فعلی دعوت دوستان: <b>{cur}%</b>\n\nدرصد جدید را وارد کنید (0 تا 100):",
        reply_markup=back_admin(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(ExtraStates.ref_percent)
async def set_ref_percent(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    try:
        p = int(msg.text.strip())
        if not 0 <= p <= 100:
            raise ValueError()
    except Exception:
        await msg.answer("عدد بین 0 تا 100 وارد کنید.")
        return
    await set_setting("ref_percent", str(p))
    await state.clear()
    await msg.answer(f"✅ درصد دعوت = {p}%", reply_markup=admin_menu())


# ---------- پیام همگانی ----------
@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    await state.set_state(ExtraStates.broadcast)
    await cb.message.edit_text(
        "متن پیام همگانی را ارسال کنید:\n(برای همه کاربران غیرمسدود ارسال می‌شود)",
        reply_markup=back_admin(),
    )
    await cb.answer()


@router.message(ExtraStates.broadcast)
async def do_broadcast(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    text = msg.text or msg.caption or ""
    if not text:
        await msg.answer("متن خالی است.")
        return
    await state.clear()
    ids = await get_all_user_ids()
    if len(ids) > 5000:
        await msg.answer("تعداد کاربران خیلی زیاد است. از ابزار خارجی استفاده کنید.")
        return
    # جلوگیری از HTML خطرناک ساده
    from html import escape as _esc
    safe_text = text  # ادمین خودش HTML می‌فرستد؛ طول را محدود کن
    if len(safe_text) > 3500:
        await msg.answer("متن پیام خیلی طولانی است (حداکثر ۳۵۰۰ کاراکتر).")
        return
    await msg.answer(f"در حال ارسال به {len(ids)} کاربر...")
    ok = fail = 0
    for uid in ids:
        try:
            await msg.bot.send_message(uid, safe_text)
            ok += 1
            await asyncio.sleep(0.07)  # احترام به rate limit تلگرام
        except Exception:
            fail += 1
    await msg.answer(f"✅ ارسال شد: {ok}\n❌ ناموفق: {fail}", reply_markup=admin_menu())


# ---------- تنظیم تست ----------
@router.callback_query(F.data == "adm:trial_set")
async def adm_trial_set(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    days = await get_setting("trial_days", "1")
    gb = await get_setting("trial_gb", "1")
    en = await get_setting("trial_enabled", "1")
    await state.set_state(ExtraStates.trial_days)
    await cb.message.edit_text(
        f"🎁 تنظیم اکانت تست\nفعال: {'بله' if en == '1' else 'خیر'}\nروز: {days} | حجم: {gb}GB\n\nتعداد روز تست را وارد کنید (0 = غیرفعال):",
        reply_markup=back_admin(),
    )
    await cb.answer()


@router.message(ExtraStates.trial_days)
async def trial_days_msg(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    try:
        d = int(msg.text.strip())
    except Exception:
        await msg.answer("عدد وارد کنید.")
        return
    if d <= 0:
        await set_setting("trial_enabled", "0")
        await state.clear()
        await msg.answer("اکانت تست غیرفعال شد.", reply_markup=admin_menu())
        return
    await set_setting("trial_days", str(d))
    await set_setting("trial_enabled", "1")
    await state.set_state(ExtraStates.trial_gb)
    await msg.answer("حجم تست به گیگابایت را وارد کنید:")


@router.message(ExtraStates.trial_gb)
async def trial_gb_msg(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    try:
        g = int(msg.text.strip())
    except Exception:
        await msg.answer("عدد وارد کنید.")
        return
    await set_setting("trial_gb", str(g))
    await state.clear()
    await msg.answer(f"✅ تست فعال شد: {await get_setting('trial_days')} روز / {g}GB", reply_markup=admin_menu())


# ---------- کانال اجباری ----------
@router.callback_query(F.data == "adm:force_ch")
async def adm_force_ch(cb: CallbackQuery, state: FSMContext):
    if not _admin(cb.from_user.id):
        return
    cur = await get_setting("force_channel", "")
    await state.set_state(ExtraStates.force_channel)
    await cb.message.edit_text(
        f"کانال اجباری فعلی: {cur or 'غیرفعال'}\n\n"
        f"یوزرنیم کانال را با @ بفرستید (مثال: @mychannel)\n"
        f"یا کلمه off برای غیرفعال کردن:",
        reply_markup=back_admin(),
    )
    await cb.answer()


@router.message(ExtraStates.force_channel)
async def set_force_ch(msg: Message, state: FSMContext):
    if not _admin(msg.from_user.id):
        return
    t = msg.text.strip()
    if t.lower() in ("off", "0", "غیرفعال"):
        await set_setting("force_channel", "")
        await set_setting("force_channel_id", "0")
        await state.clear()
        await msg.answer("کانال اجباری غیرفعال شد.", reply_markup=admin_menu())
        return
    if not t.startswith("@"):
        t = "@" + t
    await set_setting("force_channel", t)
    await state.clear()
    await msg.answer(
        f"✅ کانال اجباری: {t}\n"
        f"ربات باید ادمین کانال باشد تا بتواند عضویت را چک کند.",
        reply_markup=admin_menu(),
    )
