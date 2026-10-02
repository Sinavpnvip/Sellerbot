from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛒 خرید اشتراک", callback_data="shop"),
        InlineKeyboardButton(text="📋 اشتراک‌های من", callback_data="mysubs"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 کیف پول", callback_data="wallet"),
        InlineKeyboardButton(text="👤 پروفایل", callback_data="profile"),
    )
    builder.row(
        InlineKeyboardButton(text="🎁 اکانت تست", callback_data="trial"),
        InlineKeyboardButton(text="🤝 دعوت دوستان", callback_data="referral"),
    )
    builder.row(InlineKeyboardButton(text="💬 پشتیبانی", callback_data="support"))
    if is_admin:
        builder.row(InlineKeyboardButton(text="⚙️ پنل مدیریت", callback_data="admin"))
    return builder.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="menu")]
    ])


def plans_kb(plans: List[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in plans:
        text = f"{p['title']} — {p['price']:,} تومان"
        builder.row(InlineKeyboardButton(text=text, callback_data=f"buy:{p['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu"))
    return builder.as_markup()


def confirm_buy_kb(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تأیید و خرید", callback_data=f"confirm_buy:{plan_id}"),
            InlineKeyboardButton(text="❌ انصراف", callback_data="shop"),
        ]
    ])


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 اتصال به پنل JinX", callback_data="adm:panel"))
    builder.row(InlineKeyboardButton(text="📦 مدیریت پلن‌ها", callback_data="adm:plans"))
    builder.row(InlineKeyboardButton(text="💳 تنظیمات کارت و کیف پول", callback_data="adm:wallet_set"))
    builder.row(InlineKeyboardButton(text="🧾 رسیدهای در انتظار", callback_data="adm:receipts"))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات عمومی", callback_data="adm:settings"))
    builder.row(InlineKeyboardButton(text="📊 آمار", callback_data="adm:stats"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu"))
    return builder.as_markup()


def receipts_kb(receipts: List[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in receipts:
        name = r.get("username") or r.get("full_name") or str(r["user_id"])
        builder.row(
            InlineKeyboardButton(
                text=f"#{r['id']} | {name} | {r['amount']:,}",
                callback_data=f"adm:receipt:{r['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin"))
    return builder.as_markup()


def receipt_action_kb(rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ تأیید", callback_data=f"adm:approve:{rid}"),
            InlineKeyboardButton(text="❌ رد", callback_data=f"adm:reject:{rid}"),
        ],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm:receipts")],
    ])


def plans_admin_kb(plans: List[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in plans:
        status = "✅" if p["is_active"] else "❌"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {p['title']} | {p['price']:,}",
                callback_data=f"adm:planinfo:{p['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="➕ افزودن پلن", callback_data="adm:addplan"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin"))
    return builder.as_markup()