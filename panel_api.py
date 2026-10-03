"""
اتصال چندپنلی: PasarGuard/JinX | Marzban | Hiddify | Custom
همه عملیات فروش از این ماژول رد می‌شود.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

GB = 1024 * 1024 * 1024


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _days_to_expire_iso(days: int) -> str:
    return (_now_utc() + timedelta(days=max(days, 0))).isoformat().replace("+00:00", "Z")


def _days_to_unix(days: int) -> int:
    return int((_now_utc() + timedelta(days=max(days, 0))).timestamp())


def _parse_expire(raw) -> Optional[datetime]:
    if raw is None or raw == "" or raw == 0:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            if ts <= 0:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class PanelClient:
    """کلاینت واحد با پشتیبانی چند نوع پنل."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        token: str = "",
        panel_type: str = "pasarguard",
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.username = username or ""
        self.password = password or ""
        self.token = token or ""
        self.panel_type = (panel_type or "pasarguard").lower().strip()
        if self.panel_type in ("jinx", "jin x", "pasar", "pg"):
            self.panel_type = "pasarguard"
        self._client = httpx.AsyncClient(timeout=30.0, verify=True, follow_redirects=True)

    async def close(self):
        await self._client.aclose()

    def _headers(self) -> dict:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    # ---------- Auth ----------
    async def login(self) -> bool:
        if self.token and self.panel_type != "hiddify":
            # توکن ذخیره‌شده را یک‌بار تست کن
            ok, _ = await self.test_connection()
            if ok:
                return True
        try:
            if self.panel_type == "hiddify":
                # Hiddify: API key در هدر یا path؛ پسورد را به‌عنوان api_key می‌گیریم
                self.token = self.password or self.token
                return bool(self.token)

            # PasarGuard / Marzban / Custom — فرم رایج
            for path in ("/api/admin/token", "/api/admins/token", "/api/token"):
                try:
                    r = await self._client.post(
                        f"{self.base_url}{path}",
                        data={"username": self.username, "password": self.password},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if r.status_code == 200:
                        data = r.json()
                        self.token = data.get("access_token") or data.get("token") or ""
                        if self.token:
                            return True
                except Exception:
                    continue

            # JSON body fallback
            r = await self._client.post(
                f"{self.base_url}/api/admin/token",
                json={"username": self.username, "password": self.password},
            )
            if r.status_code == 200:
                data = r.json()
                self.token = data.get("access_token") or data.get("token") or ""
                return bool(self.token)
        except Exception as e:
            logger.warning("login failed: %s", e)
        return False

    async def test_connection(self) -> Tuple[bool, str]:
        try:
            if not self.token and not await self.login():
                return False, "لاگین ناموفق — یوزر/رمز یا آدرس را چک کنید"
            if self.panel_type == "hiddify":
                r = await self._client.get(
                    f"{self.base_url}/api/v2/admin/user/",
                    headers={"Hiddify-API-Key": self.token, "Accept": "application/json"},
                )
                if r.status_code in (200, 201):
                    return True, "Hiddify متصل شد"
                return False, f"Hiddify: {r.status_code} {(r.text or '')[:120]}"

            for path in ("/api/admin", "/api/admins/current", "/api/system", "/api/core"):
                r = await self._client.get(f"{self.base_url}{path}", headers=self._headers())
                if r.status_code == 200:
                    return True, f"متصل ({self.panel_type})"
            # آخرین تلاش: لیست کاربران محدود
            r = await self._client.get(
                f"{self.base_url}/api/users",
                headers=self._headers(),
                params={"limit": 1},
            )
            if r.status_code == 200:
                return True, f"متصل ({self.panel_type})"
            return False, f"پاسخ نامعتبر: {r.status_code}"
        except Exception as e:
            return False, str(e)

    async def get_groups(self) -> List[dict]:
        if self.panel_type == "hiddify":
            return []
        if not self.token and not await self.login():
            return []
        for path in ("/api/groups", "/api/user/groups"):
            try:
                r = await self._client.get(f"{self.base_url}{path}", headers=self._headers())
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return data.get("groups") or data.get("items") or []
            except Exception:
                continue
        return []

    # ---------- User CRUD ----------
    async def create_user(
        self,
        username: str,
        days: int,
        volume_gb: int,
        group_ids: Optional[List[Any]] = None,
        note: str = "",
    ) -> Tuple[Optional[dict], str]:
        if not self.token and not await self.login():
            return None, "لاگین پنل ناموفق"

        if self.panel_type == "hiddify":
            return await self._hiddify_create(username, days, volume_gb, note)

        data_limit = int(volume_gb) * GB if volume_gb and int(volume_gb) > 0 else 0
        payload: Dict[str, Any] = {
            "username": username,
            "data_limit": data_limit,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "note": (note or "")[:500],
        }

        if self.panel_type in ("pasarguard", "custom"):
            payload["expire"] = _days_to_expire_iso(int(days))
            if group_ids:
                payload["group_ids"] = group_ids
        else:  # marzban
            payload["expire"] = _days_to_unix(int(days))
            # proxies حداقلی برای Marzban
            payload["proxies"] = {"vless": {}, "vmess": {}, "trojan": {}, "shadowsocks": {}}
            payload["inbounds"] = {}

        paths = [
            "/api/user",
            "/api/users",
        ]
        last_err = ""
        for path in paths:
            try:
                r = await self._client.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=self._headers(),
                )
                if r.status_code in (200, 201):
                    return r.json(), ""
                last_err = (r.text or str(r.status_code))[:300]
            except Exception as e:
                last_err = str(e)

        # PasarGuard گاهی بدون proxies؛ Marzban گاهی expire iso می‌خواهد
        if self.panel_type == "marzban":
            payload["expire"] = _days_to_expire_iso(int(days))
            try:
                r = await self._client.post(
                    f"{self.base_url}/api/user",
                    json=payload,
                    headers=self._headers(),
                )
                if r.status_code in (200, 201):
                    return r.json(), ""
                last_err = (r.text or str(r.status_code))[:300]
            except Exception as e:
                last_err = str(e)

        return None, f"خطای ساخت کاربر: {last_err}"

    async def _hiddify_create(self, username, days, volume_gb, note):
        try:
            body = {
                "name": username,
                "usage_limit_GB": float(volume_gb) if volume_gb else 0,
                "package_days": int(days),
                "comment": note[:200],
                "enable": True,
            }
            r = await self._client.post(
                f"{self.base_url}/api/v2/admin/user/",
                json=body,
                headers={"Hiddify-API-Key": self.token, "Accept": "application/json"},
            )
            if r.status_code in (200, 201):
                data = r.json()
                # normalize
                if isinstance(data, dict):
                    data.setdefault("username", username)
                    uuid = data.get("uuid") or data.get("user_info", {}).get("uuid")
                    if uuid:
                        data["subscription_url"] = f"{self.base_url}/{uuid}/"
                return data, ""
            return None, (r.text or str(r.status_code))[:300]
        except Exception as e:
            return None, str(e)

    async def get_user(self, username: str) -> Tuple[Optional[dict], str]:
        if not self.token and not await self.login():
            return None, "لاگین ناموفق"
        if self.panel_type == "hiddify":
            try:
                r = await self._client.get(
                    f"{self.base_url}/api/v2/admin/user/",
                    headers={"Hiddify-API-Key": self.token, "Accept": "application/json"},
                    params={"search": username},
                )
                if r.status_code == 200:
                    data = r.json()
                    items = data if isinstance(data, list) else data.get("results") or data.get("users") or []
                    for it in items:
                        if str(it.get("name") or it.get("username") or "") == username:
                            return it, ""
                    if items:
                        return items[0], ""
                return None, "کاربر پیدا نشد"
            except Exception as e:
                return None, str(e)

        for path in (f"/api/user/{username}", f"/api/users/{username}"):
            try:
                r = await self._client.get(f"{self.base_url}{path}", headers=self._headers())
                if r.status_code == 200:
                    return r.json(), ""
            except Exception as e:
                last = str(e)
        return None, "کاربر پیدا نشد"

    async def _put_user(self, username: str, payload: dict) -> Tuple[bool, str]:
        for path in (f"/api/user/{username}", f"/api/users/{username}"):
            try:
                r = await self._client.put(
                    f"{self.base_url}{path}", json=payload, headers=self._headers()
                )
                if r.status_code in (200, 201):
                    return True, ""
                last = (r.text or str(r.status_code))[:300]
            except Exception as e:
                last = str(e)
        return False, last if "last" in dir() else "خطا"

    async def modify_user(
        self, username: str, extra_days: int = 0, extra_gb: int = 0
    ) -> Tuple[bool, str]:
        user, err = await self.get_user(username)
        if err or not user:
            return False, err or "کاربر نیست"

        if self.panel_type == "hiddify":
            return await self._hiddify_modify(user, username, extra_days, extra_gb)

        payload: Dict[str, Any] = {}
        if extra_days:
            base = _parse_expire(user.get("expire")) or _now_utc()
            if base < _now_utc():
                base = _now_utc()
            new_exp = base + timedelta(days=int(extra_days))
            if self.panel_type == "marzban":
                payload["expire"] = int(new_exp.timestamp())
            else:
                payload["expire"] = new_exp.isoformat().replace("+00:00", "Z")

        if extra_gb:
            cur = int(user.get("data_limit") or 0)
            add = int(extra_gb) * GB
            payload["data_limit"] = add if cur <= 0 else cur + add

        # PasarGuard expects group_ids often
        if "group_ids" in user:
            payload.setdefault("group_ids", user.get("group_ids") or [])
        if user.get("status"):
            payload.setdefault("status", user.get("status"))

        if not payload:
            return False, "تغییری نیست"
        return await self._put_user(username, payload)

    async def _hiddify_modify(self, user, username, extra_days, extra_gb):
        try:
            uuid = user.get("uuid") or user.get("user_info", {}).get("uuid")
            if not uuid:
                return False, "uuid نیست"
            body = {}
            if extra_days:
                body["package_days"] = int(user.get("package_days") or 0) + int(extra_days)
            if extra_gb:
                body["usage_limit_GB"] = float(user.get("usage_limit_GB") or 0) + float(extra_gb)
            r = await self._client.patch(
                f"{self.base_url}/api/v2/admin/user/{uuid}/",
                json=body,
                headers={"Hiddify-API-Key": self.token, "Accept": "application/json"},
            )
            return (True, "") if r.status_code in (200, 201) else (False, (r.text or str(r.status_code))[:200])
        except Exception as e:
            return False, str(e)

    async def delete_user(self, username: str) -> Tuple[bool, str]:
        if not self.token and not await self.login():
            return False, "لاگین ناموفق"
        if self.panel_type == "hiddify":
            user, err = await self.get_user(username)
            if err or not user:
                return False, err or "نیست"
            uuid = user.get("uuid") or user.get("user_info", {}).get("uuid")
            if not uuid:
                return False, "uuid نیست"
            r = await self._client.delete(
                f"{self.base_url}/api/v2/admin/user/{uuid}/",
                headers={"Hiddify-API-Key": self.token},
            )
            return (True, "") if r.status_code in (200, 204) else (False, str(r.status_code))
        for path in (f"/api/user/{username}", f"/api/users/{username}"):
            r = await self._client.delete(f"{self.base_url}{path}", headers=self._headers())
            if r.status_code in (200, 204):
                return True, ""
        return False, "حذف ناموفق"

    async def set_status(self, username: str, status: str) -> Tuple[bool, str]:
        user, err = await self.get_user(username)
        if err or not user:
            return False, err or "نیست"
        if self.panel_type == "hiddify":
            uuid = user.get("uuid") or user.get("user_info", {}).get("uuid")
            if not uuid:
                return False, "uuid نیست"
            r = await self._client.patch(
                f"{self.base_url}/api/v2/admin/user/{uuid}/",
                json={"enable": status == "active"},
                headers={"Hiddify-API-Key": self.token, "Accept": "application/json"},
            )
            return (True, "") if r.status_code in (200, 201) else (False, str(r.status_code))
        payload = {
            "status": status,
            "group_ids": user.get("group_ids") or [],
            "expire": user.get("expire"),
            "data_limit": user.get("data_limit"),
        }
        return await self._put_user(username, payload)

    async def admin_set_expire_days(self, username: str, days_from_now: int) -> Tuple[bool, str]:
        user, err = await self.get_user(username)
        if err or not user:
            return False, err or "نیست"
        if self.panel_type == "hiddify":
            uuid = user.get("uuid") or user.get("user_info", {}).get("uuid")
            r = await self._client.patch(
                f"{self.base_url}/api/v2/admin/user/{uuid}/",
                json={"package_days": max(int(days_from_now), 0)},
                headers={"Hiddify-API-Key": self.token, "Accept": "application/json"},
            )
            return (True, "") if r.status_code in (200, 201) else (False, str(r.status_code))
        exp = _now_utc() + timedelta(days=max(int(days_from_now), 0) or 0, minutes=1)
        if self.panel_type == "marzban":
            expire_val: Any = int(exp.timestamp())
        else:
            expire_val = exp.isoformat().replace("+00:00", "Z")
        payload = {
            "expire": expire_val,
            "group_ids": user.get("group_ids") or [],
            "status": user.get("status") or "active",
            "data_limit": user.get("data_limit"),
        }
        return await self._put_user(username, payload)

    async def admin_adjust_days(self, username: str, delta_days: int) -> Tuple[bool, str]:
        return await self.modify_user(username, extra_days=int(delta_days), extra_gb=0)

    async def admin_set_data_gb(self, username: str, gb: int) -> Tuple[bool, str]:
        user, err = await self.get_user(username)
        if err or not user:
            return False, err or "نیست"
        limit = 0 if int(gb) <= 0 else int(gb) * GB
        if self.panel_type == "hiddify":
            uuid = user.get("uuid") or user.get("user_info", {}).get("uuid")
            r = await self._client.patch(
                f"{self.base_url}/api/v2/admin/user/{uuid}/",
                json={"usage_limit_GB": float(gb)},
                headers={"Hiddify-API-Key": self.token, "Accept": "application/json"},
            )
            return (True, "") if r.status_code in (200, 201) else (False, str(r.status_code))
        payload = {
            "data_limit": limit,
            "group_ids": user.get("group_ids") or [],
            "status": user.get("status") or "active",
            "expire": user.get("expire"),
        }
        return await self._put_user(username, payload)

    async def admin_adjust_gb(self, username: str, delta_gb: int) -> Tuple[bool, str]:
        if int(delta_gb) >= 0:
            return await self.modify_user(username, extra_days=0, extra_gb=int(delta_gb))
        user, err = await self.get_user(username)
        if err or not user:
            return False, err or "نیست"
        if self.panel_type == "hiddify":
            cur = float(user.get("usage_limit_GB") or 0)
            return await self.admin_set_data_gb(username, max(int(cur + delta_gb), 0))
        cur = int(user.get("data_limit") or 0)
        new_limit = max(cur + int(delta_gb) * GB, 0)
        payload = {
            "data_limit": new_limit,
            "group_ids": user.get("group_ids") or [],
            "status": user.get("status") or "active",
            "expire": user.get("expire"),
        }
        return await self._put_user(username, payload)

    async def get_subscription_url(self, username: str) -> str:
        user, err = await self.get_user(username)
        if user:
            for k in ("subscription_url", "subscriptionUrl", "sub_link", "link"):
                if user.get(k):
                    return str(user[k])
            uuid = user.get("uuid") or user.get("user_info", {}).get("uuid")
            if uuid and self.panel_type == "hiddify":
                return f"{self.base_url}/{uuid}/"
        return f"{self.base_url}/sub/{username}"


async def get_client_from_db() -> Optional[PanelClient]:
    from database import get_panel

    p = await get_panel()
    if not p.get("base_url"):
        return None
    # username optional for hiddify (api key in password)
    if p.get("panel_type") != "hiddify" and not p.get("username"):
        return None
    return PanelClient(
        base_url=p["base_url"],
        username=p.get("username") or "",
        password=p.get("password") or "",
        token=p.get("token") or "",
        panel_type=p.get("panel_type") or "pasarguard",
    )


PANEL_TYPES = [
    ("pasarguard", "PasarGuard / JinX"),
    ("marzban", "Marzban"),
    ("hiddify", "Hiddify"),
    ("custom", "سفارشی (شبیه Marzban/PG)"),
]
