from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🛒 خرید اشتراک", callback_data="shop"),
        InlineKeyboardButton(text="✨ سرویس‌های من", callback_data="mysubs"),
    )
    b.row(
        InlineKeyboardButton(text="💎 کیف پول", callback_data="wallet"),
        InlineKeyboardButton(text="👤 پروفایل", callback_data="profile"),
    )
    b.row(
        InlineKeyboardButton(text="🎁 تست رایگان", callback_data="trial"),
        InlineKeyboardButton(text="🤝 دعوت دوستان", callback_data="referral"),
    )
    b.row(InlineKeyboardButton(text="💬 پشتیبانی", callback_data="support"))
    if is_admin:
        b.row(InlineKeyboardButton(text="🛠 پنل مدیریت", callback_data="admin"))
    return b.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu")]
    ])


def back_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ پنل ادمین", callback_data="admin")]
    ])


def plans_kb(plans: List[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in plans:
        b.row(InlineKeyboardButton(
            text=f"📦 {p['title']}  •  {p['price']:,} ت",
            callback_data=f"buy:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu"))
    return b.as_markup()


def plan_offer_kb(plan_id: int, has_coupon: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if not has_coupon:
        rows.append([InlineKeyboardButton(text="🎟 کد تخفیف دارم", callback_data=f"ask_coupon:{plan_id}")])
    rows.append([InlineKeyboardButton(text="✅ ادامه خرید", callback_data=f"go_buy:{plan_id}")])
    rows.append([
        InlineKeyboardButton(text="✏️ نام دلخواه", callback_data=f"custom_name:{plan_id}"),
        InlineKeyboardButton(text="🔙 پلن‌ها", callback_data="shop"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def final_buy_kb(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأیید و خرید", callback_data=f"confirm_buy:{plan_id}")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="shop")],
    ])


def low_balance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 افزایش موجودی", callback_data="topup")],
        [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu")],
    ])


def wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزایش موجودی", callback_data="topup")],
        [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu")],
    ])


def after_amount_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف", callback_data="wallet")],
    ])


def mysub_item_kb(order_id: int, sub_url: str) -> InlineKeyboardMarkup:
    # URL button if valid http
    rows = []
    if sub_url and sub_url.startswith("http"):
        rows.append([InlineKeyboardButton(text="🔗 باز کردن لینک", url=sub_url)])
    rows.append([InlineKeyboardButton(text="📋 کپی لینک", callback_data=f"copy_sub:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔗 اتصال پنل", callback_data="adm:panel"))
    b.row(InlineKeyboardButton(text="🛠 مدیریت سرویس پنل", callback_data="adm:svc"))
    b.row(
        InlineKeyboardButton(text="📦 پلن‌ها", callback_data="adm:plans"),
        InlineKeyboardButton(text="🎟 کد تخفیف", callback_data="adm:coupons"),
    )
    b.row(
        InlineKeyboardButton(text="👥 کاربران", callback_data="adm:users"),
        InlineKeyboardButton(text="🧾 رسیدها", callback_data="adm:receipts"),
    )
    b.row(
        InlineKeyboardButton(text="💬 تیکت‌ها", callback_data="adm:tickets"),
        InlineKeyboardButton(text="💳 کارت بانکی", callback_data="adm:wallet_set"),
    )
    b.row(
        InlineKeyboardButton(text="🤝 درصد دعوت", callback_data="adm:ref_percent"),
        InlineKeyboardButton(text="📢 پیام همگانی", callback_data="adm:broadcast"),
    )
    b.row(
        InlineKeyboardButton(text="🎁 تنظیم تست", callback_data="adm:trial_set"),
        InlineKeyboardButton(text="📣 کانال اجباری", callback_data="adm:force_ch"),
    )
    b.row(
        InlineKeyboardButton(text="📶 پکیج حجم", callback_data="adm:volpacks"),
        InlineKeyboardButton(text="⏰ یادآوری انقضا", callback_data="adm:remind"),
    )
    b.row(
        InlineKeyboardButton(text="✏️ متن‌ها", callback_data="adm:settings"),
        InlineKeyboardButton(text="📊 آمار", callback_data="adm:stats"),
    )
    b.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu"))
    return b.as_markup()


def receipts_kb(receipts: List[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in receipts:
        name = r.get("username") or r.get("full_name") or str(r["user_id"])
        b.row(InlineKeyboardButton(
            text=f"🧾 #{r['id']} | {name} | {r['amount']:,}",
            callback_data=f"adm:receipt:{r['id']}",
        ))
    b.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin"))
    return b.as_markup()


def receipt_action_kb(rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تأیید و شارژ", callback_data=f"adm:approve:{rid}"),
            InlineKeyboardButton(text="❌ رد", callback_data=f"adm:reject:{rid}"),
        ],
        [InlineKeyboardButton(text="⬅️ لیست", callback_data="adm:receipts")],
    ])


def plans_admin_kb(plans: List[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in plans:
        st = "🟢" if p["is_active"] else "🔴"
        b.row(InlineKeyboardButton(
            text=f"{st} {p['title']} | {p['price']:,}",
            callback_data=f"adm:planinfo:{p['id']}",
        ))
    b.row(InlineKeyboardButton(text="➕ پلن جدید", callback_data="adm:addplan"))
    b.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin"))
    return b.as_markup()


def coupons_admin_kb(coupons: List[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in coupons:
        st = "🟢" if c["is_active"] else "🔴"
        dtype = "%" if c["discount_type"] == "percent" else "ت"
        b.row(InlineKeyboardButton(
            text=f"{st} {c['code']} | {c['discount_value']}{dtype} | {c['used_count']}/{c['max_uses'] or '∞'}",
            callback_data=f"adm:couponinfo:{c['id']}",
        ))
    b.row(InlineKeyboardButton(text="➕ کد جدید", callback_data="adm:addcoupon"))
    b.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin"))
    return b.as_markup()


def user_manage_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 تنظیم موجودی", callback_data=f"adm:setbal:{tg_id}"),
            InlineKeyboardButton(text="➕ افزایش", callback_data=f"adm:addbal:{tg_id}"),
        ],
        [InlineKeyboardButton(text="✉️ پیام به کاربر", callback_data=f"adm:msguser:{tg_id}")],
        [
            InlineKeyboardButton(text="🚫 مسدود", callback_data=f"adm:block:{tg_id}"),
            InlineKeyboardButton(text="✅ رفع مسدود", callback_data=f"adm:unblock:{tg_id}"),
        ],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="adm:users")],
    ])


def tickets_kb(tickets: List[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in tickets:
        name = t.get("username") or t.get("full_name") or str(t["user_id"])
        preview = (t.get("message") or "")[:20]
        b.row(InlineKeyboardButton(
            text=f"💬 #{t['id']} | {name} | {preview}",
            callback_data=f"adm:ticket:{t['id']}",
        ))
    b.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin"))
    return b.as_markup()


def join_channel_kb(channel: str) -> InlineKeyboardMarkup:
    ch = channel.lstrip("@")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 عضویت در کانال", url=f"https://t.me/{ch}")],
        [InlineKeyboardButton(text="✅ عضو شدم", callback_data="check_join")],
    ])
