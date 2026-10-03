
"""قفل درون‌حافظه‌ای برای جلوگیری از دوبار کلیک روی خرید/تمدید/حجم"""
import asyncio
from collections import defaultdict

_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_inflight: set[int] = set()
_guard = asyncio.Lock()


async def acquire_user(user_id: int) -> bool:
    """اگر کاربر الان در حال تراکنش است False"""
    async with _guard:
        if user_id in _inflight:
            return False
        _inflight.add(user_id)
    return True


async def release_user(user_id: int):
    async with _guard:
        _inflight.discard(user_id)


def user_lock(user_id: int) -> asyncio.Lock:
    return _locks[user_id]
