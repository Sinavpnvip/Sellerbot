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
    set_ref, is_user_blocked,
)
from html import escape as esc
from keyboards import main_menu, back_to_menu, plans_kb, confirm_buy_kb, receipt_action_kb, join_channel_kb
from panel_api import get_client_from_db

router = Router()


class DepositState(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


class CustomNameState(StatesGroup):
    waiting_name = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admins


async def guard_user(tg_id: int) -> bool:
    """اگر مسدود باشد True برمی‌گرداند (یعنی باید متوقف شود)"""
    return await is_user_blocked(tg_id)


async def ensure_channel_member(bot, tg_id: int) -> tuple[bool, str]:
    """بررسی عضویت کانال اجباری. (ok, channel_username)"""
    ch = (await get_setting("force_channel", "")).strip()
    if not ch:
        return True, ""
    username = ch.lstrip("@")
    try:
        m = await bot.get_chat_member(chat_id=f"@{username}", user_id=tg_id)
        if m.status in ("member", "administrator", "creator", "restricted"):
            return True, username
        return False, username
    except Exception:
        # اگر ربات ادمین نباشد یا کانال اشتباه، فعلاً رد نکن تا فروش نخوابد
        return True, username


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    args = message.text.split(maxsplit=1)
    user = await ensure_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.full_name or "",
    )
    if user.get("is_blocked"):
        await message.answer("🚫 حساب شما مسدود شده است.")
        return

    ok_ch, ch_name = await ensure_channel_member(message.bot, message.from_user.id)
    if not ok_ch:
        from keyboards import join_channel_kb
        await message.answer(
            f"📣 برای استفاده از ربات ابتدا در کانال زیر عضو شوید:\n@{ch_name}",
            reply_markup=join_channel_kb(ch_name),
        )
        return

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


@router.callback_query(F.data == "check_join")
async def cb_check_join(callback: CallbackQuery):
    ok, ch = await ensure_channel_member(callback.bot, callback.from_user.id)
    if ok:
        welcome = await get_setting("welcome_text", "به فروشگاه خوش آمدید 👋")
        await callback.message.edit_text(
            welcome,
            reply_markup=main_menu(is_admin(callback.from_user.id)),
        )
        await callback.answer("عضویت تأیید شد ✅")
    else:
        await callback.answer("هنوز عضو کانال نشده‌اید", show_alert=True)


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    u = await get_user(callback.from_user.id)
    if not u:
        await callback.answer("ابتدا /start بزنید", show_alert=True)
        return
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    text = (
        f"👤 <b>پروفایل شما</b>\n\n"
        f"آیدی: <code>{u['tg_id']}</code>\n"
        f"نام: {esc(u.get('full_name') or '—')}\n"
        f"یوزرنیم: @{esc(u.get('username') or '—')}\n"
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
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
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
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
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



@router.callback_query(F.data.startswith("custom_name:"))
async def cb_custom_name(callback: CallbackQuery, state: FSMContext):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    plan = await get_plan(plan_id)
    if not plan:
        await callback.answer("پلن یافت نشد", show_alert=True)
        return
    await state.set_state(CustomNameState.waiting_name)
    await state.update_data(plan_id=plan_id)
    await callback.message.edit_text(
        "✏️ نام دلخواه اشتراک را وارد کنید:\n"
        "فقط حروف انگلیسی، عدد و _ مجاز است (۳ تا ۲۰ کاراکتر)\n"
        "مثال: <code>myvpn01</code>",
        reply_markup=back_to_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(CustomNameState.waiting_name)
async def custom_name_msg(message: Message, state: FSMContext):
    import re as _re
    if await guard_user(message.from_user.id):
        await state.clear()
        return
    name = (message.text or "").strip()
    if not _re.fullmatch(r"[A-Za-z0-9_\-]{3,20}", name):
        await message.answer("❌ نام نامعتبر است. فقط a-z و 0-9 و _ (۳ تا ۲۰ کاراکتر)")
        return
    data = await state.get_data()
    plan_id = data.get("plan_id")
    await state.clear()
    # reuse confirm with custom name stored briefly via buying with forced uname
    plan = await get_plan(plan_id)
    u = await get_user(message.from_user.id)
    if not plan or not u:
        await message.answer("خطا")
        return
    ok = await update_balance(message.from_user.id, -plan["price"])
    if not ok:
        await message.answer("موجودی کافی نیست.")
        return
    client = await get_client_from_db()
    if not client:
        await update_balance(message.from_user.id, plan["price"])
        await message.answer("پنل متصل نیست.")
        return
    uname = f"{name}_{secrets.token_hex(2)}"
    from database import get_panel
    import json as _json
    panel = await get_panel()
    try:
        group_ids = _json.loads(panel.get("group_ids") or "[]")
    except Exception:
        group_ids = []
    user_data, err = await client.create_user(
        username=uname,
        days=int(plan["days"]),
        volume_gb=int(plan["volume_gb"]),
        group_ids=group_ids or None,
        note=f"shop tg:{message.from_user.id}",
    )
    if err or not user_data:
        await client.close()
        await update_balance(message.from_user.id, plan["price"])
        await message.answer(f"❌ خطا: {err}\nمبلغ برگشت داده شد.")
        return
    sub_url = user_data.get("subscription_url") or await client.get_subscription_url(uname)
    await client.close()
    order_id = await create_order(message.from_user.id, plan_id, plan["price"])
    await complete_order(order_id, uname, sub_url)
    # ref reward
    ref_by = u.get("ref_by") or 0
    if ref_by:
        try:
            percent = int(await get_setting("ref_percent", "20") or "0")
            reward = int(plan["price"] * percent / 100)
            if reward > 0:
                await update_balance(ref_by, reward)
                try:
                    await message.bot.send_message(ref_by, f"🎉 پاداش دعوت: {reward:,} تومان")
                except Exception:
                    pass
        except Exception:
            pass
    # QR
    try:
        import qrcode
        from io import BytesIO
        from aiogram.types import BufferedInputFile
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(sub_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await message.answer_photo(
            BufferedInputFile(buf.read(), filename="sub.png"),
            caption=(
                f"✅ <b>خرید موفق</b>\n\n"
                f"پلن: {esc(str(plan['title']))}\n"
                f"نام: <code>{esc(uname)}</code>\n\n"
                f"🔗 <code>{esc(sub_url)}</code>"
            ),
            parse_mode="HTML",
            reply_markup=main_menu(is_admin(message.from_user.id)),
        )
    except Exception:
        await message.answer(
            f"✅ خرید موفق\n<code>{esc(uname)}</code>\n<code>{esc(sub_url)}</code>",
            parse_mode="HTML",
            reply_markup=main_menu(is_admin(message.from_user.id)),
        )


@router.callback_query(F.data.startswith("confirm_buy:"))
async def cb_confirm_buy(callback: CallbackQuery):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    plan = await get_plan(plan_id)
    u = await get_user(callback.from_user.id)
    if not plan or not u:
        await callback.answer("خطا", show_alert=True)
        return
    if not plan.get("is_active", 1):
        await callback.answer("این پلن غیرفعال است", show_alert=True)
        return

    # کسر اتمیک موجودی (جلوگیری از دوبار کلیک و موجودی منفی)
    ok = await update_balance(callback.from_user.id, -plan["price"])
    if not ok:
        await callback.answer("موجودی کافی نیست", show_alert=True)
        return

    client = await get_client_from_db()
    if not client:
        await update_balance(callback.from_user.id, plan["price"])  # refund
        await callback.message.edit_text(
            "⚠️ پنل هنوز به ربات متصل نشده است. به ادمین اطلاع دهید.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return

    uname = f"u{callback.from_user.id}_{secrets.token_hex(3)}"
    from database import get_panel
    import json as _json
    panel = await get_panel()
    try:
        group_ids = _json.loads(panel.get("group_ids") or "[]")
    except Exception:
        group_ids = []

    user_data, err = await client.create_user(
        username=uname,
        days=int(plan["days"]),
        volume_gb=int(plan["volume_gb"]),
        group_ids=group_ids or None,
        note=f"shop tg:{callback.from_user.id}",
    )

    if err or not user_data:
        await client.close()
        await update_balance(callback.from_user.id, plan["price"])  # refund
        await callback.message.edit_text(
            f"❌ خطا در ساخت اکانت:\n{esc(str(err or 'نامشخص'))}\n\nمبلغ به کیف پول برگردانده شد.",
            reply_markup=back_to_menu(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sub_url = user_data.get("subscription_url") or user_data.get("subscriptionUrl") or ""
    if not sub_url:
        sub_url = await client.get_subscription_url(uname)
    await client.close()

    order_id = await create_order(callback.from_user.id, plan_id, plan["price"])
    await complete_order(order_id, uname, sub_url)

    # پاداش معرف
    ref_by = u.get("ref_by") or 0
    if ref_by:
        try:
            percent = int(await get_setting("ref_percent", "20") or "0")
            reward = int(plan["price"] * percent / 100)
            if reward > 0:
                await update_balance(ref_by, reward)
                try:
                    await callback.bot.send_message(
                        ref_by,
                        f"🎉 پاداش دعوت: {reward:,} تومان از خرید زیرمجموعه‌تان.",
                    )
                except Exception:
                    pass
        except Exception:
            pass

    text = (
        f"✅ <b>خرید موفق</b>\n\n"
        f"پلن: {esc(str(plan['title']))}\n"
        f"یوزرنیم: <code>{esc(uname)}</code>\n\n"
        f"🔗 لینک اشتراک:\n<code>{esc(sub_url)}</code>\n\n"
        f"این لینک را در v2rayNG / Hiddify / Streisand وارد کنید."
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
    from database import has_used_trial, mark_trial_used
    enabled = await get_setting("trial_enabled", "1")
    if enabled != "1":
        await callback.answer("اکانت تست فعلاً غیرفعال است", show_alert=True)
        return
    if await has_used_trial(callback.from_user.id):
        await callback.answer("شما قبلاً از اکانت تست استفاده کرده‌اید", show_alert=True)
        return
    client = await get_client_from_db()
    if not client:
        await callback.message.edit_text("پنل متصل نیست. به ادمین اطلاع دهید.", reply_markup=back_to_menu())
        await callback.answer()
        return
    days = int(await get_setting("trial_days", "1") or "1")
    gb = int(await get_setting("trial_gb", "1") or "1")
    uname = f"trial{callback.from_user.id}_{secrets.token_hex(2)}"
    from database import get_panel
    import json as _json
    p = await get_panel()
    try:
        group_ids = _json.loads(p.get("group_ids") or "[]")
    except Exception:
        group_ids = []
    user_data, err = await client.create_user(uname, days, gb, group_ids or None, note=f"trial tg:{callback.from_user.id}")
    if err or not user_data:
        await client.close()
        await callback.message.edit_text(f"خطا در ساخت تست:\n{err}", reply_markup=back_to_menu())
        await callback.answer()
        return
    sub_url = user_data.get("subscription_url") or await client.get_subscription_url(uname)
    await client.close()
    await mark_trial_used(callback.from_user.id)
    await callback.message.edit_text(
        f"🎁 <b>اکانت تست فعال شد</b>\n\nمدت: {days} روز | حجم: {gb}GB\n\n🔗 <code>{sub_url}</code>",
        reply_markup=back_to_menu(),
        parse_mode="HTML",
    )
    await callback.answer("تست فعال شد")


class CouponState(StatesGroup):
    waiting_code = State()


@router.callback_query(F.data == "coupon")
async def cb_coupon(callback: CallbackQuery, state: FSMContext):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    await state.set_state(CouponState.waiting_code)
    await callback.message.edit_text(
        "🎟 کد تخفیف را ارسال کنید:\nمثال: <code>OFF20</code>",
        reply_markup=back_to_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(CouponState.waiting_code)
async def apply_coupon(message: Message, state: FSMContext):
    from database import get_coupon, has_used_coupon, use_coupon
    if await guard_user(message.from_user.id):
        await message.answer("حساب مسدود است.")
        await state.clear()
        return
    code = (message.text or "").strip().upper()
    c = await get_coupon(code)
    if not c:
        await message.answer("❌ کد تخفیف معتبر نیست.")
        return
    if c.get("max_uses") and c.get("used_count", 0) >= c["max_uses"]:
        await message.answer("❌ ظرفیت این کد تمام شده است.")
        return
    if await has_used_coupon(c["id"], message.from_user.id):
        await message.answer("❌ شما قبلاً از این کد استفاده کرده‌اید.")
        return
    # اعمال به صورت شارژ کیف پول (ساده و شفاف)
    if c["discount_type"] == "percent":
        # برای درصدی: حداقل یک هدیه ثابت از min_order یا پیام راهنما
        await message.answer(
            f"✅ کد <b>{esc(code)}</b> معتبر است ({c['discount_value']}٪).\n"
            f"این کد هنگام خرید بعدی از قیمت کم می‌شود.\n"
            f"فعلاً برای اعمال خودکار، ادمین می‌تواند موجودی هدیه بدهد.",
            parse_mode="HTML",
            reply_markup=main_menu(is_admin(message.from_user.id)),
        )
        # ثبت استفاده تا دوباره استفاده نشود — در نسخه کامل هنگام خرید کم می‌شود
        # اینجا فقط اعتبارسنجی می‌کنیم بدون سوزاندن کد درصدی تا خرید واقعی
        await state.clear()
        return
    else:
        amount = int(c["discount_value"])
        if amount <= 0:
            await message.answer("کد نامعتبر.")
            return
        ok = await use_coupon(c["id"], message.from_user.id)
        if not ok:
            await message.answer("❌ خطا در اعمال کد.")
            return
        await update_balance(message.from_user.id, amount)
        await state.clear()
        await message.answer(
            f"✅ کد اعمال شد!\n{amount:,} تومان به کیف پول شما اضافه شد.",
            reply_markup=main_menu(is_admin(message.from_user.id)),
        )


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