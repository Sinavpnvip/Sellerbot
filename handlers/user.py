from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import re
import secrets
from html import escape as esc

from config import settings
from database import (
    ensure_user, get_user, get_setting, get_plans, get_plan,
    update_balance, create_order, complete_order, add_receipt,
    set_ref, is_user_blocked, get_coupon, has_used_coupon, use_coupon,
    create_ticket, get_user_orders,
)
from keyboards import (
    main_menu, back_to_menu, plans_kb, plan_offer_kb, final_buy_kb,
    low_balance_kb, wallet_kb, receipt_action_kb, join_channel_kb,
)
from panel_api import get_client_from_db
from locks import acquire_user, release_user

router = Router()


class DepositState(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


class CustomNameState(StatesGroup):
    waiting_name = State()


class CouponBuyState(StatesGroup):
    waiting_code = State()


class SupportState(StatesGroup):
    waiting_message = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admins


async def guard_user(tg_id: int) -> bool:
    return await is_user_blocked(tg_id)


async def safe_edit(callback: CallbackQuery, text: str, reply_markup=None, parse_mode="HTML"):
    """جلوگیری از خرابی دکمه وقتی edit ناموفق باشد"""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass
    try:
        await callback.answer()
    except Exception:
        pass


async def ensure_channel_member(bot, tg_id: int) -> tuple[bool, str]:
    """True = اجازه ورود. ادمین‌ها همیشه رد می‌شوند از چک."""
    if tg_id in settings.admins:
        return True, ""
    ch = (await get_setting("force_channel", "")).strip()
    if not ch or ch.lower() in ("off", "0", "none"):
        return True, ""
    username = ch.lstrip("@").strip()
    chat_ref = f"@{username}"
    # اگر آیدی عددی کانال ذخیره شده باشد
    ch_id = (await get_setting("force_channel_id", "0")).strip()
    targets = []
    if ch_id and ch_id not in ("0", ""):
        try:
            targets.append(int(ch_id))
        except Exception:
            targets.append(ch_id)
    targets.append(chat_ref)
    last_err = None
    for target in targets:
        try:
            m = await bot.get_chat_member(chat_id=target, user_id=tg_id)
            status = getattr(m, "status", None)
            # در aiogram 3 ممکن است Enum باشد
            st = str(status).lower().split(".")[-1] if status is not None else ""
            if st in ("member", "administrator", "creator", "restricted"):
                return True, username
            # left / kicked / not_member
            return False, username
        except Exception as e:
            last_err = e
            continue
    # اگر ربات نتواند چک کند (ادمین نیست / کانال اشتباه) برای جلوگیری از قفل کامل فروش:
    # فقط وقتی کانال ست شده و خطا داریم، کاربر را راه بده ولی لاگ کن
    import logging
    logging.getLogger(__name__).warning("channel check failed for %s: %s", tg_id, last_err)
    return True, username


async def require_channel(callback_or_message, bot, tg_id: int) -> bool:
    """اگر عضو نباشد پیام عضویت می‌دهد و False برمی‌گرداند."""
    ok, ch = await ensure_channel_member(bot, tg_id)
    if ok:
        return True
    text = (
        f"📣 برای استفاده از ربات باید عضو کانال باشید.\n\n"
        f"اگر لفت داده‌اید، دوباره عضو شوید و دکمه زیر را بزنید.\n"
        f"کانال: @{ch}"
    )
    kb = join_channel_kb(ch)
    try:
        if hasattr(callback_or_message, "message"):
            # CallbackQuery
            try:
                await callback_or_message.message.edit_text(text, reply_markup=kb)
            except Exception:
                await callback_or_message.message.answer(text, reply_markup=kb)
            try:
                await callback_or_message.answer("ابتدا عضو کانال شوید", show_alert=True)
            except Exception:
                pass
        else:
            await callback_or_message.answer(text, reply_markup=kb)
    except Exception:
        pass
    return False


def calc_price(plan: dict, coupon: dict | None) -> tuple[int, int]:
    """return (final_price, discount_amount)"""
    price = int(plan["price"])
    if not coupon:
        return price, 0
    if coupon["discount_type"] == "percent":
        d = int(price * int(coupon["discount_value"]) / 100)
    else:
        d = int(coupon["discount_value"])
    d = min(d, price)
    return max(price - d, 0), d


# ---------- Start / Menu ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
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
        await message.answer(
            f"📣 برای استفاده از ربات ابتدا عضو کانال شوید:\n@{ch_name}",
            reply_markup=join_channel_kb(ch_name),
        )
        return

    args = message.text.split(maxsplit=1)
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
    title = await get_setting("shop_title", "SF VPN")
    text = f"<b>{esc(title)}</b>\n\n{welcome}"
    await message.answer(text, reply_markup=main_menu(is_admin(message.from_user.id)), parse_mode="HTML")


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not await require_channel(callback, callback.bot, callback.from_user.id):
        return
    welcome = await get_setting("welcome_text", "به فروشگاه خوش آمدید 👋")
    await safe_edit(callback, welcome, main_menu(is_admin(callback.from_user.id)))


@router.callback_query(F.data == "check_join")
async def cb_check_join(callback: CallbackQuery):
    ok, ch = await ensure_channel_member(callback.bot, callback.from_user.id)
    if ok:
        welcome = await get_setting("welcome_text", "به فروشگاه خوش آمدید 👋")
        await safe_edit(callback, welcome, main_menu(is_admin(callback.from_user.id)))
        try:
            await callback.answer("عضویت تأیید شد ✅")
        except Exception:
            pass
    else:
        await callback.answer("هنوز عضو کانال نشده‌اید", show_alert=True)


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    u = await get_user(callback.from_user.id)
    if not u:
        await callback.answer("ابتدا /start بزنید", show_alert=True)
        return
    text = (
        f"╭─ 👤 <b>پروفایل</b>\n"
        f"│ آیدی: <code>{u['tg_id']}</code>\n"
        f"│ نام: {esc(u.get('full_name') or '—')}\n"
        f"│ یوزرنیم: @{esc(u.get('username') or '—')}\n"
        f"│ موجودی: <b>{u.get('balance', 0):,}</b> تومان\n"
        f"╰─ کد دعوت: <code>ref{u['tg_id']}</code>"
    )
    await safe_edit(callback, text, back_to_menu())


# ---------- Wallet ----------
@router.callback_query(F.data == "wallet")
async def cb_wallet(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    if not await require_channel(callback, callback.bot, callback.from_user.id):
        return
    u = await get_user(callback.from_user.id)
    if not u:
        await callback.answer("ابتدا /start بزنید", show_alert=True)
        return
    text = (
        f"╭─ 💎 <b>کیف پول</b>\n"
        f"│\n"
        f"│ موجودی شما:\n"
        f"│ <b>{u.get('balance', 0):,}</b> تومان\n"
        f"│\n"
        f"╰─ برای شارژ روی دکمه زیر بزنید"
    )
    await safe_edit(callback, text, wallet_kb())


@router.callback_query(F.data == "topup")
async def cb_topup(callback: CallbackQuery, state: FSMContext):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    min_dep = await get_setting("min_deposit", "20000")
    try:
        min_fmt = f"{int(min_dep):,}"
    except Exception:
        min_fmt = str(min_dep)
    await state.set_state(DepositState.waiting_amount)
    text = (
        f"💳 <b>افزایش موجودی — کارت به کارت</b>\n\n"
        f"مبلغ واریزی را به تومان وارد کنید.\n"
        f"حداقل: <b>{min_fmt}</b> تومان\n\n"
        f"مثال: <code>50000</code>"
    )
    await safe_edit(callback, text, back_to_menu())


@router.message(DepositState.waiting_amount)
async def deposit_amount(message: Message, state: FSMContext):
    if await guard_user(message.from_user.id):
        await state.clear()
        return
    try:
        amount = int(re.sub(r"[^\d]", "", message.text or ""))
    except Exception:
        await message.answer("فقط عدد وارد کنید. مثال: 50000")
        return
    min_dep = int(await get_setting("min_deposit", "20000") or "20000")
    if amount < min_dep:
        await message.answer(f"حداقل مبلغ {min_dep:,} تومان است.")
        return
    card = await get_setting("card_number", "—")
    card_name = await get_setting("card_name", "—")
    await state.update_data(amount=amount)
    await state.set_state(DepositState.waiting_receipt)
    text = (
        f"✅ مبلغ ثبت شد: <b>{amount:,}</b> تومان\n\n"
        f"به کارت زیر واریز کنید:\n\n"
        f"💳 <code>{esc(card)}</code>\n"
        f"👤 {esc(card_name)}\n\n"
        f"مبلغ دقیق: <b>{amount:,}</b> تومان\n\n"
        f"بعد از واریز، <b>عکس رسید</b> را همینجا ارسال کنید."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=back_to_menu())


@router.message(DepositState.waiting_receipt, F.photo)
async def deposit_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = int(data.get("amount", 0))
    if amount <= 0:
        await state.clear()
        await message.answer("مبلغ نامعتبر. دوباره از کیف پول شروع کنید.", reply_markup=main_menu(is_admin(message.from_user.id)))
        return
    file_id = message.photo[-1].file_id
    rid = await add_receipt(message.from_user.id, amount, file_id)
    await state.clear()
    for admin_id in settings.admins:
        try:
            await message.bot.send_photo(
                admin_id,
                photo=file_id,
                caption=(
                    f"🧾 <b>رسید جدید #{rid}</b>\n\n"
                    f"کاربر: {esc(message.from_user.full_name or '')} "
                    f"(@{esc(message.from_user.username or '—')})\n"
                    f"آیدی: <code>{message.from_user.id}</code>\n"
                    f"مبلغ: <b>{amount:,}</b> تومان"
                ),
                parse_mode="HTML",
                reply_markup=receipt_action_kb(rid),
            )
        except Exception:
            pass
    await message.answer(
        "✅ رسید ارسال شد و در انتظار تأیید ادمین است.\nبعد از تأیید، موجودی شارژ می‌شود.",
        reply_markup=main_menu(is_admin(message.from_user.id)),
    )


# ---------- Shop + Coupon in flow ----------
@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    if not await require_channel(callback, callback.bot, callback.from_user.id):
        return
    plans = await get_plans(active_only=True)
    if not plans:
        await safe_edit(callback, "فعلاً پلنی برای فروش نیست.", back_to_menu())
        return
    await safe_edit(callback, "🛒 <b>پلن‌های موجود</b>\nیکی را انتخاب کنید:", plans_kb(plans))


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery, state: FSMContext):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    plan = await get_plan(plan_id)
    if not plan or not plan.get("is_active", 1):
        await callback.answer("پلن موجود نیست", show_alert=True)
        return
    await state.update_data(plan_id=plan_id, coupon_code=None, coupon_discount=0)
    text = (
        f"╭─ 📦 <b>{esc(str(plan['title']))}</b>\n"
        f"│ ⏱ {plan['days']} روز\n"
        f"│ 📊 {plan['volume_gb']} گیگابایت\n"
        f"│ 💰 قیمت: <b>{plan['price']:,}</b> تومان\n"
        f"╰─\n\n"
        f"اگر کد تخفیف دارید اول وارد کنید، وگرنه ادامه خرید را بزنید."
    )
    await safe_edit(callback, text, plan_offer_kb(plan_id, has_coupon=False))


@router.callback_query(F.data.startswith("ask_coupon:"))
async def cb_ask_coupon(callback: CallbackQuery, state: FSMContext):
    plan_id = int(callback.data.split(":")[1])
    await state.set_state(CouponBuyState.waiting_code)
    await state.update_data(plan_id=plan_id)
    await safe_edit(
        callback,
        "🎟 کد تخفیف را ارسال کنید:\nمثال: <code>OFF20</code>",
        back_to_menu(),
    )


@router.message(CouponBuyState.waiting_code)
async def coupon_buy_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    c = await get_coupon(code)
    data = await state.get_data()
    plan_id = data.get("plan_id")
    plan = await get_plan(plan_id) if plan_id else None
    if not plan:
        await state.clear()
        await message.answer("پلن یافت نشد. دوباره از فروشگاه شروع کنید.", reply_markup=main_menu(is_admin(message.from_user.id)))
        return
    if not c:
        await message.answer("❌ کد معتبر نیست. دوباره بفرستید یا از منو انصراف دهید.")
        return
    if c.get("max_uses") and c.get("used_count", 0) >= c["max_uses"]:
        await message.answer("❌ ظرفیت این کد تمام شده.")
        return
    if await has_used_coupon(c["id"], message.from_user.id):
        await message.answer("❌ قبلاً از این کد استفاده کرده‌اید.")
        return
    final, disc = calc_price(plan, c)
    await state.update_data(coupon_code=code, coupon_id=c["id"], coupon_discount=disc, final_price=final)
    await state.set_state(None)
    text = (
        f"✅ کد <b>{esc(code)}</b> اعمال شد\n"
        f"تخفیف: <b>{disc:,}</b> تومان\n"
        f"قیمت نهایی: <b>{final:,}</b> تومان\n\n"
        f"📦 {esc(str(plan['title']))}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=final_buy_kb(plan_id))


@router.callback_query(F.data.startswith("go_buy:"))
async def cb_go_buy(callback: CallbackQuery, state: FSMContext):
    plan_id = int(callback.data.split(":")[1])
    plan = await get_plan(plan_id)
    if not plan:
        await callback.answer("پلن نیست", show_alert=True)
        return
    data = await state.get_data()
    final = int(data.get("final_price") or plan["price"])
    disc = int(data.get("coupon_discount") or 0)
    text = (
        f"📦 <b>{esc(str(plan['title']))}</b>\n"
        f"قیمت: <b>{plan['price']:,}</b> تومان\n"
    )
    if disc:
        text += f"تخفیف: <b>{disc:,}</b>\nقیمت نهایی: <b>{final:,}</b>\n"
    text += "\nبرای خرید تأیید کنید:"
    await state.update_data(plan_id=plan_id, final_price=final)
    await safe_edit(callback, text, final_buy_kb(plan_id))


@router.callback_query(F.data.startswith("confirm_buy:"))
async def cb_confirm_buy(callback: CallbackQuery, state: FSMContext):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    uid = callback.from_user.id
    if not await acquire_user(uid):
        await callback.answer("⏳ درخواست قبلی در حال انجام است…", show_alert=True)
        return
    try:
        plan_id = int(callback.data.split(":")[1])
        plan = await get_plan(plan_id)
        u = await get_user(uid)
        if not plan or not u or not plan.get("is_active", 1):
            await callback.answer("خطا", show_alert=True)
            return

        data = await state.get_data()
        price = int(plan["price"])
        coupon_id = None
        code = data.get("coupon_code")
        if code and data.get("plan_id") == plan_id:
            c = await get_coupon(code)
            if c and not await has_used_coupon(c["id"], uid):
                if not (c.get("max_uses") and c.get("used_count", 0) >= c["max_uses"]):
                    price, _ = calc_price(plan, c)
                    coupon_id = c["id"]
        price = max(int(price), 0)

        if int(u.get("balance", 0) or 0) < price:
            await safe_edit(
                callback,
                f"⚠️ موجودی کافی نیست.\nنیاز: <b>{price:,}</b>\nموجودی: <b>{u.get('balance', 0):,}</b>",
                low_balance_kb(),
            )
            return

        ok = await update_balance(uid, -price)
        if not ok:
            await safe_edit(callback, "⚠️ موجودی کافی نیست.", low_balance_kb())
            return

        try:
            await callback.answer("در حال ساخت…")
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        if coupon_id:
            try:
                await use_coupon(int(coupon_id), uid)
            except Exception:
                pass

        client = await get_client_from_db()
        if not client:
            await update_balance(uid, price)
            await safe_edit(callback, "⚠️ پنل متصل نیست. به ادمین بگویید.", back_to_menu())
            return

        uname = f"u{uid}_{secrets.token_hex(3)}"
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
            note=f"shop tg:{uid}",
        )
        if err or not user_data:
            await client.close()
            await update_balance(uid, price)
            await safe_edit(
                callback,
                f"❌ خطا در ساخت اکانت:\n{esc(str(err or 'نامشخص'))}\nمبلغ برگشت داده شد.",
                back_to_menu(),
            )
            return

        sub_url = user_data.get("subscription_url") or user_data.get("subscriptionUrl") or ""
        if not sub_url:
            sub_url = await client.get_subscription_url(uname)
        await client.close()

        order_id = await create_order(uid, plan_id, price)
        await complete_order(order_id, uname, sub_url)
        await state.clear()

        ref_by = u.get("ref_by") or 0
        if ref_by and price > 0:
            try:
                percent = int(await get_setting("ref_percent", "20") or "0")
                percent = max(0, min(percent, 100))
                reward = int(price * percent / 100)
                if reward > 0:
                    await update_balance(int(ref_by), reward)
                    try:
                        await callback.bot.send_message(int(ref_by), f"🎉 پاداش دعوت: {reward:,} تومان")
                    except Exception:
                        pass
            except Exception:
                pass

        text = (
            f"✅ <b>خرید موفق</b>\n\n"
            f"پلن: {esc(str(plan['title']))}\n"
            f"یوزرنیم: <code>{esc(uname)}</code>\n\n"
            f"🔗 لینک اشتراک:\n<code>{esc(sub_url)}</code>\n\n"
            f"در v2rayNG / Hiddify / Streisand وارد کنید."
        )
        await safe_edit(callback, text, back_to_menu())
    finally:
        await release_user(uid)


# ---------- Custom name (kept) ----------
@router.callback_query(F.data.startswith("custom_name:"))
async def cb_custom_name(callback: CallbackQuery, state: FSMContext):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    await state.set_state(CustomNameState.waiting_name)
    await state.update_data(plan_id=plan_id)
    await safe_edit(
        callback,
        "✏️ نام دلخواه (انگلیسی، ۳ تا ۲۰ کاراکتر):\nمثال: <code>myvpn01</code>",
        back_to_menu(),
    )


@router.message(CustomNameState.waiting_name)
async def custom_name_msg(message: Message, state: FSMContext):
    if await guard_user(message.from_user.id):
        await state.clear()
        return
    uid = message.from_user.id
    if not await acquire_user(uid):
        await message.answer("⏳ درخواست قبلی در حال انجام است…")
        return
    try:
        name = (message.text or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]{3,20}", name):
            await message.answer("❌ نام نامعتبر. فقط a-z و 0-9 و _")
            return
        data = await state.get_data()
        plan_id = data.get("plan_id")
        plan = await get_plan(plan_id)
        u = await get_user(uid)
        await state.clear()
        if not plan or not u or not plan.get("is_active", 1):
            await message.answer("خطا", reply_markup=main_menu(is_admin(uid)))
            return
        price = max(int(plan["price"]), 0)
        ok = await update_balance(uid, -price)
        if not ok:
            await message.answer("موجودی کافی نیست.", reply_markup=low_balance_kb())
            return
        client = await get_client_from_db()
        if not client:
            await update_balance(uid, price)
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
            uname, int(plan["days"]), int(plan["volume_gb"]), group_ids or None, f"shop tg:{uid}"
        )
        if err or not user_data:
            await client.close()
            await update_balance(uid, price)
            await message.answer(f"❌ {err}\nمبلغ برگشت داده شد.")
            return
        sub_url = user_data.get("subscription_url") or await client.get_subscription_url(uname)
        await client.close()
        oid = await create_order(uid, plan_id, price)
        await complete_order(oid, uname, sub_url)
        await message.answer(
            f"✅ خرید موفق\n<code>{esc(uname)}</code>\n<code>{esc(sub_url)}</code>",
            parse_mode="HTML",
            reply_markup=main_menu(is_admin(uid)),
        )
    finally:
        await release_user(uid)


# ---------- My services ----------

@router.callback_query(F.data.startswith("copy_sub:"))
async def cb_copy_sub(callback: CallbackQuery):
    oid = int(callback.data.split(":")[1])
    rows = await get_user_orders(callback.from_user.id, 50)
    order = next((r for r in rows if r["id"] == oid), None)
    if not order:
        await callback.answer("پیدا نشد", show_alert=True)
        return
    sub = order.get("sub_url") or ""
    await callback.answer("لینک در پیام بالا قابل کپی است", show_alert=True)
    if sub:
        try:
            await callback.message.answer(f"<code>{esc(sub)}</code>", parse_mode="HTML")
        except Exception:
            pass


# ---------- Trial ----------
@router.callback_query(F.data == "trial")
async def cb_trial(callback: CallbackQuery):
    from database import claim_trial
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    if not await require_channel(callback, callback.bot, callback.from_user.id):
        return
    if (await get_setting("trial_enabled", "1")) != "1":
        await callback.answer("تست فعلاً غیرفعال است", show_alert=True)
        return
    uid = callback.from_user.id
    if not await acquire_user(uid):
        await callback.answer("⏳ صبر کنید…", show_alert=True)
        return
    try:
        if not await claim_trial(uid):
            await callback.answer("قبلاً تست گرفته‌اید", show_alert=True)
            return
        client = await get_client_from_db()
        if not client:
            # برگرداندن حق تست اگر پنل نیست سخت است؛ claim شده. فقط پیام بده
            await safe_edit(callback, "پنل متصل نیست. با پشتیبانی در تماس باشید.", back_to_menu())
            return
        days = max(int(await get_setting("trial_days", "1") or "1"), 1)
        gb = max(int(await get_setting("trial_gb", "1") or "1"), 1)
        uname = f"t{uid}_{secrets.token_hex(2)}"
        from database import get_panel
        import json as _json
        panel = await get_panel()
        try:
            group_ids = _json.loads(panel.get("group_ids") or "[]")
        except Exception:
            group_ids = []
        user_data, err = await client.create_user(uname, days, gb, group_ids or None, f"trial tg:{uid}")
        if err or not user_data:
            await client.close()
            await safe_edit(callback, f"خطا: {esc(str(err))}", back_to_menu())
            return
        sub_url = user_data.get("subscription_url") or await client.get_subscription_url(uname)
        await client.close()
        await safe_edit(
            callback,
            f"🎁 <b>تست فعال شد</b>\n{days} روز / {gb}GB\n\n🔗 <code>{esc(sub_url)}</code>",
            back_to_menu(),
        )
    finally:
        await release_user(uid)


# ---------- Referral ----------
@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery):
    u = await get_user(callback.from_user.id)
    if not u:
        await callback.answer("ابتدا /start", show_alert=True)
        return
    percent = await get_setting("ref_percent", "20")
    bot_info = await callback.bot.get_me()
    # short link style
    link = f"https://t.me/{bot_info.username}?start=ref{u['tg_id']}"
    text = (
        f"╭─ 🤝 <b>دعوت دوستان</b>\n"
        f"│\n"
        f"│ با هر خرید دوستت، <b>{esc(percent)}%</b>\n"
        f"│ به کیف پولت واریز می‌شود.\n"
        f"│\n"
        f"│ لینک شما:\n"
        f"│ <code>{link}</code>\n"
        f"╰─ برای دوستات بفرست"
    )
    await safe_edit(callback, text, back_to_menu())


# ---------- Real Support ----------
@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery, state: FSMContext):
    if await guard_user(callback.from_user.id):
        await callback.answer("حساب مسدود است", show_alert=True)
        return
    if not await require_channel(callback, callback.bot, callback.from_user.id):
        return
    await state.set_state(SupportState.waiting_message)
    text = (
        "💬 <b>پشتیبانی</b>\n\n"
        "پیام خود را بنویسید و ارسال کنید.\n"
        "پیام شما برای پشتیبانی ثبت می‌شود و پاسخ داده می‌شود."
    )
    await safe_edit(callback, text, back_to_menu())


@router.message(SupportState.waiting_message)
async def support_message(message: Message, state: FSMContext):
    if await guard_user(message.from_user.id):
        await state.clear()
        return
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("متن پیام را بنویسید.")
        return
    if len(text) < 3:
        await message.answer("پیام خیلی کوتاه است.")
        return
    tid = await create_ticket(message.from_user.id, text)
    await state.clear()
    for admin_id in settings.admins:
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ پاسخ", callback_data=f"adm:ticket:{tid}")],
            ])
            await message.bot.send_message(
                admin_id,
                f"💬 <b>تیکت جدید #{tid}</b>\n"
                f"از: {esc(message.from_user.full_name or '')} "
                f"(@{esc(message.from_user.username or '—')})\n"
                f"آیدی: <code>{message.from_user.id}</code>\n\n"
                f"{esc(text)}",
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            pass
    await message.answer(
        f"✅ پیام شما ثبت شد (شماره #{tid}).\nبه زودی پاسخ داده می‌شود.",
        reply_markup=main_menu(is_admin(message.from_user.id)),
    )
