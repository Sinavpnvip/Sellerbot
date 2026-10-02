from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import json

from config import settings
from database import (
    get_setting, set_setting, get_plans, add_plan, delete_plan, get_plan,
    get_panel, save_panel, get_pending_receipts, get_receipt, set_receipt_status,
    update_balance, get_user
)
from keyboards import admin_menu, back_to_menu, plans_admin_kb, receipts_kb, receipt_action_kb
from panel_api import PanelClient

router = Router()


class AdminStates(StatesGroup):
    panel_url = State()
    panel_user = State()
    panel_pass = State()
    add_plan_title = State()
    add_plan_days = State()
    add_plan_gb = State()
    add_plan_price = State()
    set_card = State()
    set_card_name = State()
    set_min_deposit = State()
    set_welcome = State()
    set_support = State()


def admin_only(func):
    async def wrapper(event, *args, **kwargs):
        uid = event.from_user.id
        if uid not in settings.admins:
            if hasattr(event, "answer"):
                await event.answer("دسترسی ندارید", show_alert=True)
            return
        return await func(event, *args, **kwargs)
    return wrapper


@router.callback_query(F.data == "admin")
async def cb_admin(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admins:
        await callback.answer("دسترسی ندارید", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "⚙️ <b>پنل مدیریت</b>\n\nیکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=admin_menu(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------- اتصال پنل ----------
@router.callback_query(F.data == "adm:panel")
async def adm_panel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admins:
        return
    p = await get_panel()
    status = "✅ متصل" if p.get("is_connected") else "❌ متصل نیست"
    text = (
        f"🔗 <b>اتصال به پنل JinX / PasarGuard</b>\n\n"
        f"وضعیت: {status}\n"
        f"آدرس فعلی: <code>{p.get('base_url') or '—'}</code>\n"
        f"یوزرنیم: <code>{p.get('username') or '—'}</code>\n\n"
        f"برای تنظیم مجدد، آدرس پنل را ارسال کنید:\n"
        f"مثال: https://xxxx.up.railway.app"
    )
    await state.set_state(AdminStates.panel_url)
    await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.panel_url)
async def panel_url(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    url = message.text.strip().rstrip("/")
    if not url.startswith("http"):
        await message.answer("آدرس باید با http یا https شروع شود.")
        return
    await state.update_data(panel_url=url)
    await state.set_state(AdminStates.panel_user)
    await message.answer("یوزرنیم ادمین پنل را وارد کنید:")


@router.message(AdminStates.panel_user)
async def panel_user(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    await state.update_data(panel_user=message.text.strip())
    await state.set_state(AdminStates.panel_pass)
    await message.answer("رمز عبور ادمین پنل را وارد کنید:")


@router.message(AdminStates.panel_pass)
async def panel_pass(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    data = await state.get_data()
    url = data["panel_url"]
    user = data["panel_user"]
    password = message.text.strip()

    client = PanelClient(url, user, password)
    ok, msg = await client.test_connection()
    await client.close()

    if ok:
        # گرفتن گروه‌ها
        client2 = PanelClient(url, user, password)
        await client2.login()
        groups = await client2.get_groups()
        await client2.close()
        gids = [g.get("id") for g in groups if g.get("id")] if groups else []
        await save_panel(url, user, password, group_ids=json.dumps(gids))
        await state.clear()
        await message.answer(
            f"✅ {msg}\n\nگروه‌های پیدا شده: {len(gids)}\nاتصال ذخیره شد.",
            reply_markup=admin_menu(),
        )
    else:
        await state.clear()
        await message.answer(f"❌ {msg}\n\nدوباره از منوی ادمین تلاش کنید.", reply_markup=admin_menu())


# ---------- پلن‌ها ----------
@router.callback_query(F.data == "adm:plans")
async def adm_plans(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    plans = await get_plans(active_only=False)
    text = "📦 <b>مدیریت پلن‌ها</b>\n\n" + (f"{len(plans)} پلن ثبت شده." if plans else "هنوز پلنی نیست.")
    await callback.message.edit_text(text, reply_markup=plans_admin_kb(plans), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "adm:addplan")
async def adm_addplan(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admins:
        return
    await state.set_state(AdminStates.add_plan_title)
    await callback.message.edit_text("عنوان پلن را وارد کنید:\nمثال: ۱ ماهه ۲۰ گیگ", reply_markup=back_to_menu())
    await callback.answer()


@router.message(AdminStates.add_plan_title)
async def add_plan_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminStates.add_plan_days)
    await message.answer("تعداد روز را وارد کنید (عدد):\nمثال: 30")


@router.message(AdminStates.add_plan_days)
async def add_plan_days(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
    except Exception:
        await message.answer("عدد معتبر وارد کنید.")
        return
    await state.update_data(days=days)
    await state.set_state(AdminStates.add_plan_gb)
    await message.answer("حجم به گیگابایت را وارد کنید (عدد):\nمثال: 20")


@router.message(AdminStates.add_plan_gb)
async def add_plan_gb(message: Message, state: FSMContext):
    try:
        gb = int(message.text.strip())
    except Exception:
        await message.answer("عدد معتبر وارد کنید.")
        return
    await state.update_data(gb=gb)
    await state.set_state(AdminStates.add_plan_price)
    await message.answer("قیمت به تومان را وارد کنید (عدد):\nمثال: 49000")


@router.message(AdminStates.add_plan_price)
async def add_plan_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip().replace(",", ""))
    except Exception:
        await message.answer("عدد معتبر وارد کنید.")
        return
    data = await state.get_data()
    pid = await add_plan(data["title"], data["days"], data["gb"], price)
    await state.clear()
    await message.answer(f"✅ پلن با آیدی {pid} اضافه شد.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("adm:planinfo:"))
async def adm_planinfo(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    pid = int(callback.data.split(":")[2])
    plan = await get_plan(pid)
    if not plan:
        await callback.answer("پیدا نشد")
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 حذف پلن", callback_data=f"adm:delplan:{pid}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:plans")],
    ])
    text = (
        f"📦 {plan['title']}\n"
        f"روز: {plan['days']} | حجم: {plan['volume_gb']}GB\n"
        f"قیمت: {plan['price']:,} تومان"
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:delplan:"))
async def adm_delplan(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    pid = int(callback.data.split(":")[2])
    await delete_plan(pid)
    await callback.answer("حذف شد")
    plans = await get_plans(active_only=False)
    await callback.message.edit_text("📦 مدیریت پلن‌ها", reply_markup=plans_admin_kb(plans))


# ---------- کیف پول و کارت ----------
@router.callback_query(F.data == "adm:wallet_set")
async def adm_wallet_set(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admins:
        return
    card = await get_setting("card_number")
    name = await get_setting("card_name")
    min_d = await get_setting("min_deposit")
    text = (
        f"💳 <b>تنظیمات کارت</b>\n\n"
        f"شماره کارت: <code>{card}</code>\n"
        f"نام: {name}\n"
        f"حداقل واریز: {min_d}\n\n"
        f"شماره کارت جدید را ارسال کنید (یا /cancel):"
    )
    await state.set_state(AdminStates.set_card)
    await callback.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.set_card)
async def set_card(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    await set_setting("card_number", message.text.strip())
    await state.set_state(AdminStates.set_card_name)
    await message.answer("نام صاحب حساب را وارد کنید:")


@router.message(AdminStates.set_card_name)
async def set_card_name(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    await set_setting("card_name", message.text.strip())
    await state.set_state(AdminStates.set_min_deposit)
    await message.answer("حداقل مبلغ واریز (تومان) را وارد کنید:\nمثال: 20000")


@router.message(AdminStates.set_min_deposit)
async def set_min_deposit(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    try:
        val = int(message.text.strip().replace(",", ""))
        await set_setting("min_deposit", str(val))
    except Exception:
        await message.answer("عدد معتبر وارد کنید.")
        return
    await state.clear()
    await message.answer("✅ تنظیمات کارت ذخیره شد.", reply_markup=admin_menu())


# ---------- رسیدها ----------
@router.callback_query(F.data == "adm:receipts")
async def adm_receipts(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    recs = await get_pending_receipts()
    if not recs:
        await callback.message.edit_text("رسید در انتظاری وجود ندارد.", reply_markup=admin_menu())
    else:
        await callback.message.edit_text(
            f"🧾 {len(recs)} رسید در انتظار تأیید:",
            reply_markup=receipts_kb(recs),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:receipt:"))
async def adm_receipt_detail(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    rid = int(callback.data.split(":")[2])
    r = await get_receipt(rid)
    if not r:
        await callback.answer("پیدا نشد")
        return
    await callback.message.answer_photo(
        r["file_id"],
        caption=f"رسید #{rid}\nکاربر: {r['user_id']}\nمبلغ: {r['amount']:,}",
        reply_markup=receipt_action_kb(rid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:approve:"))
async def adm_approve(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    rid = int(callback.data.split(":")[2])
    r = await get_receipt(rid)
    if not r or r["status"] != "pending":
        await callback.answer("قبلاً بررسی شده", show_alert=True)
        return
    ok = await set_receipt_status(rid, "approved")
    if not ok:
        await callback.answer("قبلاً بررسی شده", show_alert=True)
        return
    await update_balance(r["user_id"], r["amount"])
    try:
        await callback.bot.send_message(
            r["user_id"],
            f"✅ رسید شما تأیید شد.\nمبلغ {r['amount']:,} تومان به کیف پول اضافه شد.",
        )
    except Exception:
        pass
    await callback.answer("تأیید شد و موجودی شارژ شد")
    try:
        cap = (callback.message.caption or "") + "\n\n✅ تأیید شد"
        await callback.message.edit_caption(caption=cap)
    except Exception:
        try:
            await callback.message.edit_text("✅ رسید تأیید شد.")
        except Exception:
            pass


@router.callback_query(F.data.startswith("adm:reject:"))
async def adm_reject(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    rid = int(callback.data.split(":")[2])
    r = await get_receipt(rid)
    if not r or r["status"] != "pending":
        await callback.answer("قبلاً بررسی شده", show_alert=True)
        return
    ok = await set_receipt_status(rid, "rejected")
    if not ok:
        await callback.answer("قبلاً بررسی شده", show_alert=True)
        return
    try:
        await callback.bot.send_message(r["user_id"], "❌ رسید شما رد شد. با پشتیبانی در تماس باشید.")
    except Exception:
        pass
    await callback.answer("رد شد")
    try:
        cap = (callback.message.caption or "") + "\n\n❌ رد شد"
        await callback.message.edit_caption(caption=cap)
    except Exception:
        try:
            await callback.message.edit_text("❌ رسید رد شد.")
        except Exception:
            pass


# ---------- تنظیمات عمومی ----------
@router.callback_query(F.data == "adm:settings")
async def adm_settings(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in settings.admins:
        return
    await state.set_state(AdminStates.set_welcome)
    welcome = await get_setting("welcome_text")
    await callback.message.edit_text(
        f"متن خوش‌آمدگویی فعلی:\n\n{welcome}\n\nمتن جدید را ارسال کنید:",
        reply_markup=back_to_menu(),
    )
    await callback.answer()


@router.message(AdminStates.set_welcome)
async def set_welcome(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    await set_setting("welcome_text", message.text)
    await state.set_state(AdminStates.set_support)
    await message.answer("متن پشتیبانی را وارد کنید:")


@router.message(AdminStates.set_support)
async def set_support(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admins:
        return
    await set_setting("support_text", message.text)
    await state.clear()
    await message.answer("✅ تنظیمات ذخیره شد.", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:stats")
async def adm_stats(callback: CallbackQuery):
    if callback.from_user.id not in settings.admins:
        return
    from database import DB_PATH
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        users = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        orders = (await (await db.execute("SELECT COUNT(*) FROM orders WHERE status='paid'")).fetchone())[0]
        revenue = (await (await db.execute("SELECT COALESCE(SUM(amount),0) FROM orders WHERE status='paid'")).fetchone())[0]
    text = (
        f"📊 <b>آمار</b>\n\n"
        f"کاربران: {users}\n"
        f"خریدهای موفق: {orders}\n"
        f"مجموع فروش: {revenue:,} تومان"
    )
    await callback.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
    await callback.answer()