import os
import re
import sqlite3
import json
import time
from datetime import datetime, timedelta, timezone

# Database path
DB_DIR = os.path.dirname(os.path.abspath(__file__))
if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/whatsapp_messages.db"
else:
    DB_PATH = os.path.join(os.path.dirname(DB_DIR), "whatsapp_messages.db")

_DB_INITIALIZED = False

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except Exception:
        pass
    return conn

def init_db(force: bool = False):
    """Initialize database tables for messages, bookings, templates, and contact settings."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED and not force:
        return
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Messages Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                sender_name TEXT DEFAULT 'User',
                message TEXT NOT NULL,
                direction TEXT NOT NULL, -- 'inbound' or 'outbound'
                channel TEXT NOT NULL DEFAULT 'meta_whatsapp', -- 'meta_whatsapp', 'twilio', 'simulator', 'manual_admin'
                status TEXT DEFAULT 'received', -- 'received', 'sent', 'failed'
                raw_payload TEXT,
                ai_model TEXT,
                latency_ms REAL DEFAULT 0,
                media_type TEXT, -- 'image', 'document', 'audio', 'video'
                media_url TEXT,
                media_filename TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safe schema migrations for media support
        for col_def in ["media_type TEXT", "media_url TEXT", "media_filename TEXT"]:
            try:
                cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_def}")
            except Exception:
                pass
        
        # Bookings & Support Requests Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL,
                customer_name TEXT DEFAULT 'Customer',
                service_requested TEXT DEFAULT 'Customer Support / Appointment',
                booking_date_time TEXT DEFAULT 'Pending Schedule',
                status TEXT DEFAULT 'pending', -- 'confirmed', 'pending', 'cancelled', 'completed'
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Message Templates Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT DEFAULT 'General',
                content TEXT NOT NULL,
                shortcut TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Contact Settings (Bot enabled / disabled per user)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_settings (
                phone_number TEXT PRIMARY KEY,
                bot_enabled INTEGER DEFAULT 1,
                assigned_agent TEXT DEFAULT 'Support Team',
                tags TEXT DEFAULT 'Customer',
                notes TEXT DEFAULT ''
            )
        """)
        
        # Webhook Logs Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                payload TEXT,
                status_code INTEGER DEFAULT 200,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Leads & CRM Prospects Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL UNIQUE,
                name TEXT DEFAULT 'Lead',
                source TEXT DEFAULT 'Manual Import',
                status TEXT DEFAULT 'New', -- 'New', 'Contacted', 'Interested', 'Converted', 'Closed'
                notes TEXT DEFAULT '',
                last_messaged_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Persistent Customer & Business Ecosystem Profiles
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customer_profiles (
                phone_number TEXT PRIMARY KEY,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed default support templates if empty
        cursor.execute("SELECT COUNT(*) as count FROM templates")
        if cursor.fetchone()["count"] == 0:
            default_templates = [
                ("👋 Welcome Greeting", "Greeting", "Hello {{name}}! 👋 Thank you for reaching out to Growhaz (https://www.growhaz.in/). How can we assist you with our cybersecurity, app development, or blockchain solutions today?", "/welcome"),
                ("🛡️ Security Vulnerability Scan", "Security", "Hi {{name}}, you can run automated vulnerability scans (Alpha G1/G5) on your website in under 5 minutes. Start your audit here: https://www.growhaz.in/security-tools", "/security"),
                ("📱 Appify & Web Development", "Development", "Hi {{name}}, we build high-speed static websites, dynamic web apps, and convert websites to native Android/iOS mobile apps. Check our portfolio: https://www.growhaz.in/development", "/development"),
                ("🔗 Blockchain Verification", "Trust", "Hi {{name}}, you can instantly verify certificates and documents on our blockchain ledger here: https://www.growhaz.in/verify", "/verify"),
                ("💰 Pricing & Packages", "Pricing", "Hi {{name}}, here is our transparent pricing guide:\n• AlphaG1 Scan: ₹1,999 | AlphaG5: ₹4,999\n• Static Website: ₹20,000 | Dynamic: ₹60,000+\n• Details: https://www.growhaz.in/pricing", "/pricing"),
                ("📅 Consultation Booking", "Bookings", "Hi {{name}}, your consultation with Growhaz is registered for {{service}} on {{date_time}}! Need to reschedule? Visit https://www.growhaz.in/contact", "/confirm"),
                ("👤 Human Handover", "Handover", "A specialist from the Growhaz engineering team has joined this chat. One moment please while I connect you.", "/agent"),
                ("⭐ Feedback & CSAT Survey", "Feedback", "Hi {{name}}, how was your Growhaz experience today? Please rate us from 1 (Poor) to 5 (Excellent) ⭐. Visit us at https://www.growhaz.in/ . Thank you!", "/feedback")
            ]
            cursor.executemany("INSERT INTO templates (title, category, content, shortcut) VALUES (?, ?, ?, ?)", default_templates)
        
        # Ensure any stale messages containing old company branding are wiped
        cursor.execute("DELETE FROM messages WHERE message LIKE '%printingtask%' OR sender_name LIKE '%printingtask%' OR phone_number IN ('918103976748', '917803872080')")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phone ON messages(phone_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phone_created ON messages(phone_number, created_at DESC)")
        
        conn.commit()
        conn.close()
        _DB_INITIALIZED = True
    except Exception as e:
        print(f"[DB] Error initializing database: {e}")

def save_message(phone_number: str, message: str, direction: str = "inbound", 
                 sender_name: str = "User", channel: str = "meta_whatsapp", 
                 status: str = "received", raw_payload: dict = None, 
                 ai_model: str = None, latency_ms: float = 0.0,
                 media_type: str = None, media_url: str = None, media_filename: str = None):
    """Save an incoming or outgoing message to the database and track booking intent."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        
        payload_str = json.dumps(raw_payload) if isinstance(raw_payload, (dict, list)) else (raw_payload or "")
        
        cursor.execute("""
            INSERT INTO messages (phone_number, sender_name, message, direction, channel, status, raw_payload, ai_model, latency_ms, media_type, media_url, media_filename)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (phone_number, sender_name, message, direction, channel, status, payload_str, ai_model, latency_ms, media_type, media_url, media_filename))
        
        msg_id = cursor.lastrowid

        # Automatic Support / Booking Intent Detection for Inbound Messages
        if direction == "inbound" and message:
            detect_and_record_booking(cursor, phone_number, sender_name, message)

        conn.commit()
        conn.close()
        return msg_id
    except Exception as e:
        print(f"[DB] Error saving message: {e}")
        return None

def detect_and_record_booking(cursor, phone_number: str, customer_name: str, message: str):
    """Detect if incoming message has booking or order intent."""
    msg_lower = message.lower()
    booking_keywords = ["book", "booking", "appointment", "schedule", "reserve", "slot", "meeting", "consultation", "order", "scan", "security", "app", "appify", "verify"]
    
    if any(k in msg_lower for k in booking_keywords):
        service = "Growhaz Service Consultation"
        if "security" in msg_lower or "scan" in msg_lower: service = "Website Security Audit (Alpha G5)"
        elif "app" in msg_lower or "appify" in msg_lower: service = "Appify Website to Mobile App"
        elif "blockchain" in msg_lower or "verify" in msg_lower: service = "Blockchain Document Verification"
        elif "web" in msg_lower or "develop" in msg_lower: service = "Secure Web Development"
        elif "consult" in msg_lower: service = "Growhaz Technical Consultation"
        elif "order" in msg_lower or "book" in msg_lower: service = "Growhaz Service Order"

        cursor.execute("""
            SELECT id FROM bookings 
            WHERE phone_number = ? AND created_at >= datetime('now', '-2 hours')
            LIMIT 1
        """, (phone_number,))
        existing = cursor.fetchone()
        
        if not existing:
            cursor.execute("""
                INSERT INTO bookings (phone_number, customer_name, service_requested, booking_date_time, status, notes)
                VALUES (?, ?, ?, ?, 'pending', ?)
            """, (phone_number, customer_name or "WhatsApp Customer", service, "Requested via WhatsApp", message))

def is_bot_enabled_for_contact(phone_number: str) -> bool:
    """Check if automated bot is enabled for this customer phone number."""
    if not phone_number:
        return True
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        clean = str(phone_number).replace("+", "").strip()
        cursor.execute("""
            SELECT bot_enabled FROM contact_settings 
            WHERE phone_number = ? 
               OR phone_number = ? 
               OR REPLACE(phone_number, '+', '') = ?
            LIMIT 1
        """, (phone_number, f"+{clean}", clean))
        row = cursor.fetchone()
        conn.close()
        if row is not None:
            return bool(row["bot_enabled"])
        return True # Default enabled
    except Exception as e:
        print(f"[DB] Error checking bot enabled: {e}")
        return True

def set_bot_enabled_for_contact(phone_number: str, enabled: bool):
    """Toggle automated bot for this customer."""
    if not phone_number:
        return False
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        clean = str(phone_number).replace("+", "").strip()
        val = 1 if enabled else 0
        
        # Save under raw, clean, and plus versions so lookup always hits
        keys = set([str(phone_number).strip(), clean, f"+{clean}"])
        for p in keys:
            if p:
                cursor.execute("""
                    INSERT INTO contact_settings (phone_number, bot_enabled)
                    VALUES (?, ?)
                    ON CONFLICT(phone_number) DO UPDATE SET bot_enabled = excluded.bot_enabled
                """, (p, val))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] Error setting bot enabled: {e}")
        return False

def get_conversations():
    """Get list of distinct contact conversations with their latest message and timestamp."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT 
                m1.phone_number,
                COALESCE(
                    (SELECT m_in.sender_name FROM messages m_in WHERE REPLACE(m_in.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') AND m_in.direction = 'inbound' ORDER BY m_in.id DESC LIMIT 1),
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
                (SELECT m_in.created_at FROM messages m_in WHERE REPLACE(m_in.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') AND m_in.direction = 'inbound' ORDER BY m_in.id DESC LIMIT 1) as last_inbound_time,
                (SELECT COUNT(*) FROM messages m2 WHERE REPLACE(m2.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '')) as total_messages,
                (SELECT COUNT(*) FROM messages m3 WHERE REPLACE(m3.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') AND m3.direction = 'inbound') as inbound_count,
                COALESCE((SELECT cs.bot_enabled FROM contact_settings cs WHERE REPLACE(cs.phone_number, '+', '') = REPLACE(m1.phone_number, '+', '') LIMIT 1), 1) as bot_enabled
            FROM messages m1
            WHERE m1.id IN (
                SELECT MAX(id) FROM messages GROUP BY REPLACE(phone_number, '+', '')
            )
            ORDER BY m1.created_at DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        import datetime
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        conversations = []
        for row in rows:
            d = dict(row)
            last_inbound_str = d.get("last_inbound_time")
            free_window_active = False
            remaining_seconds = 0
            if last_inbound_str:
                try:
                    clean_ts = str(last_inbound_str).split(".")[0].strip()
                    inbound_dt = datetime.datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
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

def get_messages(phone_number: str = None, limit: int = 500):
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        
        if phone_number:
            clean = str(phone_number).replace("+", "").strip()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM messages 
                    WHERE phone_number = ? 
                       OR phone_number = ? 
                       OR REPLACE(phone_number, '+', '') = ?
                    ORDER BY created_at DESC, id DESC 
                    LIMIT ?
                )
                ORDER BY created_at ASC, id ASC
            """, (phone_number, f"+{clean}", clean, limit))
        else:
            cursor.execute("""
                SELECT * FROM messages 
                ORDER BY created_at DESC, id DESC 
                LIMIT ?
            """, (limit,))
            
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error getting messages: {e}")
        return []

def get_templates():
    """Get all response templates."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM templates ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error getting templates: {e}")
        return []

def save_template(title: str, category: str, content: str, shortcut: str = ""):
    """Save a new custom message template."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO templates (title, category, content, shortcut) VALUES (?, ?, ?, ?)", (title, category, content, shortcut))
        t_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return t_id
    except Exception as e:
        print(f"[DB] Error saving template: {e}")
        return None

def delete_template(template_id: int):
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        return False

def get_bookings():
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bookings ORDER BY created_at DESC LIMIT 100")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        return []

def update_booking_status(booking_id: int, status: str):
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def add_manual_booking(phone_number: str, customer_name: str, service: str, date_time: str, status: str = "confirmed", notes: str = ""):
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bookings (phone_number, customer_name, service_requested, booking_date_time, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (phone_number, customer_name, service, date_time, status, notes))
        conn.commit()
        booking_id = cursor.lastrowid
        conn.close()
        return booking_id
    except Exception:
        return None

def get_stats():
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) as total FROM messages")
        total_messages = cursor.fetchone()["total"]
        
        cursor.execute("SELECT COUNT(DISTINCT phone_number) as contacts FROM messages")
        total_contacts = cursor.fetchone()["contacts"]
        
        cursor.execute("SELECT COUNT(*) as inbound FROM messages WHERE direction = 'inbound'")
        inbound_messages = cursor.fetchone()["inbound"]
        
        cursor.execute("SELECT COUNT(*) as outbound FROM messages WHERE direction = 'outbound'")
        outbound_messages = cursor.fetchone()["outbound"]
        
        cursor.execute("SELECT AVG(latency_ms) as avg_latency FROM messages WHERE latency_ms > 0")
        avg_row = cursor.fetchone()
        avg_latency = round(avg_row["avg_latency"] or 0, 2) if avg_row else 0
        
        cursor.execute("SELECT COUNT(*) as count FROM webhook_logs")
        total_webhooks = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM bookings")
        total_bookings = cursor.fetchone()["count"]
        
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        cursor.execute("SELECT COUNT(*) as today_total FROM messages WHERE created_at LIKE ?", (f"{today_str}%",))
        today_messages = cursor.fetchone()["today_total"]
        
        # Count contacts with active 24h free promotional window
        cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            SELECT COUNT(DISTINCT REPLACE(phone_number, '+', '')) as active_window_count
            FROM messages
            WHERE direction = 'inbound' AND created_at >= ?
        """, (cutoff_24h,))
        active_free_windows = cursor.fetchone()["active_window_count"] or 0

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
            "active_free_windows": active_free_windows
        }
    except Exception as e:
        return {
            "total_messages": 0, "total_contacts": 0, "inbound_messages": 0, "outbound_messages": 0,
            "avg_latency_ms": 0, "total_webhooks": 0, "total_bookings": 0, "today_messages": 0
        }

def save_webhook_log(endpoint: str, method: str, payload: any = None, status_code: int = 200, ip_address: str = ""):
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        payload_str = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload or "")
        cursor.execute("INSERT INTO webhook_logs (endpoint, method, payload, status_code, ip_address) VALUES (?, ?, ?, ?, ?)", 
                       (endpoint, method, payload_str, status_code, ip_address))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_webhook_logs(limit: int = 50):
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM webhook_logs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []

def clear_data():
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages")
        cursor.execute("DELETE FROM bookings")
        cursor.execute("DELETE FROM webhook_logs")
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def delete_messages(message_ids: list):
    """Delete one or multiple messages by their IDs."""
    if not message_ids:
        return False
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        ids = [int(i) for i in message_ids if str(i).isdigit()]
        if not ids:
            return False
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", ids)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] Error deleting messages: {e}")
        return False

def delete_contact(phone_number: str):
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        clean = str(phone_number).replace("+", "").strip()
        cursor.execute("""
            DELETE FROM messages 
            WHERE phone_number = ? 
               OR phone_number = ? 
               OR REPLACE(phone_number, '+', '') = ?
        """, (phone_number, f"+{clean}", clean))
        cursor.execute("""
            DELETE FROM bookings 
            WHERE phone_number = ? 
               OR phone_number = ? 
               OR REPLACE(phone_number, '+', '') = ?
        """, (phone_number, f"+{clean}", clean))
        cursor.execute("""
            DELETE FROM contact_settings 
            WHERE phone_number = ? 
               OR phone_number = ? 
               OR REPLACE(phone_number, '+', '') = ?
        """, (phone_number, f"+{clean}", clean))
        norm_key = normalize_phone_key(phone_number)
        cursor.execute("""
            DELETE FROM customer_profiles
            WHERE phone_number = ?
               OR REPLACE(phone_number, '+', '') = ?
               OR phone_number = ?
        """, (phone_number, clean, norm_key))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] Error deleting contact: {e}")
        return False

# ==================== LEADS MANAGEMENT ====================

def add_or_update_lead(phone_number: str, name: str = "Lead", source: str = "Manual Import", status: str = "New", notes: str = "") -> int:
    """Insert a new lead or update an existing lead by phone number."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        clean_phone = "".join(c for c in phone_number if c.isdigit())
        if not clean_phone:
            conn.close()
            return 0
        
        cursor.execute("""
            INSERT INTO leads (phone_number, name, source, status, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(phone_number) DO UPDATE SET
                name = CASE WHEN excluded.name != 'Lead' AND excluded.name != '' THEN excluded.name ELSE leads.name END,
                source = CASE WHEN excluded.source != '' THEN excluded.source ELSE leads.source END,
                notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE leads.notes END
        """, (clean_phone, name or "Lead", source or "Manual Import", status or "New", notes or ""))
        
        lead_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return lead_id or 1
    except Exception as e:
        print(f"[DB] Error adding lead: {e}")
        return 0

def record_lead_messaged(phone_number: str, status: str = "Contacted"):
    """Update last messaged timestamp and status for a lead."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        clean_phone = "".join(c for c in phone_number if c.isdigit())
        cursor.execute("""
            UPDATE leads 
            SET last_messaged_at = CURRENT_TIMESTAMP,
                status = ?
            WHERE phone_number = ?
        """, (status, clean_phone))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Error recording lead messaged: {e}")

def get_leads() -> list:
    """Retrieve all leads ordered by newest first."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM leads ORDER BY id DESC")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"[DB] Error fetching leads: {e}")
        return []

def delete_lead(lead_id: int) -> bool:
    """Delete a lead by ID."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM leads WHERE id = ?", (int(lead_id),))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] Error deleting lead: {e}")
        return False

def update_lead_status(lead_id: int, status: str) -> bool:
    """Update the status of a lead."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE leads SET status = ? WHERE id = ?", (status, int(lead_id)))
        conn.commit()
        conn.close()
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


def get_customer_profile(phone_number: str) -> dict:
    """Fetch stored customer & business ecosystem profile, enriched with CRM leads & chat metadata."""
    key = normalize_phone_key(phone_number)
    raw_clean = str(phone_number or "").replace("+", "").strip()
    profile = {
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

        cursor.execute("""
            SELECT * FROM customer_profiles
            WHERE phone_number = ?
               OR REPLACE(phone_number, '+', '') = ?
               OR REPLACE(phone_number, '+', '') = ?
            LIMIT 1
        """, (key, key, raw_clean))
        row = cursor.fetchone()
        if row:
            for col in (
                "contact_name", "business_name", "business_category", "area",
                "has_website", "website_url", "existing_ecosystem",
                "pain_points", "goals", "data_source", "updated_at", "created_at"
            ):
                if row[col]:
                    profile[col] = str(row[col]).strip()

        # Enrich from leads table if profile is missing fields
        cursor.execute("""
            SELECT name, source, notes FROM leads
            WHERE phone_number = ?
               OR REPLACE(phone_number, '+', '') = ?
               OR REPLACE(phone_number, '+', '') = ?
            LIMIT 1
        """, (key, key, raw_clean))
        lead_row = cursor.fetchone()
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

        # Enrich contact_name from latest inbound message sender_name
        if not _is_meaningful_profile_val(profile["contact_name"], "contact_name"):
            cursor.execute("""
                SELECT sender_name FROM messages
                WHERE (REPLACE(phone_number, '+', '') = ? OR REPLACE(phone_number, '+', '') = ?)
                  AND direction = 'inbound'
                ORDER BY id DESC LIMIT 1
            """, (key, raw_clean))
            msg_row = cursor.fetchone()
            if msg_row and _is_meaningful_profile_val(msg_row["sender_name"], "contact_name"):
                profile["contact_name"] = str(msg_row["sender_name"]).strip()

        conn.close()
    except Exception as e:
        print(f"[DB] Error fetching customer profile: {e}")

    has_bname = _is_meaningful_profile_val(profile["business_name"], "business_name")
    has_bcat = _is_meaningful_profile_val(profile["business_category"], "business_category")
    has_web = _is_meaningful_profile_val(profile["has_website"], "has_website") or bool(profile["website_url"])
    has_eco = _is_meaningful_profile_val(profile["existing_ecosystem"], "existing_ecosystem")

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


def upsert_customer_profile(phone_number: str, overwrite_existing: bool = True, **fields) -> dict:
    """Create or merge meaningful business & ecosystem facts for a phone number."""
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

        cursor.execute("SELECT * FROM customer_profiles WHERE phone_number = ?", (key,))
        existing = cursor.fetchone()
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
            cursor.execute("""
                INSERT INTO customer_profiles (
                    phone_number, contact_name, business_name, business_category, area,
                    has_website, website_url, existing_ecosystem, pain_points, goals, data_source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(phone_number) DO UPDATE SET
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
            """, (
                key,
                merged["contact_name"], merged["business_name"], merged["business_category"],
                merged["area"], merged["has_website"], merged["website_url"],
                merged["existing_ecosystem"], merged["pain_points"], merged["goals"],
                merged["data_source"]
            ))

            # Keep placeholder leads table row synced with real business/contact name
            best_name = merged["business_name"] or merged["contact_name"]
            if _is_meaningful_profile_val(best_name, "business_name"):
                cursor.execute("""
                    UPDATE leads
                    SET name = ?
                    WHERE REPLACE(phone_number, '+', '') = ?
                      AND (name IS NULL OR TRIM(name) = '' OR LOWER(TRIM(name)) = 'lead')
                """, (best_name, key))

            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Error upserting customer profile: {e}")

    return get_customer_profile(key)


