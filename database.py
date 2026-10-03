import aiosqlite
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = Path("./data/bot.db")


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            full_name TEXT DEFAULT '',
            balance INTEGER DEFAULT 0,
            ref_code TEXT UNIQUE,
            ref_by INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            days INTEGER NOT NULL,
            volume_gb INTEGER NOT NULL,
            price INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_id INTEGER,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            panel_username TEXT,
            sub_url TEXT,
            created_at TEXT,
            paid_at TEXT
        );

        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            file_id TEXT,
            status TEXT DEFAULT 'pending',
            admin_note TEXT DEFAULT '',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS panel (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            base_url TEXT DEFAULT '',
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            token TEXT DEFAULT '',
            group_ids TEXT DEFAULT '[]',
            is_connected INTEGER DEFAULT 0,
            panel_type TEXT DEFAULT 'pasarguard'
        );

        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            discount_type TEXT DEFAULT 'percent',
            discount_value INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 0,
            used_count INTEGER DEFAULT 0,
            min_order INTEGER DEFAULT 0,
            expire_at TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS coupon_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coupon_id INTEGER,
            user_id INTEGER,
            used_at TEXT,
            UNIQUE(coupon_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS trials (
            user_id INTEGER PRIMARY KEY,
            used_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            admin_reply TEXT DEFAULT '',
            created_at TEXT,
            replied_at TEXT
        );

        CREATE TABLE IF NOT EXISTS volume_packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            gb INTEGER NOT NULL,
            price INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS reminder_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            sent_at TEXT,
            UNIQUE(order_id, kind)
        );
        """)
        await db.commit()

        # seed default settings
        defaults = {
            "shop_title": "فروشگاه وی‌پی‌ان",
            "card_number": "6037-****-****-****",
            "card_name": "نام صاحب حساب",
            "min_deposit": "20000",
            "trial_days": "1",
            "trial_gb": "1",
            "trial_enabled": "1",
            "ref_percent": "20",
            "support_text": "برای پشتیبانی به @YourSupport پیام دهید",
            "welcome_text": "به فروشگاه خوش آمدید 👋\nاز منوی زیر استفاده کنید.",
            "force_channel": "",
            "force_channel_id": "0",
            "custom_username": "1",
            "renew_enabled": "1",
            "volume_enabled": "1",
            "status_enabled": "1",
            "remind_enabled": "1",
            "remind_days": "3,1",
            "remind_hour_utc": "8",
        }
        for k, v in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )
        await db.execute(
            "INSERT OR IGNORE INTO panel (id) VALUES (1)"
        )
        try:
            await db.execute("ALTER TABLE panel ADD COLUMN panel_type TEXT DEFAULT 'pasarguard'")
        except Exception:
            pass
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> Dict[str, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {r["key"]: r["value"] for r in rows}


# ---------- Users ----------
async def ensure_user(tg_id: int, username: str = "", full_name: str = "") -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if row:
            return dict(row)

        import secrets
        ref_code = secrets.token_hex(2)
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO users (tg_id, username, full_name, ref_code, created_at) VALUES (?, ?, ?, ?, ?)",
            (tg_id, username or "", full_name or "", ref_code, now),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        return dict(await cur.fetchone())


async def get_user(tg_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def update_balance(tg_id: int, amount: int) -> bool:
    """افزایش/کاهش موجودی. اگر amount منفی باشد و موجودی کافی نباشد False برمی‌گرداند."""
    async with aiosqlite.connect(DB_PATH) as db:
        if amount < 0:
            cur = await db.execute(
                "UPDATE users SET balance = balance + ? WHERE tg_id = ? AND balance >= ?",
                (amount, tg_id, abs(amount)),
            )
            await db.commit()
            return cur.rowcount > 0
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE tg_id = ?", (amount, tg_id)
        )
        await db.commit()
        return True


async def is_user_blocked(tg_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT is_blocked FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return bool(row and row[0])


async def set_ref(tg_id: int, ref_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET ref_by = ? WHERE tg_id = ? AND (ref_by = 0 OR ref_by IS NULL)",
            (ref_by, tg_id),
        )
        await db.commit()


# ---------- Plans ----------
async def get_plans(active_only: bool = True) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM plans"
        if active_only:
            q += " WHERE is_active = 1"
        q += " ORDER BY sort_order, id"
        cur = await db.execute(q)
        return [dict(r) for r in await cur.fetchall()]


async def add_plan(title: str, days: int, volume_gb: int, price: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO plans (title, days, volume_gb, price) VALUES (?, ?, ?, ?)",
            (title, days, volume_gb, price),
        )
        await db.commit()
        return cur.lastrowid


async def delete_plan(plan_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
        await db.commit()


async def get_plan(plan_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM plans WHERE id = ?", (plan_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


# ---------- Panel config ----------
async def get_panel() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM panel WHERE id = 1")
        row = await cur.fetchone()
        return dict(row) if row else {}


async def save_panel(base_url: str, username: str, password: str, token: str = "", group_ids: str = "[]", panel_type: str = "pasarguard"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO panel (id, base_url, username, password, token, group_ids, panel_type)
               VALUES (1, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 base_url=excluded.base_url,
                 username=excluded.username,
                 password=excluded.password,
                 token=excluded.token,
                 group_ids=excluded.group_ids,
                 panel_type=excluded.panel_type
            """,
            (base_url, username, password, token, group_ids, panel_type or "pasarguard"),
        )
        await db.commit()


async def create_order(user_id: int, plan_id: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        cur = await db.execute(
            "INSERT INTO orders (user_id, plan_id, amount, created_at) VALUES (?, ?, ?, ?)",
            (user_id, plan_id, amount, now),
        )
        await db.commit()
        return cur.lastrowid


async def complete_order(order_id: int, panel_username: str, sub_url: str):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        await db.execute(
            "UPDATE orders SET status='paid', panel_username=?, sub_url=?, paid_at=? WHERE id=?",
            (panel_username, sub_url, now, order_id),
        )
        await db.commit()


async def add_receipt(user_id: int, amount: int, file_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        cur = await db.execute(
            "INSERT INTO receipts (user_id, amount, file_id, created_at) VALUES (?, ?, ?, ?)",
            (user_id, amount, file_id, now),
        )
        await db.commit()
        return cur.lastrowid


async def get_pending_receipts() -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT r.*, u.username, u.full_name FROM receipts r LEFT JOIN users u ON u.tg_id = r.user_id WHERE r.status='pending' ORDER BY r.id"
        )
        return [dict(r) for r in await cur.fetchall()]


async def set_receipt_status(rid: int, status: str, note: str = "") -> bool:
    """فقط اگر هنوز pending باشد آپدیت می‌کند. True = موفق"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE receipts SET status=?, admin_note=? WHERE id=? AND status='pending'",
            (status, note, rid),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_receipt(rid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM receipts WHERE id = ?", (rid,))
        row = await cur.fetchone()
        return dict(row) if row else None

# ---------- Coupons ----------
async def add_coupon(code: str, discount_type: str, discount_value: int, max_uses: int = 0, min_order: int = 0, expire_at: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        cur = await db.execute(
            "INSERT INTO coupons (code, discount_type, discount_value, max_uses, min_order, expire_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (code.upper().strip(), discount_type, discount_value, max_uses, min_order, expire_at, now),
        )
        await db.commit()
        return cur.lastrowid


async def get_coupon(code: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM coupons WHERE code = ? AND is_active = 1", (code.upper().strip(),))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_coupons() -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM coupons ORDER BY id DESC")
        return [dict(r) for r in await cur.fetchall()]


async def use_coupon(coupon_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            now = datetime.utcnow().isoformat()
            await db.execute(
                "INSERT INTO coupon_uses (coupon_id, user_id, used_at) VALUES (?, ?, ?)",
                (coupon_id, user_id, now),
            )
            await db.execute(
                "UPDATE coupons SET used_count = used_count + 1 WHERE id = ?", (coupon_id,)
            )
            await db.commit()
            return True
        except Exception:
            return False


async def has_used_coupon(coupon_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM coupon_uses WHERE coupon_id = ? AND user_id = ?",
            (coupon_id, user_id),
        )
        return await cur.fetchone() is not None


async def delete_coupon(cid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM coupons WHERE id = ?", (cid,))
        await db.commit()


# ---------- User management ----------
async def set_user_balance(tg_id: int, balance: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = ? WHERE tg_id = ?", (balance, tg_id))
        await db.commit()


async def set_user_blocked(tg_id: int, blocked: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_blocked = ? WHERE tg_id = ?", (1 if blocked else 0, tg_id)
        )
        await db.commit()


async def search_users(query: str, limit: int = 20) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = f"%{query}%"
        cur = await db.execute(
            "SELECT * FROM users WHERE CAST(tg_id AS TEXT) LIKE ? OR username LIKE ? OR full_name LIKE ? LIMIT ?",
            (q, q, q, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT tg_id FROM users WHERE is_blocked = 0")
        return [r[0] for r in await cur.fetchall()]


# ---------- Trial ----------
async def has_used_trial(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM trials WHERE user_id = ?", (user_id,))
        return await cur.fetchone() is not None


async def claim_trial(user_id: int) -> bool:
    """اتمیک: فقط اولین‌بار True"""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        try:
            cur = await db.execute(
                "INSERT INTO trials (user_id, used_at) VALUES (?, ?)",
                (user_id, now),
            )
            await db.commit()
            return cur.rowcount > 0
        except Exception:
            return False


async def mark_trial_used(user_id: int):
    await claim_trial(user_id)


# ---------- Support tickets ----------
async def create_ticket(user_id: int, message: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        cur = await db.execute(
            "INSERT INTO tickets (user_id, message, created_at) VALUES (?, ?, ?)",
            (user_id, message[:2000], now),
        )
        await db.commit()
        return cur.lastrowid


async def get_open_tickets(limit: int = 30) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT t.*, u.username, u.full_name FROM tickets t
               LEFT JOIN users u ON u.tg_id = t.user_id
               WHERE t.status='open' ORDER BY t.id DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_ticket(tid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM tickets WHERE id=?", (tid,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def reply_ticket(tid: int, reply: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.utcnow().isoformat()
        cur = await db.execute(
            "UPDATE tickets SET status='replied', admin_reply=?, replied_at=? WHERE id=? AND status='open'",
            (reply[:2000], now, tid),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_user_orders(user_id: int, limit: int = 20) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM orders WHERE user_id=? AND status='paid' ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


# ---------- Volume packs ----------
async def get_volume_packs(active_only: bool = True) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM volume_packs"
        if active_only:
            q += " WHERE is_active=1"
        q += " ORDER BY gb, id"
        cur = await db.execute(q)
        return [dict(r) for r in await cur.fetchall()]


async def add_volume_pack(title: str, gb: int, price: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO volume_packs (title, gb, price) VALUES (?, ?, ?)",
            (title, gb, price),
        )
        await db.commit()
        return cur.lastrowid


async def delete_volume_pack(pid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM volume_packs WHERE id=?", (pid,))
        await db.commit()


async def get_volume_pack(pid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM volume_packs WHERE id=?", (pid,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_order_by_id(oid: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE id=?", (oid,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_paid_orders() -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM orders WHERE status='paid' AND panel_username IS NOT NULL")
        return [dict(r) for r in await cur.fetchall()]


async def mark_reminder_sent(order_id: int, kind: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            now = datetime.utcnow().isoformat()
            await db.execute(
                "INSERT INTO reminder_log (order_id, kind, sent_at) VALUES (?, ?, ?)",
                (order_id, kind, now),
            )
            await db.commit()
            return True
        except Exception:
            return False


async def was_reminder_sent(order_id: int, kind: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM reminder_log WHERE order_id=? AND kind=?",
            (order_id, kind),
        )
        return await cur.fetchone() is not None
