import os
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
                SELECT * FROM messages 
                WHERE phone_number = ? 
                   OR phone_number = ? 
                   OR REPLACE(phone_number, '+', '') = ?
                ORDER BY created_at ASC, id ASC 
                LIMIT ?
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

