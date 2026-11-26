import os
import re
import sqlite3
import json
import secrets
from datetime import datetime, timedelta, timezone

# Database path
DB_DIR = os.path.dirname(os.path.abspath(__file__))
if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/whatsapp_messages.db"
else:
    DB_PATH = os.path.join(os.path.dirname(DB_DIR), "whatsapp_messages.db")

_DB_INITIALIZED = False

DEFAULT_TEMPLATES = [
    ("👋 Welcome Greeting", "Greeting", "Hello {{name}}! 👋 Thank you for reaching out to Growhaz (https://www.growhaz.in/). How can we assist you with our cybersecurity, app development, or blockchain solutions today?", "/welcome"),
    ("🛡️ Security Vulnerability Scan", "Security", "Hi {{name}}, you can run automated vulnerability scans (Alpha G1/G5) on your website in under 5 minutes. Start your audit here: https://www.growhaz.in/security-tools", "/security"),
    ("📱 Appify & Web Development", "Development", "Hi {{name}}, we build high-speed static websites, dynamic web apps, and convert websites to native Android/iOS mobile apps. Check our portfolio: https://www.growhaz.in/development", "/development"),
    ("🔗 Blockchain Verification", "Trust", "Hi {{name}}, you can instantly verify certificates and documents on our blockchain ledger here: https://www.growhaz.in/verify", "/verify"),
    ("💰 Pricing & Packages", "Pricing", "Hi {{name}}, here is our transparent pricing guide:\n• AlphaG1 Scan: ₹1,999 | AlphaG5: ₹4,999\n• Static Website: ₹20,000 | Dynamic: ₹60,000+\n• Details: https://www.growhaz.in/pricing", "/pricing"),
    ("📅 Consultation Booking", "Bookings", "Hi {{name}}, your consultation with Growhaz is registered for {{service}} on {{date_time}}! Need to reschedule? Visit https://www.growhaz.in/contact", "/confirm"),
    ("👤 Human Handover", "Handover", "A specialist from the Growhaz engineering team has joined this chat. One moment please while I connect you.", "/agent"),
    ("⭐ Feedback & CSAT Survey", "Feedback", "Hi {{name}}, how was your Growhaz experience today? Please rate us from 1 (Poor) to 5 (Excellent) ⭐. Visit us at https://www.growhaz.in/ . Thank you!", "/feedback"),
]


def _get_cloud_store():
    try:
        from api.supabase_store import get_cloud_store
        return get_cloud_store()
    except ImportError:
        try:
            from supabase_store import get_cloud_store
            return get_cloud_store()
        except Exception:
            return None
    except Exception:
        return None


_get_neo4j = _get_cloud_store


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except Exception:
        pass
    return conn


def _migrate_composite_tables(cursor):
    """Safely upgrade legacy single-PK tables to composite (tenant_id, phone_number) uniqueness."""
    # 1. contact_settings
    info = cursor.execute("PRAGMA table_info(contact_settings)").fetchall()
    cols = {r["name"] for r in info}
    if "tenant_id" not in cols:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_settings_v2 (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                bot_enabled INTEGER DEFAULT 1,
                assigned_agent TEXT DEFAULT 'Support Team',
                tags TEXT DEFAULT 'Customer',
                notes TEXT DEFAULT '',
                PRIMARY KEY (tenant_id, phone_number)
            )
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO contact_settings_v2 (tenant_id, phone_number, bot_enabled, assigned_agent, tags, notes)
            SELECT 'default', phone_number, COALESCE(bot_enabled, 1), COALESCE(assigned_agent, 'Support Team'),
                   COALESCE(tags, 'Customer'), COALESCE(notes, '')
            FROM contact_settings
        """)
        cursor.execute("DROP TABLE contact_settings")
        cursor.execute("ALTER TABLE contact_settings_v2 RENAME TO contact_settings")

    # 2. customer_profiles
    pinfo = cursor.execute("PRAGMA table_info(customer_profiles)").fetchall()
    pcols = {r["name"] for r in pinfo}
    if "tenant_id" not in pcols:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customer_profiles_v2 (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                contact_name TEXT DEFAULT '',
                business_name TEXT DEFAULT '',
                business_category TEXT DEFAULT '',
                area TEXT DEFAULT '',
                has_website TEXT DEFAULT '',
                website_url TEXT DEFAULT '',
                existing_ecosystem TEXT DEFAULT '',
                pain_points TEXT DEFAULT '',
                goals TEXT DEFAULT '',
                data_source TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, phone_number)
            )
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO customer_profiles_v2 (
                tenant_id, phone_number, contact_name, business_name, business_category,
                area, has_website, website_url, existing_ecosystem, pain_points, goals,
                data_source, updated_at, created_at
            )
            SELECT 'default', phone_number, contact_name, business_name, business_category,
                   area, has_website, website_url, existing_ecosystem, pain_points, goals,
                   data_source, updated_at, created_at
            FROM customer_profiles
        """)
        cursor.execute("DROP TABLE customer_profiles")
        cursor.execute("ALTER TABLE customer_profiles_v2 RENAME TO customer_profiles")

    # 3. leads
    linfo = cursor.execute("PRAGMA table_info(leads)").fetchall()
    lcols = {r["name"] for r in linfo}
    if "tenant_id" not in lcols:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                name TEXT DEFAULT 'Lead',
                source TEXT DEFAULT 'Manual Import',
                status TEXT DEFAULT 'New',
                notes TEXT DEFAULT '',
                last_messaged_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, phone_number)
            )
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO leads_v2 (id, tenant_id, phone_number, name, source, status, notes, last_messaged_at, created_at)
            SELECT id, 'default', phone_number, name, source, status, notes, last_messaged_at, created_at
            FROM leads
        """)
        cursor.execute("DROP TABLE leads")
        cursor.execute("ALTER TABLE leads_v2 RENAME TO leads")


def init_db(force: bool = False):
    """Initialize database tables for multi-tenant SaaS, billing, security, messages, and profiles."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED and not force:
        return
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Tenants Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                email TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                business_name TEXT DEFAULT '',
                custom_system_prompt TEXT DEFAULT '',
                billing_mode TEXT DEFAULT 'managed_meta',
                plan_tier TEXT DEFAULT 'payg',
                plan_quota INTEGER DEFAULT 0,
                plan_used INTEGER DEFAULT 0,
                plan_expires_at TEXT DEFAULT '',
                demo_used INTEGER DEFAULT 0,
                whatsapp_token TEXT DEFAULT '',
                whatsapp_phone_number_id TEXT DEFAULT '',
                whatsapp_verify_token TEXT DEFAULT '',
                deepseek_api_key TEXT DEFAULT '',
                deepseek_model TEXT DEFAULT 'deepseek-chat',
                groq_api_key TEXT DEFAULT '',
                groq_model TEXT DEFAULT 'llama-3.3-70b-versatile',
                openrouter_api_key TEXT DEFAULT '',
                openrouter_guard_model TEXT DEFAULT 'meta-llama/llama-guard-4-12b',
                meta_app_secret TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for tcol in ("meta_app_secret TEXT DEFAULT ''",):
            try:
                cursor.execute(f"ALTER TABLE tenants ADD COLUMN {tcol}")
            except Exception:
                pass

        # Messages Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                sender_name TEXT DEFAULT 'User',
                message TEXT NOT NULL,
                direction TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'meta_whatsapp',
                status TEXT DEFAULT 'received',
                raw_payload TEXT,
                ai_model TEXT,
                latency_ms REAL DEFAULT 0,
                media_type TEXT,
                media_url TEXT,
                media_filename TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        for col_def in [
            "tenant_id TEXT NOT NULL DEFAULT 'default'",
            "media_type TEXT",
            "media_url TEXT",
            "media_filename TEXT",
        ]:
            try:
                cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_def}")
            except Exception:
                pass

        # Bookings & Support Requests Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                customer_name TEXT DEFAULT 'Customer',
                service_requested TEXT DEFAULT 'Customer Support / Appointment',
                booking_date_time TEXT DEFAULT 'Pending Schedule',
                status TEXT DEFAULT 'pending',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE bookings ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        except Exception:
            pass

        # Message Templates Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                title TEXT NOT NULL,
                category TEXT DEFAULT 'General',
                content TEXT NOT NULL,
                shortcut TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE templates ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        except Exception:
            pass

        # Contact Settings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_settings (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                bot_enabled INTEGER DEFAULT 1,
                assigned_agent TEXT DEFAULT 'Support Team',
                tags TEXT DEFAULT 'Customer',
                notes TEXT DEFAULT '',
                PRIMARY KEY (tenant_id, phone_number)
            )
        """)

        # Webhook Logs Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                payload TEXT,
                status_code INTEGER DEFAULT 200,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("ALTER TABLE webhook_logs ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        except Exception:
            pass

        # Leads & CRM Prospects Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                name TEXT DEFAULT 'Lead',
                source TEXT DEFAULT 'Manual Import',
                status TEXT DEFAULT 'New',
                notes TEXT DEFAULT '',
                last_messaged_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, phone_number)
            )
        """)

        # Persistent Customer & Business Ecosystem Profiles
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customer_profiles (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                contact_name TEXT DEFAULT '',
                business_name TEXT DEFAULT '',
                business_category TEXT DEFAULT '',
                area TEXT DEFAULT '',
                has_website TEXT DEFAULT '',
                website_url TEXT DEFAULT '',
                existing_ecosystem TEXT DEFAULT '',
                pain_points TEXT DEFAULT '',
                goals TEXT DEFAULT '',
                data_source TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, phone_number)
            )
        """)

        # 24h Billing Windows Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS billing_windows (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                billing_mode TEXT DEFAULT 'managed_meta',
                cost_coins REAL DEFAULT 0,
                charge_source TEXT DEFAULT 'free_demo',
                opened_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, phone_number)
            )
        """)

        # Security / Prompt-Injection Events Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT DEFAULT '',
                input_text TEXT NOT NULL,
                detector TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                blocked INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Webhook Event Deduplication / Idempotency Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_events (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                event_id TEXT NOT NULL,
                phone_number TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, event_id)
            )
        """)

        # Multi-Turn Conversation State & Pending Action Confirmation Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_state (
                tenant_id TEXT NOT NULL DEFAULT 'default',
                phone_number TEXT NOT NULL,
                stage TEXT DEFAULT 'idle',
                pending_action_json TEXT DEFAULT '',
                pending_expires_at TEXT DEFAULT '',
                last_intent TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                PRIMARY KEY (tenant_id, phone_number)
            )
        """)

        # Centralised Agent Action Audit Trail
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS action_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                actor TEXT DEFAULT '',
                phone_number TEXT DEFAULT '',
                action_name TEXT NOT NULL,
                status TEXT NOT NULL,
                risk_level TEXT DEFAULT 'low',
                details_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Failed Webhook Job Dead-Letter Queue
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dead_letter_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                event_id TEXT DEFAULT '',
                phone_number TEXT DEFAULT '',
                payload_json TEXT DEFAULT '{}',
                error_message TEXT DEFAULT '',
                attempts INTEGER DEFAULT 0,
                status TEXT DEFAULT 'failed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        _migrate_composite_tables(cursor)

        # Ensure default workspace tenant row exists (verify token comes from env or random secret)
        env_vtoken = (os.getenv("WHATSAPP_VERIFY_TOKEN", "") or "").strip() or f"gh_v_{secrets.token_urlsafe(16)}"
        cursor.execute(
            "INSERT OR IGNORE INTO tenants (tenant_id, business_name, billing_mode, whatsapp_verify_token) VALUES ('default', 'Growhaz Support Desk', 'managed_meta', ?)",
            (env_vtoken,),
        )

        # Seed default support templates for default tenant if completely empty
        cursor.execute("SELECT COUNT(*) as count FROM templates WHERE tenant_id = 'default'")
        if cursor.fetchone()["count"] == 0:
            cursor.executemany(
                "INSERT INTO templates (tenant_id, title, category, content, shortcut) VALUES ('default', ?, ?, ?, ?)",
                DEFAULT_TEMPLATES,
            )

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phone ON messages(phone_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenant_phone ON messages(tenant_id, phone_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phone_created ON messages(tenant_id, phone_number, created_at DESC)")

        conn.commit()
        conn.close()
        _DB_INITIALIZED = True
    except Exception as e:
        print(f"[DB] Error initializing database: {e}")


def sync_with_neo4j_on_boot() -> dict:
    """Hydrate local SQLite from persistent Supabase Cloud Postgres (keeping all historical chats across deploys)."""
    init_db()
    store = _get_cloud_store()
    if not store:
        return {"connected": False}
    try:
        conn = get_connection()
        res = store.hydrate_and_sync_sqlite(conn)
        conn.close()
        return {"connected": store.get_status().get("connected", False), **res}
    except Exception as e:
        print(f"[DB] Cloud boot sync warning: {e}")
        return {"connected": False, "error": str(e)}


# ==================== TENANT & BILLING HELPERS ====================

def ensure_tenant(tenant_id: str, email: str = "", full_name: str = "") -> dict:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tid,)).fetchone()
    if not row:
        default_vtoken = f"gh_v_{secrets.token_urlsafe(24)}" if tid != "default" else ((os.getenv("WHATSAPP_VERIFY_TOKEN", "") or "").strip() or f"gh_v_{secrets.token_urlsafe(24)}")
        bname = f"{full_name}'s Business" if full_name else "My Business"
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, email, full_name, business_name, whatsapp_verify_token)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tid, email or "", full_name or "", bname, default_vtoken),
        )
        # Seed starter templates for this new workspace
        cur.executemany(
            "INSERT INTO templates (tenant_id, title, category, content, shortcut) VALUES (?, ?, ?, ?, ?)",
            [(tid, t[0], t[1], t[2], t[3]) for t in DEFAULT_TEMPLATES],
        )
        conn.commit()
        row = cur.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tid,)).fetchone()
    elif email or full_name:
        if (email and row["email"] != email) or (full_name and not row["full_name"]):
            cur.execute(
                """
                UPDATE tenants
                SET email = CASE WHEN ? != '' THEN ? ELSE email END,
                    full_name = CASE WHEN ? != '' AND (full_name IS NULL OR full_name = '') THEN ? ELSE full_name END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ?
                """,
                (email, email, full_name, full_name, tid),
            )
            conn.commit()
            row = cur.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tid,)).fetchone()

    tenant = dict(row) if row else {"tenant_id": tid}
    conn.close()
    neo = _get_neo4j()
    if neo:
        neo.upsert_tenant(tenant)
    return tenant


def get_tenant(tenant_id: str) -> dict:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    conn = get_connection()
    row = conn.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else {"tenant_id": tid}


def update_tenant_settings(tenant_id: str, **fields) -> dict:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    ensure_tenant(tid)
    allowed = {
        "business_name", "custom_system_prompt", "billing_mode",
        "whatsapp_token", "whatsapp_phone_number_id", "whatsapp_verify_token", "meta_app_secret",
        "deepseek_api_key", "deepseek_model", "groq_api_key", "groq_model",
        "openrouter_api_key", "openrouter_guard_model",
    }
    updates = {k: str(v).strip() for k, v in fields.items() if k in allowed and v is not None}
    if updates:
        conn = get_connection()
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys()) + ", updated_at = CURRENT_TIMESTAMP"
        conn.execute(f"UPDATE tenants SET {set_clause} WHERE tenant_id = ?", (*updates.values(), tid))
        conn.commit()
        conn.close()
    tenant = get_tenant(tid)
    neo = _get_neo4j()
    if neo:
        neo.upsert_tenant(tenant)
    return tenant


def update_tenant_plan(tenant_id: str, billing_mode: str, plan_tier: str, plan_quota: int, plan_expires_at: str) -> dict:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    ensure_tenant(tid)
    conn = get_connection()
    conn.execute(
        """
        UPDATE tenants
        SET billing_mode = ?, plan_tier = ?, plan_quota = ?, plan_used = 0,
            plan_expires_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE tenant_id = ?
        """,
        (billing_mode, plan_tier, int(plan_quota), plan_expires_at, tid),
    )
    conn.commit()
    conn.close()
    tenant = get_tenant(tid)
    neo = _get_neo4j()
    if neo:
        neo.upsert_tenant(tenant)
    return tenant


def increment_tenant_demo_used(tenant_id: str) -> int:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    conn = get_connection()
    conn.execute("UPDATE tenants SET demo_used = COALESCE(demo_used, 0) + 1, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = ?", (tid,))
    conn.commit()
    row = conn.execute("SELECT demo_used FROM tenants WHERE tenant_id = ?", (tid,)).fetchone()
    conn.close()
    val = int(row["demo_used"]) if row else 1
    neo = _get_neo4j()
    if neo:
        neo.upsert_tenant(get_tenant(tid))
    return val


def increment_tenant_plan_used(tenant_id: str) -> int:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    conn = get_connection()
    conn.execute("UPDATE tenants SET plan_used = COALESCE(plan_used, 0) + 1, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = ?", (tid,))
    conn.commit()
    row = conn.execute("SELECT plan_used FROM tenants WHERE tenant_id = ?", (tid,)).fetchone()
    conn.close()
    val = int(row["plan_used"]) if row else 1
    neo = _get_neo4j()
    if neo:
        neo.upsert_tenant(get_tenant(tid))
    return val


def find_tenant_for_webhook(tenant_id: str = "", phone_number_id: str = "", verify_token: str = "") -> dict:
    init_db()
    conn = get_connection()
    if tenant_id:
        r = conn.execute("SELECT * FROM tenants WHERE tenant_id = ? LIMIT 1", (tenant_id.strip(),)).fetchone()
        if r:
            conn.close()
            return dict(r)
    if phone_number_id:
        r = conn.execute("SELECT * FROM tenants WHERE whatsapp_phone_number_id = ? LIMIT 1", (phone_number_id.strip(),)).fetchone()
        if r:
            conn.close()
            return dict(r)
    if verify_token:
        r = conn.execute("SELECT * FROM tenants WHERE whatsapp_verify_token = ? LIMIT 1", (verify_token.strip(),)).fetchone()
        if r:
            conn.close()
            return dict(r)
    r = conn.execute("SELECT * FROM tenants WHERE tenant_id = 'default' LIMIT 1").fetchone()
    conn.close()
    return dict(r) if r else {"tenant_id": "default"}


def is_billing_window_active(tenant_id: str, phone_number: str) -> bool:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    norm = normalize_phone_key(phone_number) or str(phone_number or "").replace("+", "").strip()
    if not norm:
        return False
    conn = get_connection()
    row = conn.execute(
        "SELECT expires_at FROM billing_windows WHERE tenant_id = ? AND phone_number = ?",
        (tid, norm),
    ).fetchone()
    conn.close()
    if not row or not row["expires_at"]:
        return False
    try:
        exp = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        return exp > datetime.now(timezone.utc)
    except Exception:
        return False


def record_billing_window(
    tenant_id: str,
    phone_number: str,
    billing_mode: str,
    cost_coins: float,
    charge_source: str,
    opened_at: str,
    expires_at: str,
):
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    norm = normalize_phone_key(phone_number) or str(phone_number or "").replace("+", "").strip()
    if not norm:
        return
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO billing_windows (tenant_id, phone_number, billing_mode, cost_coins, charge_source, opened_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tenant_id, phone_number) DO UPDATE SET
            billing_mode = excluded.billing_mode,
            cost_coins = excluded.cost_coins,
            charge_source = excluded.charge_source,
            opened_at = excluded.opened_at,
            expires_at = excluded.expires_at
        """,
        (tid, norm, billing_mode, float(cost_coins or 0), charge_source, opened_at, expires_at),
    )
    conn.commit()
    conn.close()
    neo = _get_neo4j()
    if neo:
        neo.upsert_billing_window_node({
            "tenant_id": tid,
            "phone_number": norm,
            "billing_mode": billing_mode,
            "cost_coins": cost_coins,
            "charge_source": charge_source,
            "opened_at": opened_at,
            "expires_at": expires_at,
        })


def save_security_event(tenant_id: str, phone_number: str, input_text: str, detector: str, reason: str, blocked: bool = True):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO security_events (tenant_id, phone_number, input_text, detector, reason, blocked)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tid, str(phone_number or ""), str(input_text or "")[:500], str(detector or ""), str(reason or ""), 1 if blocked else 0),
        )
        eid = cur.lastrowid
        conn.commit()
        row = cur.execute("SELECT * FROM security_events WHERE id = ?", (eid,)).fetchone()
        conn.close()
        if row:
            neo = _get_neo4j()
            if neo:
                neo.save_security_event_node(dict(row))
    except Exception as e:
        print(f"[DB] Security event log warning: {e}")


def get_security_events(tenant_id: str = "default", limit: int = 30) -> list:
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM security_events WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
            (tid, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ==================== MESSAGES, CONVERSATIONS & BOOKINGS ====================

def save_message(
    phone_number: str,
    message: str,
    direction: str = "inbound",
    sender_name: str = "User",
    channel: str = "meta_whatsapp",
    status: str = "received",
    raw_payload: dict = None,
    ai_model: str = None,
    latency_ms: float = 0.0,
    media_type: str = None,
    media_url: str = None,
    media_filename: str = None,
    tenant_id: str = "default",
):
    """Save an incoming or outgoing message to SQLite + mirror persistently to Neo4j AuraDB."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()

        payload_str = json.dumps(raw_payload) if isinstance(raw_payload, (dict, list)) else (raw_payload or "")

        cursor.execute(
            """
            INSERT INTO messages (
                tenant_id, phone_number, sender_name, message, direction, channel,
                status, raw_payload, ai_model, latency_ms, media_type, media_url, media_filename
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tid, phone_number, sender_name, message, direction, channel, status, payload_str, ai_model, latency_ms, media_type, media_url, media_filename),
        )

        msg_id = cursor.lastrowid

        if direction == "inbound" and message:
            detect_and_record_booking(cursor, phone_number, sender_name, message, tenant_id=tid)

        conn.commit()
        row = cursor.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
        conn.close()

        if row:
            neo = _get_neo4j()
            if neo:
                neo.save_message_node(dict(row))
        return msg_id
    except Exception as e:
        print(f"[DB] Error saving message: {e}")
        return None


def detect_and_record_booking(cursor, phone_number: str, customer_name: str, message: str, tenant_id: str = "default"):
    """Detect if incoming message has booking or order intent."""
    tid = str(tenant_id or "default").strip() or "default"
    msg_lower = message.lower()
    booking_keywords = ["book", "booking", "appointment", "schedule", "reserve", "slot", "meeting", "consultation", "order", "scan", "security", "app", "appify", "verify"]

    if any(k in msg_lower for k in booking_keywords):
        service = "Growhaz Service Consultation"
        if "security" in msg_lower or "scan" in msg_lower:
            service = "Website Security Audit (Alpha G5)"
        elif "app" in msg_lower or "appify" in msg_lower:
            service = "Appify Website to Mobile App"
        elif "blockchain" in msg_lower or "verify" in msg_lower:
            service = "Blockchain Document Verification"
        elif "web" in msg_lower or "develop" in msg_lower:
            service = "Secure Web Development"
        elif "consult" in msg_lower:
            service = "Growhaz Technical Consultation"
        elif "order" in msg_lower or "book" in msg_lower:
            service = "Growhaz Service Order"

        existing = cursor.execute(
            """
            SELECT id FROM bookings
            WHERE tenant_id = ? AND phone_number = ? AND created_at >= datetime('now', '-2 hours')
            LIMIT 1
            """,
            (tid, phone_number),
        ).fetchone()

        if not existing:
            cursor.execute(
                """
                INSERT INTO bookings (tenant_id, phone_number, customer_name, service_requested, booking_date_time, status, notes)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (tid, phone_number, customer_name or "WhatsApp Customer", service, "Requested via WhatsApp", message),
            )
            bid = cursor.lastrowid
            neo = _get_neo4j()
            if neo and bid:
                neo.save_booking_node({
                    "id": bid,
                    "tenant_id": tid,
                    "phone_number": phone_number,
                    "customer_name": customer_name or "WhatsApp Customer",
                    "service_requested": service,
                    "booking_date_time": "Requested via WhatsApp",
                    "status": "pending",
                    "notes": message,
                })


def is_bot_enabled_for_contact(phone_number: str, tenant_id: str = "default") -> bool:
    """Check if automated bot is enabled for this customer phone number."""
    if not phone_number:
        return True
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        clean = str(phone_number).replace("+", "").strip()
        row = conn.execute(
            """
            SELECT bot_enabled FROM contact_settings
            WHERE tenant_id = ?
              AND (phone_number = ? OR phone_number = ? OR REPLACE(phone_number, '+', '') = ?)
            LIMIT 1
            """,
            (tid, phone_number, f"+{clean}", clean),
        ).fetchone()
        conn.close()
        if row is not None:
            return bool(row["bot_enabled"])
        return True
    except Exception as e:
        print(f"[DB] Error checking bot enabled: {e}")
        return True


def set_bot_enabled_for_contact(phone_number: str, enabled: bool, tenant_id: str = "default"):
    """Toggle automated bot for this customer."""
    if not phone_number:
        return False
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()
        clean = str(phone_number).replace("+", "").strip()
        val = 1 if enabled else 0

        keys = set([str(phone_number).strip(), clean, f"+{clean}"])
        neo = _get_neo4j()
        for p in keys:
            if p:
                cursor.execute(
                    """
                    INSERT INTO contact_settings (tenant_id, phone_number, bot_enabled)
                    VALUES (?, ?, ?)
                    ON CONFLICT(tenant_id, phone_number) DO UPDATE SET bot_enabled = excluded.bot_enabled
                    """,
                    (tid, p, val),
                )
                if neo:
                    neo.upsert_contact_setting_node(tid, p, val)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] Error setting bot enabled: {e}")
        return False


def get_conversations(tenant_id: str = "default"):
    """Get list of distinct contact conversations for a tenant."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                m1.phone_number,
                COALESCE(
                    (SELECT m_in.sender_name FROM messages m_in WHERE m_in.tenant_id = ? AND REPLACE(m_in.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') AND m_in.direction = 'inbound' ORDER BY m_in.id DESC LIMIT 1),
                    m1.sender_name,
                    'Customer'
                ) as sender_name,
                COALESCE(
                    NULLIF(m1.message, ''),
                    CASE
                        WHEN m1.media_type = 'image' THEN '📷 Photo'
                        WHEN m1.media_type = 'document' THEN '📄 ' || COALESCE(m1.media_filename, 'Document')
                        ELSE 'Attachment'
                    END
                ) as last_message,
                m1.media_type as last_media_type,
                m1.direction as last_direction,
                m1.channel as last_channel,
                m1.created_at as last_time,
                (SELECT m_in.created_at FROM messages m_in WHERE m_in.tenant_id = ? AND REPLACE(m_in.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') AND m_in.direction = 'inbound' ORDER BY m_in.id DESC LIMIT 1) as last_inbound_time,
                (SELECT COUNT(*) FROM messages m2 WHERE m2.tenant_id = ? AND REPLACE(m2.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '')) as total_messages,
                (SELECT COUNT(*) FROM messages m3 WHERE m3.tenant_id = ? AND REPLACE(m3.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') AND m3.direction = 'inbound') as inbound_count,
                COALESCE((SELECT cs.bot_enabled FROM contact_settings cs WHERE cs.tenant_id = ? AND REPLACE(cs.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') LIMIT 1), 1) as bot_enabled
            FROM messages m1
            WHERE m1.tenant_id = ?
              AND m1.id IN (
                  SELECT MAX(id) FROM messages WHERE tenant_id = ? GROUP BY REPLACE(phone_number, '+', '')
              )
            ORDER BY m1.created_at DESC
        """
        cursor.execute(query, (tid, tid, tid, tid, tid, tid, tid))
        rows = cursor.fetchall()
        conn.close()

        utc_now = datetime.now(timezone.utc)
        conversations = []
        for row in rows:
            d = dict(row)
            last_inbound_str = d.get("last_inbound_time")
            free_window_active = False
            remaining_seconds = 0
            if last_inbound_str:
                try:
                    raw_s = str(last_inbound_str).strip()
                    if "T" in raw_s:
                        inbound_dt = datetime.fromisoformat(raw_s.replace("Z", "+00:00"))
                        if inbound_dt.tzinfo is None:
                            inbound_dt = inbound_dt.replace(tzinfo=timezone.utc)
                    else:
                        clean_ts = raw_s.split(".")[0].strip()
                        inbound_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    elapsed = (utc_now - inbound_dt).total_seconds()
                    if 0 <= elapsed < 86400:
                        free_window_active = True
                        remaining_seconds = int(86400 - elapsed)
                except Exception as err:
                    print(f"[DB] Error parsing inbound timestamp: {err}")
            d["free_window_active"] = free_window_active
            d["free_window_remaining_seconds"] = remaining_seconds
            conversations.append(d)

        return conversations
    except Exception as e:
        print(f"[DB] Error getting conversations: {e}")
        return []


def get_messages(phone_number: str = None, limit: int = 500, tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()

        if phone_number:
            clean = str(phone_number).replace("+", "").strip()
            cursor.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages
                    WHERE tenant_id = ?
                      AND (phone_number = ? OR phone_number = ? OR REPLACE(phone_number, '+', '') = ?)
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC, id ASC
                """,
                (tid, phone_number, f"+{clean}", clean, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM messages
                WHERE tenant_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (tid, limit),
            )

        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error getting messages: {e}")
        return []


def get_templates(tenant_id: str = "default"):
    """Get all response templates for a tenant (seeding starter templates if none exist)."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()
        rows = cursor.execute("SELECT * FROM templates WHERE tenant_id = ? ORDER BY id ASC", (tid,)).fetchall()
        if not rows:
            cursor.executemany(
                "INSERT INTO templates (tenant_id, title, category, content, shortcut) VALUES (?, ?, ?, ?, ?)",
                [(tid, t[0], t[1], t[2], t[3]) for t in DEFAULT_TEMPLATES],
            )
            conn.commit()
            rows = cursor.execute("SELECT * FROM templates WHERE tenant_id = ? ORDER BY id ASC", (tid,)).fetchall()
            neo = _get_neo4j()
            if neo:
                for r in rows:
                    neo.save_template_node(dict(r))
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error getting templates: {e}")
        return []


def save_template(title: str, category: str, content: str, shortcut: str = "", tenant_id: str = "default"):
    """Save a new custom message template."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO templates (tenant_id, title, category, content, shortcut) VALUES (?, ?, ?, ?, ?)",
            (tid, title, category, content, shortcut),
        )
        t_id = cursor.lastrowid
        conn.commit()
        row = cursor.execute("SELECT * FROM templates WHERE id = ?", (t_id,)).fetchone()
        conn.close()
        if row:
            neo = _get_neo4j()
            if neo:
                neo.save_template_node(dict(row))
        return t_id
    except Exception as e:
        print(f"[DB] Error saving template: {e}")
        return None


def delete_template(template_id: int, tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        conn.execute("DELETE FROM templates WHERE id = ? AND tenant_id = ?", (template_id, tid))
        conn.commit()
        conn.close()
        neo = _get_neo4j()
        if neo:
            neo.delete_template_node(tid, template_id)
        return True
    except Exception:
        return False


def get_bookings(tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM bookings WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 100",
            (tid,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def update_booking_status(booking_id: int, status: str, tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        conn.execute("UPDATE bookings SET status = ? WHERE id = ? AND tenant_id = ?", (status, booking_id, tid))
        conn.commit()
        conn.close()
        neo = _get_neo4j()
        if neo:
            neo.update_booking_node(tid, booking_id, status)
        return True
    except Exception:
        return False


def add_manual_booking(phone_number: str, customer_name: str, service: str, date_time: str, status: str = "confirmed", notes: str = "", tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO bookings (tenant_id, phone_number, customer_name, service_requested, booking_date_time, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tid, phone_number, customer_name, service, date_time, status, notes),
        )
        conn.commit()
        booking_id = cursor.lastrowid
        row = cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        conn.close()
        if row:
            neo = _get_neo4j()
            if neo:
                neo.save_booking_node(dict(row))
        return booking_id
    except Exception:
        return None


def get_stats(tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()

        total_messages = cursor.execute("SELECT COUNT(*) as total FROM messages WHERE tenant_id = ?", (tid,)).fetchone()["total"]
        total_contacts = cursor.execute("SELECT COUNT(DISTINCT phone_number) as contacts FROM messages WHERE tenant_id = ?", (tid,)).fetchone()["contacts"]
        inbound_messages = cursor.execute("SELECT COUNT(*) as inbound FROM messages WHERE tenant_id = ? AND direction = 'inbound'", (tid,)).fetchone()["inbound"]
        outbound_messages = cursor.execute("SELECT COUNT(*) as outbound FROM messages WHERE tenant_id = ? AND direction = 'outbound'", (tid,)).fetchone()["outbound"]

        avg_row = cursor.execute("SELECT AVG(latency_ms) as avg_latency FROM messages WHERE tenant_id = ? AND latency_ms > 0", (tid,)).fetchone()
        avg_latency = round(avg_row["avg_latency"] or 0, 2) if avg_row else 0

        total_webhooks = cursor.execute("SELECT COUNT(*) as count FROM webhook_logs WHERE tenant_id = ?", (tid,)).fetchone()["count"]
        total_bookings = cursor.execute("SELECT COUNT(*) as count FROM bookings WHERE tenant_id = ?", (tid,)).fetchone()["count"]

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        today_messages = cursor.execute(
            "SELECT COUNT(*) as today_total FROM messages WHERE tenant_id = ? AND created_at LIKE ?",
            (tid, f"{today_str}%"),
        ).fetchone()["today_total"]

        cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        active_free_windows = cursor.execute(
            """
            SELECT COUNT(DISTINCT REPLACE(phone_number, '+', '')) as active_window_count
            FROM messages
            WHERE tenant_id = ? AND direction = 'inbound' AND created_at >= ?
            """,
            (tid, cutoff_24h),
        ).fetchone()["active_window_count"] or 0

        blocked_attacks = cursor.execute(
            "SELECT COUNT(*) as cnt FROM security_events WHERE tenant_id = ? AND blocked = 1",
            (tid,),
        ).fetchone()["cnt"]

        conn.close()
        return {
            "total_messages": total_messages,
            "total_contacts": total_contacts,
            "inbound_messages": inbound_messages,
            "outbound_messages": outbound_messages,
            "avg_latency_ms": avg_latency,
            "total_webhooks": total_webhooks,
            "total_bookings": total_bookings,
            "today_messages": today_messages,
            "active_free_windows": active_free_windows,
            "blocked_attacks": blocked_attacks,
        }
    except Exception:
        return {
            "total_messages": 0, "total_contacts": 0, "inbound_messages": 0, "outbound_messages": 0,
            "avg_latency_ms": 0, "total_webhooks": 0, "total_bookings": 0, "today_messages": 0,
            "active_free_windows": 0, "blocked_attacks": 0,
        }


def save_webhook_log(endpoint: str, method: str, payload: any = None, status_code: int = 200, ip_address: str = "", tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        payload_str = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload or "")
        conn.execute(
            "INSERT INTO webhook_logs (tenant_id, endpoint, method, payload, status_code, ip_address) VALUES (?, ?, ?, ?, ?, ?)",
            (tid, endpoint, method, payload_str, status_code, ip_address),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_webhook_logs(limit: int = 50, tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM webhook_logs WHERE tenant_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (tid, limit),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def clear_data(tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        conn.execute("DELETE FROM messages WHERE tenant_id = ?", (tid,))
        conn.execute("DELETE FROM bookings WHERE tenant_id = ?", (tid,))
        conn.execute("DELETE FROM webhook_logs WHERE tenant_id = ?", (tid,))
        conn.commit()
        conn.close()
        neo = _get_neo4j()
        if neo:
            neo.clear_tenant_messages(tid)
        return True
    except Exception:
        return False


def delete_messages(message_ids: list, tenant_id: str = "default"):
    """Delete one or multiple messages by their IDs for this tenant."""
    if not message_ids:
        return False
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        ids = [int(i) for i in message_ids if str(i).isdigit()]
        if not ids:
            conn.close()
            return False
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM messages WHERE tenant_id = ? AND id IN ({placeholders})", [tid, *ids])
        conn.commit()
        conn.close()
        neo = _get_neo4j()
        if neo:
            neo.delete_message_nodes(tid, ids)
        return True
    except Exception as e:
        print(f"[DB] Error deleting messages: {e}")
        return False


def delete_contact(phone_number: str, tenant_id: str = "default"):
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        clean = str(phone_number).replace("+", "").strip()
        conn.execute(
            "DELETE FROM messages WHERE tenant_id = ? AND (phone_number = ? OR phone_number = ? OR REPLACE(phone_number, '+', '') = ?)",
            (tid, phone_number, f"+{clean}", clean),
        )
        conn.execute(
            "DELETE FROM bookings WHERE tenant_id = ? AND (phone_number = ? OR phone_number = ? OR REPLACE(phone_number, '+', '') = ?)",
            (tid, phone_number, f"+{clean}", clean),
        )
        conn.execute(
            "DELETE FROM contact_settings WHERE tenant_id = ? AND (phone_number = ? OR phone_number = ? OR REPLACE(phone_number, '+', '') = ?)",
            (tid, phone_number, f"+{clean}", clean),
        )
        norm_key = normalize_phone_key(phone_number)
        conn.execute(
            "DELETE FROM customer_profiles WHERE tenant_id = ? AND (phone_number = ? OR REPLACE(phone_number, '+', '') = ? OR phone_number = ?)",
            (tid, phone_number, clean, norm_key),
        )
        conn.commit()
        conn.close()
        neo = _get_neo4j()
        if neo:
            neo.delete_conversation_nodes(tid, phone_number)
        return True
    except Exception as e:
        print(f"[DB] Error deleting contact: {e}")
        return False


# ==================== LEADS MANAGEMENT ====================

def add_or_update_lead(phone_number: str, name: str = "Lead", source: str = "Manual Import", status: str = "New", notes: str = "", tenant_id: str = "default") -> int:
    """Insert a new lead or update an existing lead by phone number within tenant."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        cursor = conn.cursor()
        clean_phone = "".join(c for c in phone_number if c.isdigit())
        if not clean_phone:
            conn.close()
            return 0

        cursor.execute(
            """
            INSERT INTO leads (tenant_id, phone_number, name, source, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, phone_number) DO UPDATE SET
                name = CASE WHEN excluded.name != 'Lead' AND excluded.name != '' THEN excluded.name ELSE leads.name END,
                source = CASE WHEN excluded.source != '' THEN excluded.source ELSE leads.source END,
                notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE leads.notes END
            """,
            (tid, clean_phone, name or "Lead", source or "Manual Import", status or "New", notes or ""),
        )

        lead_id = cursor.lastrowid
        conn.commit()
        row = cursor.execute(
            "SELECT * FROM leads WHERE tenant_id = ? AND phone_number = ?",
            (tid, clean_phone),
        ).fetchone()
        conn.close()
        if row:
            neo = _get_neo4j()
            if neo:
                neo.save_lead_node(dict(row))
        return (row["id"] if row else lead_id) or 1
    except Exception as e:
        print(f"[DB] Error adding lead: {e}")
        return 0


def record_lead_messaged(phone_number: str, status: str = "Contacted", tenant_id: str = "default"):
    """Update last messaged timestamp and status for a lead."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        clean_phone = "".join(c for c in phone_number if c.isdigit())
        conn.execute(
            """
            UPDATE leads
            SET last_messaged_at = CURRENT_TIMESTAMP,
                status = ?
            WHERE tenant_id = ? AND phone_number = ?
            """,
            (status, tid, clean_phone),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE tenant_id = ? AND phone_number = ?", (tid, clean_phone)).fetchone()
        conn.close()
        if row:
            neo = _get_neo4j()
            if neo:
                neo.save_lead_node(dict(row))
    except Exception as e:
        print(f"[DB] Error recording lead messaged: {e}")


def get_leads(tenant_id: str = "default") -> list:
    """Retrieve all leads for a tenant ordered by newest first."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        rows = [dict(r) for r in conn.execute("SELECT * FROM leads WHERE tenant_id = ? ORDER BY id DESC", (tid,)).fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"[DB] Error fetching leads: {e}")
        return []


def delete_lead(lead_id: int, tenant_id: str = "default") -> bool:
    """Delete a lead by ID within tenant."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        conn.execute("DELETE FROM leads WHERE id = ? AND tenant_id = ?", (int(lead_id), tid))
        conn.commit()
        conn.close()
        neo = _get_neo4j()
        if neo:
            neo.delete_lead_node(tid, lead_id)
        return True
    except Exception as e:
        print(f"[DB] Error deleting lead: {e}")
        return False


def update_lead_status(lead_id: int, status: str, tenant_id: str = "default") -> bool:
    """Update the status of a lead."""
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        conn.execute("UPDATE leads SET status = ? WHERE id = ? AND tenant_id = ?", (status, int(lead_id), tid))
        conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE id = ? AND tenant_id = ?", (int(lead_id), tid)).fetchone()
        conn.close()
        if row:
            neo = _get_neo4j()
            if neo:
                neo.save_lead_node(dict(row))
        return True
    except Exception as e:
        print(f"[DB] Error updating lead status: {e}")
        return False


# ==================== CUSTOMER & BUSINESS ECOSYSTEM PROFILES ====================

_PROFILE_PLACEHOLDERS = {
    "lead", "customer", "user", "unknown", "business", "business lead",
    "valued business", "your area", "not specified", "n/a", "na", "none",
    "null", "there", "unnamed"
}


def normalize_phone_key(phone_number: str) -> str:
    """Normalize phone number into canonical digits (prepending 91 for 10-digit Indian mobiles)."""
    digits = re.sub(r"\D", "", str(phone_number or ""))
    if not digits:
        return ""
    if digits.startswith("00") and 12 <= len(digits) <= 17:
        digits = digits[2:]
    if len(digits) == 13 and digits.startswith("091") and digits[3] in "6789":
        digits = digits[1:]
    elif len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        digits = "91" + digits[1:]
    elif len(digits) == 10:
        digits = "91" + digits
    return digits


def _is_meaningful_profile_val(val: str, field: str = "") -> bool:
    """Return True only if value carries real domain/contact data rather than a generic placeholder."""
    s = str(val or "").strip()
    if not s:
        return False
    low = s.lower()
    if low in _PROFILE_PLACEHOLDERS:
        return False
    if re.match(r"^(lead|business|unnamed lead|contact)\s*#?\d+$", low):
        return False
    if field in ("contact_name", "business_name") and s.isdigit():
        return False
    return True


def _merge_tag_lists(existing_val: str, new_val: str) -> str:
    """Merge comma-separated ecosystem/goal items preserving order without duplicates."""
    seen = {}
    for chunk in (existing_val, new_val):
        for part in str(chunk or "").split(","):
            clean = part.strip()
            if clean and clean.lower() not in seen:
                seen[clean.lower()] = clean
    return ", ".join(seen.values())


def get_customer_profile(phone_number: str, tenant_id: str = "default") -> dict:
    """Fetch stored customer & business ecosystem profile for this tenant."""
    tid = str(tenant_id or "default").strip() or "default"
    key = normalize_phone_key(phone_number)
    raw_clean = str(phone_number or "").replace("+", "").strip()
    profile = {
        "tenant_id": tid,
        "phone_number": key or raw_clean,
        "contact_name": "",
        "business_name": "",
        "business_category": "",
        "area": "",
        "has_website": "",
        "website_url": "",
        "existing_ecosystem": "",
        "pain_points": "",
        "goals": "",
        "data_source": "",
        "updated_at": "",
        "created_at": "",
    }
    if not key and not raw_clean:
        profile["has_business_name"] = False
        profile["has_business_category"] = False
        profile["has_enough_business_context"] = False
        profile["missing_fields"] = ["business_name", "business_category", "has_website", "existing_ecosystem"]
        return profile

    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()

        row = cursor.execute(
            """
            SELECT * FROM customer_profiles
            WHERE tenant_id = ?
              AND (phone_number = ? OR REPLACE(phone_number, '+', '') = ? OR REPLACE(phone_number, '+', '') = ?)
            LIMIT 1
            """,
            (tid, key, key, raw_clean),
        ).fetchone()
        if row:
            for col in (
                "contact_name", "business_name", "business_category", "area",
                "has_website", "website_url", "existing_ecosystem",
                "pain_points", "goals", "data_source", "updated_at", "created_at"
            ):
                if row[col]:
                    profile[col] = str(row[col]).strip()

        lead_row = cursor.execute(
            """
            SELECT name, source, notes FROM leads
            WHERE tenant_id = ?
              AND (phone_number = ? OR REPLACE(phone_number, '+', '') = ? OR REPLACE(phone_number, '+', '') = ?)
            LIMIT 1
            """,
            (tid, key, key, raw_clean),
        ).fetchone()
        if lead_row:
            lead_name = str(lead_row["name"] or "").strip()
            lead_source = str(lead_row["source"] or "").lower()
            lead_notes = str(lead_row["notes"] or "").strip()
            if _is_meaningful_profile_val(lead_name, "business_name"):
                if not profile["business_name"] and ("campaign" in lead_source or "csv" in lead_source or "•" in lead_notes):
                    profile["business_name"] = lead_name
                elif not profile["contact_name"]:
                    profile["contact_name"] = lead_name
            if "•" in lead_notes:
                parts = [p.strip() for p in lead_notes.split("•")]
                if len(parts) >= 1 and not profile["business_category"] and _is_meaningful_profile_val(parts[0], "business_category"):
                    profile["business_category"] = parts[0]
                if len(parts) >= 2 and not profile["area"] and _is_meaningful_profile_val(parts[1], "area"):
                    profile["area"] = parts[1]

        if not _is_meaningful_profile_val(profile["contact_name"], "contact_name"):
            msg_row = cursor.execute(
                """
                SELECT sender_name FROM messages
                WHERE tenant_id = ?
                  AND (REPLACE(phone_number, '+', '') = ? OR REPLACE(phone_number, '+', '') = ?)
                  AND direction = 'inbound'
                ORDER BY id DESC LIMIT 1
                """,
                (tid, key, raw_clean),
            ).fetchone()
            if msg_row and _is_meaningful_profile_val(msg_row["sender_name"], "contact_name"):
                profile["contact_name"] = str(msg_row["sender_name"]).strip()

        conn.close()
    except Exception as e:
        print(f"[DB] Error fetching customer profile: {e}")

    has_bname = _is_meaningful_profile_val(profile["business_name"], "business_name")
    has_bcat = _is_meaningful_profile_val(profile["business_category"], "business_category")
    has_web = _is_meaningful_profile_val(profile["has_website"], "has_website") or bool(profile["website_url"])
    has_eco = _is_meaningful_profile_val(profile["existing_ecosystem"], "existing_ecosystem")

    # Fallback: If local SQLite profile is mostly empty, try fetching from Supabase cloud
    if not has_bname and not has_bcat:
        try:
            store = _get_cloud_store()
            if store:
                cloud_prof_key = f"{tid}:{key or raw_clean}"
                cloud_rows = store._select(
                    "wa_customer_profiles",
                    params={"profile_key": f"eq.{cloud_prof_key}", "limit": 1},
                )
                if cloud_rows:
                    cp = cloud_rows[0]
                    for col in (
                        "contact_name", "business_name", "business_category", "area",
                        "has_website", "website_url", "existing_ecosystem",
                        "pain_points", "goals", "data_source",
                    ):
                        cloud_val = str(cp.get(col) or "").strip()
                        if cloud_val and not profile.get(col):
                            profile[col] = cloud_val
                    # Re-evaluate after cloud hydration
                    has_bname = _is_meaningful_profile_val(profile["business_name"], "business_name")
                    has_bcat = _is_meaningful_profile_val(profile["business_category"], "business_category")
                    has_web = _is_meaningful_profile_val(profile["has_website"], "has_website") or bool(profile["website_url"])
                    has_eco = _is_meaningful_profile_val(profile["existing_ecosystem"], "existing_ecosystem")
        except Exception as cloud_err:
            print(f"[DB] Supabase profile fallback warning: {cloud_err}")

    missing = []
    if not has_bname:
        missing.append("business_name")
    if not has_bcat:
        missing.append("business_category")
    if not has_web:
        missing.append("has_website")
    if not has_eco:
        missing.append("existing_ecosystem")

    profile["has_business_name"] = has_bname
    profile["has_business_category"] = has_bcat
    profile["has_enough_business_context"] = bool(has_bname or has_bcat)
    profile["missing_fields"] = missing
    return profile


def upsert_customer_profile(phone_number: str, overwrite_existing: bool = True, tenant_id: str = "default", **fields) -> dict:
    """Create or merge meaningful business & ecosystem facts for a phone number within a tenant."""
    tid = str(tenant_id or "default").strip() or "default"
    key = normalize_phone_key(phone_number)
    if not key:
        return {}

    allowed_cols = (
        "contact_name", "business_name", "business_category", "area",
        "has_website", "website_url", "existing_ecosystem",
        "pain_points", "goals", "data_source"
    )
    list_cols = {"existing_ecosystem", "pain_points", "goals"}

    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()

        existing = cursor.execute(
            "SELECT * FROM customer_profiles WHERE tenant_id = ? AND phone_number = ?",
            (tid, key),
        ).fetchone()
        merged = {col: (str(existing[col] or "").strip() if existing and existing[col] else "") for col in allowed_cols}

        changed = existing is None
        for col in allowed_cols:
            if col not in fields:
                continue
            new_val = str(fields.get(col) or "").strip()
            if not _is_meaningful_profile_val(new_val, col):
                continue
            if col in list_cols:
                combined = _merge_tag_lists(merged[col], new_val)
                if combined != merged[col]:
                    merged[col] = combined
                    changed = True
            else:
                if overwrite_existing or not merged[col]:
                    if new_val != merged[col]:
                        merged[col] = new_val
                        changed = True

        if changed:
            cursor.execute(
                """
                INSERT INTO customer_profiles (
                    tenant_id, phone_number, contact_name, business_name, business_category, area,
                    has_website, website_url, existing_ecosystem, pain_points, goals, data_source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, phone_number) DO UPDATE SET
                    contact_name = excluded.contact_name,
                    business_name = excluded.business_name,
                    business_category = excluded.business_category,
                    area = excluded.area,
                    has_website = excluded.has_website,
                    website_url = excluded.website_url,
                    existing_ecosystem = excluded.existing_ecosystem,
                    pain_points = excluded.pain_points,
                    goals = excluded.goals,
                    data_source = CASE WHEN excluded.data_source != '' THEN excluded.data_source ELSE customer_profiles.data_source END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tid, key,
                    merged["contact_name"], merged["business_name"], merged["business_category"],
                    merged["area"], merged["has_website"], merged["website_url"],
                    merged["existing_ecosystem"], merged["pain_points"], merged["goals"],
                    merged["data_source"],
                ),
            )

            best_name = merged["business_name"] or merged["contact_name"]
            if _is_meaningful_profile_val(best_name, "business_name"):
                cursor.execute(
                    """
                    UPDATE leads
                    SET name = ?
                    WHERE tenant_id = ? AND REPLACE(phone_number, '+', '') = ?
                      AND (name IS NULL OR TRIM(name) = '' OR LOWER(TRIM(name)) = 'lead')
                    """,
                    (best_name, tid, key),
                )

            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Error upserting customer profile: {e}")

    full_prof = get_customer_profile(key, tenant_id=tid)
    neo = _get_neo4j()
    if neo:
        import threading
        threading.Thread(target=neo.upsert_customer_profile_node, args=(tid, full_prof), daemon=True).start()
    return full_prof


# ==================== RELIABILITY, DEDUP, STATE, AUDIT & DLQ ====================

def claim_webhook_event(tenant_id: str, event_id: str, phone_number: str = "") -> bool:
    """
    Atomically claim a webhook message/event ID for idempotent processing.
    Returns True if newly claimed, False if already processed (duplicate retry).
    """
    eid = str(event_id or "").strip()
    if not eid:
        return True
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO processed_events (tenant_id, event_id, phone_number) VALUES (?, ?, ?)",
        (tid, eid, str(phone_number or "")),
    )
    claimed = cur.rowcount > 0
    conn.commit()
    conn.close()
    if not claimed:
        return False

    store = _get_cloud_store()
    if store and hasattr(store, "has_processed_event") and store.has_processed_event(tid, eid):
        return False
    if store and hasattr(store, "save_processed_event"):
        store.save_processed_event({
            "tenant_id": tid,
            "event_id": eid,
            "phone_number": str(phone_number or ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return True


def get_conversation_state(tenant_id: str, phone_number: str) -> dict:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    norm = normalize_phone_key(phone_number) or str(phone_number or "").replace("+", "").strip()
    if not norm:
        return {"tenant_id": tid, "phone_number": "", "stage": "idle", "pending_action": None}
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM conversation_state WHERE tenant_id = ? AND phone_number = ?",
        (tid, norm),
    ).fetchone()
    conn.close()
    if not row:
        return {"tenant_id": tid, "phone_number": norm, "stage": "idle", "pending_action": None, "pending_expires_at": "", "last_intent": ""}
    d = dict(row)
    pending = None
    if d.get("pending_action_json"):
        try:
            pending = json.loads(d["pending_action_json"])
        except Exception:
            pending = None
    d["pending_action"] = pending
    return d


def set_conversation_state(
    tenant_id: str,
    phone_number: str,
    stage: str = "idle",
    pending_action: dict = None,
    pending_expires_at: str = "",
    last_intent: str = "",
) -> dict:
    init_db()
    tid = str(tenant_id or "default").strip() or "default"
    norm = normalize_phone_key(phone_number) or str(phone_number or "").replace("+", "").strip()
    if not norm:
        return {}
    now_iso = datetime.now(timezone.utc).isoformat()
    pending_str = json.dumps(pending_action) if pending_action else ""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO conversation_state (tenant_id, phone_number, stage, pending_action_json, pending_expires_at, last_intent, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tenant_id, phone_number) DO UPDATE SET
            stage = excluded.stage,
            pending_action_json = excluded.pending_action_json,
            pending_expires_at = excluded.pending_expires_at,
            last_intent = excluded.last_intent,
            updated_at = excluded.updated_at
        """,
        (tid, norm, str(stage or "idle"), pending_str, str(pending_expires_at or ""), str(last_intent or ""), now_iso),
    )
    conn.commit()
    conn.close()
    store = _get_cloud_store()
    if store and hasattr(store, "upsert_conversation_state"):
        store.upsert_conversation_state({
            "tenant_id": tid,
            "phone_number": norm,
            "stage": str(stage or "idle"),
            "pending_action_json": pending_str,
            "pending_expires_at": str(pending_expires_at or ""),
            "last_intent": str(last_intent or ""),
            "updated_at": now_iso,
        })
    return get_conversation_state(tid, norm)


def clear_conversation_state(tenant_id: str, phone_number: str) -> bool:
    set_conversation_state(tenant_id, phone_number, stage="idle", pending_action=None, pending_expires_at="", last_intent="cleared")
    return True


def log_action_audit(
    tenant_id: str,
    actor: str,
    action_name: str,
    status: str,
    risk_level: str = "low",
    phone_number: str = "",
    details: dict = None,
) -> int:
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        details_str = json.dumps(details or {})[:2000]
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO action_audit (tenant_id, actor, phone_number, action_name, status, risk_level, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tid, str(actor or ""), str(phone_number or ""), str(action_name), str(status), str(risk_level), details_str),
        )
        aid = cur.lastrowid
        conn.commit()
        row = cur.execute("SELECT * FROM action_audit WHERE id = ?", (aid,)).fetchone()
        conn.close()
        store = _get_cloud_store()
        if row and store and hasattr(store, "save_action_audit"):
            store.save_action_audit(dict(row))
        return aid or 0
    except Exception:
        return 0


def get_action_audits(tenant_id: str = "default", limit: int = 50) -> list:
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM action_audit WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
            (tid, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def save_dead_letter_job(
    tenant_id: str,
    event_id: str,
    phone_number: str,
    payload: dict,
    error_message: str,
    attempts: int = 3,
) -> int:
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        payload_str = json.dumps(payload or {})[:4000]
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dead_letter_jobs (tenant_id, event_id, phone_number, payload_json, error_message, attempts, status)
            VALUES (?, ?, ?, ?, ?, ?, 'failed')
            """,
            (tid, str(event_id or ""), str(phone_number or ""), payload_str, str(error_message or "")[:1000], int(attempts)),
        )
        jid = cur.lastrowid
        conn.commit()
        row = cur.execute("SELECT * FROM dead_letter_jobs WHERE id = ?", (jid,)).fetchone()
        conn.close()
        store = _get_cloud_store()
        if row and store and hasattr(store, "save_dead_letter_job"):
            store.save_dead_letter_job(dict(row))
        return jid or 0
    except Exception:
        return 0


def get_dead_letter_jobs(tenant_id: str = "default", limit: int = 30) -> list:
    try:
        init_db()
        tid = str(tenant_id or "default").strip() or "default"
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM dead_letter_jobs WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
            (tid, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
