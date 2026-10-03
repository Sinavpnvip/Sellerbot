import asyncio
import logging
import os
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from database import init_db
from handlers import user, admin
from handlers import admin_extra
from handlers import services
from handlers import admin_services

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



async def reminder_worker(bot: Bot):
    """یادآوری انقضای سرویس — قابل تنظیم از settings"""
    import asyncio
    from datetime import datetime, timezone
    from database import (
        get_setting, get_all_paid_orders, was_reminder_sent, mark_reminder_sent,
    )
    from panel_api import get_client_from_db
    while True:
        try:
            await asyncio.sleep(3600)  # هر ساعت
            if (await get_setting("remind_enabled", "1")) != "1":
                continue
            raw = await get_setting("remind_days", "3,1")
            days_list = []
            for x in raw.split(","):
                x = x.strip()
                if x.isdigit():
                    days_list.append(int(x))
            if not days_list:
                continue
            client = await get_client_from_db()
            if not client:
                continue
            orders = await get_all_paid_orders()
            now = datetime.now(timezone.utc)
            for order in orders:
                uname = order.get("panel_username")
                uid = order.get("user_id")
                oid = order.get("id")
                if not uname or not uid:
                    continue
                data, err = await client.get_user(uname)
                if err or not data:
                    continue
                exp_raw = data.get("expire")
                exp = None
                try:
                    if isinstance(exp_raw, (int, float)):
                        ts = float(exp_raw)
                        if ts > 1e12:
                            ts /= 1000.0
                        if ts > 0:
                            exp = datetime.fromtimestamp(ts, tz=timezone.utc)
                    elif exp_raw:
                        s = str(exp_raw).replace("Z", "+00:00")
                        exp = datetime.fromisoformat(s)
                        if exp.tzinfo is None:
                            exp = exp.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if not exp:
                    continue
                left_days = int((exp - now).total_seconds() // 86400)
                for d in days_list:
                    if left_days == d:
                        kind = f"d{d}"
                        if await was_reminder_sent(oid, kind):
                            continue
                        try:
                            await bot.send_message(
                                uid,
                                f"⏰ <b>یادآوری انقضا</b>\n\n"
                                f"سرویس <code>{uname}</code>\n"
                                f"حدود <b>{d}</b> روز تا انقضا مانده.\n"
                                f"از «سرویس‌های من» می‌توانید تمدید کنید.",
                                parse_mode="HTML",
                            )
                            await mark_reminder_sent(oid, kind)
                        except Exception:
                            pass
            await client.close()
        except Exception as e:
            logging.getLogger(__name__).exception("reminder error: %s", e)
            await asyncio.sleep(60)


async def on_startup(bot: Bot):
    await init_db()
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username}")
    asyncio.create_task(reminder_worker(bot))


async def health(request):
    return web.Response(text="ok")


async def main():
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(user.router)
    dp.include_router(admin.router)
    dp.include_router(admin_extra.router)
    dp.include_router(services.router)
    dp.include_router(admin_services.router)
    dp.startup.register(on_startup)

    # Health check for Railway
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", settings.port))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server on port {port}")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())