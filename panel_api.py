"""
ارتباط با API پنل PasarGuard / JinX
"""
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class PanelClient:
    def __init__(self, base_url: str, username: str, password: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token = token
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def close(self):
        await self._client.aclose()

    async def login(self) -> bool:
        """لاگین و گرفتن توکن"""
        try:
            # PasarGuard معمولا از /api/admin/token استفاده می‌کند
            r = await self._client.post(
                f"{self.base_url}/api/admin/token",
                data={"username": self.username, "password": self.password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if r.status_code == 200:
                data = r.json()
                self.token = data.get("access_token") or data.get("token") or ""
                return bool(self.token)

            # روش جایگزین بعضی فورک‌ها
            r2 = await self._client.post(
                f"{self.base_url}/api/admins/token",
                json={"username": self.username, "password": self.password},
            )
            if r2.status_code == 200:
                data = r2.json()
                self.token = data.get("access_token") or data.get("token") or ""
                return bool(self.token)

            logger.error(f"Login failed: {r.status_code} {r.text[:200]}")
            return False
        except Exception as e:
            logger.exception(f"Login error: {e}")
            return False

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def test_connection(self) -> tuple[bool, str]:
        ok = await self.login()
        if not ok:
            return False, "لاگین ناموفق. یوزرنیم یا پسورد اشتباه است یا آدرس پنل اشتباه است."
        try:
            r = await self._client.get(f"{self.base_url}/api/system", headers=self._headers())
            if r.status_code == 200:
                return True, "اتصال موفق ✅"
            # بعضی نسخه‌ها
            r2 = await self._client.get(f"{self.base_url}/api/admin", headers=self._headers())
            if r2.status_code in (200, 401, 403):
                return True, "اتصال برقرار شد (توکن معتبر است)"
            return False, f"پاسخ غیرمنتظره: {r.status_code}"
        except Exception as e:
            return False, f"خطا در ارتباط: {e}"

    async def get_groups(self) -> List[dict]:
        try:
            r = await self._client.get(f"{self.base_url}/api/groups", headers=self._headers())
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data
                return data.get("groups") or data.get("items") or []
            return []
        except Exception:
            return []

    async def create_user(
        self,
        username: str,
        days: int,
        volume_gb: int,
        group_ids: List[int] | None = None,
        note: str = "خرید از ربات",
    ) -> tuple[Optional[dict], str]:
        """
        ساخت کاربر جدید در پنل
        بازگشت: (user_data, error_message)
        """
        if not self.token:
            if not await self.login():
                return None, "خطا در لاگین به پنل"

        expire = None
        if days > 0:
            expire = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"

        data_limit = volume_gb * 1024 * 1024 * 1024 if volume_gb > 0 else 0

        payload = {
            "username": username,
            "status": "active",
            "expire": expire,
            "data_limit": data_limit,
            "data_limit_reset_strategy": "no_reset",
            "note": note,
        }
        if group_ids:
            payload["group_ids"] = group_ids

        try:
            r = await self._client.post(
                f"{self.base_url}/api/user",
                json=payload,
                headers=self._headers(),
            )
            if r.status_code in (200, 201):
                return r.json(), ""

            # بعضی نسخه‌ها از /api/users استفاده می‌کنند
            r2 = await self._client.post(
                f"{self.base_url}/api/users",
                json=payload,
                headers=self._headers(),
            )
            if r2.status_code in (200, 201):
                return r2.json(), ""

            err = r.text[:300] if r.text else str(r.status_code)
            return None, f"خطای پنل: {err}"
        except Exception as e:
            return None, f"خطای ارتباط: {e}"

    async def get_subscription_url(self, username: str) -> str:
        """لینک ساب کاربر"""
        # فرمت رایج PasarGuard / Marzban-like
        return f"{self.base_url}/sub/{username}"


async def get_client_from_db() -> Optional[PanelClient]:
    from database import get_panel
    p = await get_panel()
    if not p.get("base_url") or not p.get("username"):
        return None
    return PanelClient(
        base_url=p["base_url"],
        username=p["username"],
        password=p.get("password") or "",
        token=p.get("token") or "",
    )