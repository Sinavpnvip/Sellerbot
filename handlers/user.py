from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import re
import secrets

from config import settings
from database import (
    ensure_user, get_user, get_setting, get_plans, get_plan,
    update_balance, create_order, complete_order, add_receipt,
    set_ref,
)
from keyboards import main_menu, back_to_menu, plans_kb, confirm_buy_kb, receipt_action_kb
from panel_api import get_client_from_db

router = Router()


class DepositState(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admins


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    args = message.text.split(maxsplit=1)
    user = await ensure_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or "",
    )

    # ریفرال
    if len(args) > 1:
        code = args[1].strip()
        if code.startswith("ref"):
            try:
                ref_id = int(code.replace("ref", ""))
                if ref_id != message.from_user.id:
                    await set_ref(message.from_user.id, ref_id)
            except Exception:
                pass

    welcome = await get_setting("welcome_text", "به فروشگاه خوش آمدید 👋")
    title = await get_setting("shop_title", "فروشگاه وی‌پی‌ان")
    text = f"<b>{title}</b>\n\n{welcome}"
    await message.answer(text, reply_markup=main_menu(is_admin(message.from_user.id)), parse_mode="HTML")


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    welcome = await get_setting("welcome_text", "به فروشگاه خوش آمدید 👋")
    await callback.message.edit_text(
        welcome,
        reply_markup=main_menu(is_admin(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    u = await get_user(callback.from_user.id)
    if not u:
        await callback.answer("ابتدا /start بزنید", show_alert=True)
        return
    text = (
        f"👤 <b>پروفایل شما</b>\n\n"
        f"آیدی: <code>{u['tg_id']}</code>\n"
        f"نام: {u.get('full_name') or '—'}\n"
        f"یوزرنیم: @{u.get('username') or '—'}\n"
        f"موجودی: <b>{u.get('balance', 0):,}</b> تومان\n"
        f"کد دعوت: <code>ref{u['tg_id']}</code>"
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "wallet")
async def cb_wallet(callback: CallbackQuery, state: FSMContext):
    u = await get_user(callback.from_user.id)
    if not u:
        await callback.answer("ابتدا /start بزنید", show_alert=True)
        return
    card = await get_setting("card_number", "—")
    card_name = await get_setting("card_name", "—")
    min_dep = await get_setting("min_deposit", "20000")
    try:
        min_dep_fmt = f"{int(min_dep):,}"
    except Exception:
        min_dep_fmt = str(min_dep)
    text = (
        f"💰 <b>کیف پول</b>\n\n"
        f"موجودی فعلی: <b>{u.get('balance', 0):,}</b> تومان\n\n"
        f"برای افزایش موجودی، مبلغ را به کارت زیر واریز کنید و رسید را ارسال کنید:\n\n"
        f"💳 <code>{card}</code>\n"
        f"👤 {card_name}\n\n"
        f"حداقل واریز: {min_dep_fmt} تومان\n\n"
        f"بعد از واریز روی دکمه زیر بزنید."
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 ارسال رسید واریز", callback_data="deposit")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")],
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "deposit")
async def cb_deposit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DepositState.waiting_amount)
    await callback.message.edit_text(
        "مبلغ واریزی را به تومان وارد کنید (فقط عدد):\nمثلاً: 50000",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(DepositState.waiting_amount)
async def deposit_amount(message: Message, state: FSMContext):
    try:
        amount = int(re.sub(r"[^\d]", "", message.text))
    except Exception:
        await message.answer("مبلغ معتبر وارد کنید (فقط عدد).")
        return
    min_dep = int(await get_setting("min_deposit", "20000"))
    if amount < min_dep:
        await message.answer(f"حداقل مبلغ واریز {min_dep:,} تومان است.")
        return
    await state.update_data(amount=amount)
    await state.set_state(DepositState.waiting_receipt)
    await message.answer(
        f"مبلغ {amount:,} تومان ثبت شد.\n\nحالا عکس رسید واریز را ارسال کنید.",
        reply_markup=back_to_menu(),
    )


@router.message(DepositState.waiting_receipt, F.photo)
async def deposit_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount", 0)
    file_id = message.photo[-1].file_id
    rid = await add_receipt(message.from_user.id, amount, file_id)
    await state.clear()

    # اطلاع به ادمین‌ها
    for admin_id in settings.admins:
        try:
            await message.bot.send_photo(
                admin_id,
                photo=file_id,
                caption=(
                    f"🧾 <b>رسید جدید #{rid}</b>\n\n"
                    f"کاربر: {message.from_user.full_name} (@{message.from_user.username or '—'})\n"
                    f"آیدی: <code>{message.from_user.id}</code>\n"
                    f"مبلغ: <b>{amount:,}</b> تومان"
                ),
                parse_mode="HTML",
                reply_markup=receipt_action_kb(rid),
            )
        except Exception:
            pass

    await message.answer(
        "✅ رسید شما ارسال شد و در انتظار تأیید ادمین است.\nبعد از تأیید، موجودی کیف پولتان شارژ می‌شود.",
        reply_markup=main_menu(is_admin(message.from_user.id)),
    )


@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery):
    plans = await get_plans(active_only=True)
    if not plans:
        await callback.message.edit_text(
            "فعلاً پلنی برای فروش وجود ندارد.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return
    text = "🛒 <b>پلن‌های موجود</b>\n\nیکی را انتخاب کنید:"
    await callback.message.edit_text(text, reply_markup=plans_kb(plans), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery):
    plan_id = int(callback.data.split(":")[1])
    plan = await get_plan(plan_id)
    if not plan:
        await callback.answer("پلن پیدا نشد", show_alert=True)
        return
    u = await get_user(callback.from_user.id)
    text = (
        f"📦 <b>{plan['title']}</b>\n\n"
        f"⏱ مدت: {plan['days']} روز\n"
        f"📊 حجم: {plan['volume_gb']} گیگابایت\n"
        f"💰 قیمت: <b>{plan['price']:,}</b> تومان\n\n"
        f"موجودی شما: {u.get('balance', 0):,} تومان\n"
    )
    if u.get("balance", 0) < plan["price"]:
        text += "\n⚠️ موجودی کافی نیست. ابتدا کیف پول را شارژ کنید."
        await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="HTML")
    else:
        text += "\nآیا خرید را تأیید می‌کنید؟"
        await callback.message.edit_text(text, reply_markup=confirm_buy_kb(plan_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def cb_confirm_buy(callback: CallbackQuery):
    plan_id = int(callback.data.split(":")[1])
    plan = await get_plan(plan_id)
    u = await get_user(callback.from_user.id)
    if not plan or not u:
        await callback.answer("خطا", show_alert=True)
        return
    if u.get("balance", 0) < plan["price"]:
        await callback.answer("موجودی کافی نیست", show_alert=True)
        return

    client = await get_client_from_db()
    if not client:
        await callback.message.edit_text(
            "⚠️ پنل هنوز به ربات متصل نشده است. به ادمین اطلاع دهید.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return

    # کم کردن موجودی
    await update_balance(callback.from_user.id, -plan["price"])

    # ساخت نام کاربری یکتا
    uname = f"u{callback.from_user.id}_{secrets.token_hex(2)}"

    from database import get_panel
    p = await get_panel()
    group_ids = []
    try:
        import json
        group_ids = json.loads(p.get("group_ids") or "[]")
    except Exception:
        pass

    user_data, err = await client.create_user(
        username=uname,
        days=plan["days"],
        volume_gb=plan["volume_gb"],
        group_ids=group_ids or None,
        note=f"خرید از ربات - tg:{callback.from_user.id}",
    )

    if err or not user_data:
        await client.close()
        # برگرداندن پول
        await update_balance(callback.from_user.id, plan["price"])
        await callback.message.edit_text(
            f"❌ خطا در ساخت اکانت:\n{err or 'نامشخص'}\n\nمبلغ به کیف پول برگردانده شد.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return

    sub_url = (
        user_data.get("subscription_url")
        or user_data.get("subscriptionUrl")
        or ""
    )
    if not sub_url:
        sub_url = await client.get_subscription_url(uname)
    await client.close()

    order_id = await create_order(callback.from_user.id, plan_id, plan["price"])
    await complete_order(order_id, uname, sub_url)

    text = (
        f"✅ <b>خرید موفق</b>\n\n"
        f"پلن: {plan['title']}\n"
        f"یوزرنیم پنل: <code>{uname}</code>\n\n"
        f"🔗 لینک اشتراک:\n<code>{sub_url}</code>\n\n"
        f"این لینک را در اپلیکیشن خود (v2rayNG / Hiddify / Streisand و ...) وارد کنید."
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer("خرید انجام شد ✅")


@router.callback_query(F.data == "mysubs")
async def cb_mysubs(callback: CallbackQuery):
    from database import DB_PATH
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE user_id=? AND status='paid' ORDER BY id DESC LIMIT 20",
            (callback.from_user.id,),
        )
        rows = await cur.fetchall()
    if not rows:
        await callback.message.edit_text(
            "هنوز اشتراکی نخریده‌اید.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return
    lines = ["📋 <b>اشتراک‌های شما</b>\n"]
    for r in rows:
        lines.append(
            f"• <code>{r['panel_username']}</code>\n"
            f"  لینک: <code>{r['sub_url'] or '—'}</code>\n"
        )
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "trial")
async def cb_trial(callback: CallbackQuery):
    enabled = await get_setting("trial_enabled", "1")
    if enabled != "1":
        await callback.answer("اکانت تست فعلاً غیرفعال است", show_alert=True)
        return
    # ساده: فقط یک‌بار اجازه بده (می‌توان بعداً با جدول جدا کنترل کرد)
    await callback.message.edit_text(
        "🎁 اکانت تست به زودی فعال می‌شود.\nدر نسخه‌های بعدی کامل می‌شود.",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery):
    u = await get_user(callback.from_user.id)
    percent = await get_setting("ref_percent", "20")
    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref{u['tg_id']}"
    text = (
        f"🤝 <b>دعوت دوستان</b>\n\n"
        f"با دعوت هر دوست {percent}٪ از خرید او به شما پاداش داده می‌شود.\n\n"
        f"لینک اختصاصی شما:\n<code>{link}</code>"
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    text = await get_setting("support_text", "برای پشتیبانی پیام دهید.")
    await callback.message.edit_text(text, reply_markup=back_to_menu())
    await callback.answer()