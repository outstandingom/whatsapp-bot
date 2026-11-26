"""
Neo4j AuraDB Cloud Persistence + Live Temporal DNA Knowledge Graph Store.

1. Persists multi-tenant SaaS records (Tenants, ChatMessages, CustomerProfiles, Templates,
   Leads, Bookings, ContactSettings, BillingWindows, SecurityEvents) in Neo4j AuraDB so
   ephemeral container deploys/pushes on Render NEVER lose old chats or business memory.
2. Maintains a live per-tenant Knowledge Graph of customers, businesses, categories,
   localities, websites, ecosystem tools, inquired services, and conversation episodes.
"""

import os
import re
import json
import hashlib
import logging
import datetime
import threading
from typing import Dict, Any, List, Optional

logger = logging.getLogger("neo4j_store")

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _slug(val: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(val or "").strip().lower()).strip("_")
    return s[:max_len] or "item"


class Neo4jStore:
    """Thread-safe Neo4j AuraDB store with automatic TLS fallback & graceful degradation."""

    def __init__(self):
        self._lock = threading.RLock()
        self._driver = None
        self._active_uri = ""
        self._connected = False
        self._last_error: Optional[str] = None
        self._indexes_created = False
        self._init_driver()

    def _get_config(self) -> tuple[str, str, str, str]:
        uri = os.getenv("NEO4J_URI", "").strip()
        user = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j")).strip()
        password = os.getenv("NEO4J_PASSWORD", "").strip()
        database = os.getenv("NEO4J_DATABASE", "neo4j").strip() or "neo4j"
        return uri, user, password, database

    def _candidate_uris(self, uri: str) -> List[str]:
        candidates = [uri]
        if uri.startswith("neo4j+s://"):
            host = uri[len("neo4j+s://"):]
            candidates.append(f"neo4j+ssc://{host}")
            candidates.append(f"bolt+ssc://{host}")
        elif uri.startswith("bolt+s://"):
            host = uri[len("bolt+s://"):]
            candidates.append(f"bolt+ssc://{host}")
        return candidates

    def _init_driver(self) -> bool:
        with self._lock:
            if not HAS_NEO4J:
                self._connected = False
                self._last_error = "neo4j Python driver is not installed"
                return False

            uri, user, password, database = self._get_config()
            if not uri or not password:
                self._connected = False
                self._last_error = "NEO4J_URI or NEO4J_PASSWORD not configured"
                return False

            for cand_uri in self._candidate_uris(uri):
                drv = None
                try:
                    drv = GraphDatabase.driver(
                        cand_uri,
                        auth=(user, password),
                        connection_timeout=6.0,
                        connection_acquisition_timeout=6.0,
                        max_transaction_retry_time=5.0,
                        max_connection_lifetime=1800,
                    )
                    drv.verify_connectivity()
                    if self._driver and self._driver is not drv:
                        try:
                            self._driver.close()
                        except Exception:
                            pass
                    self._driver = drv
                    self._active_uri = cand_uri
                    self._connected = True
                    self._last_error = None
                    if not self._indexes_created:
                        self._ensure_indexes(database)
                    logger.info(f"[Neo4j] Connected ({cand_uri}, db={database})")
                    return True
                except Exception as e:
                    self._last_error = str(e)
                    if drv:
                        try:
                            drv.close()
                        except Exception:
                            pass
            self._connected = False
            return False

    def _ensure_driver(self) -> bool:
        if self._connected and self._driver:
            return True
        return self._init_driver()

    def _ensure_indexes(self, database: str):
        statements = [
            "CREATE INDEX IF NOT EXISTS FOR (t:Tenant) ON (t.id)",
            "CREATE INDEX IF NOT EXISTS FOR (m:ChatMessage) ON (m.key)",
            "CREATE INDEX IF NOT EXISTS FOR (m:ChatMessage) ON (m.tenant_id)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Customer) ON (c.key)",
            "CREATE INDEX IF NOT EXISTS FOR (c:Customer) ON (c.tenant_id)",
            "CREATE INDEX IF NOT EXISTS FOR (b:Business) ON (b.key)",
            "CREATE INDEX IF NOT EXISTS FOR (tpl:Template) ON (tpl.key)",
            "CREATE INDEX IF NOT EXISTS FOR (l:Lead) ON (l.key)",
            "CREATE INDEX IF NOT EXISTS FOR (bk:Booking) ON (bk.key)",
            "CREATE INDEX IF NOT EXISTS FOR (cs:ContactSetting) ON (cs.key)",
            "CREATE INDEX IF NOT EXISTS FOR (bw:BillingWindow) ON (bw.key)",
            "CREATE INDEX IF NOT EXISTS FOR (ep:Episode) ON (ep.id)",
        ]
        try:
            with self._driver.session(database=database) as s:
                for stmt in statements:
                    try:
                        s.run(stmt)
                    except Exception:
                        pass
            self._indexes_created = True
        except Exception as e:
            logger.debug(f"[Neo4j] Index creation note: {e}")

    def _run_write(self, cypher: str, **params) -> bool:
        if not self._ensure_driver():
            return False
        _, _, _, database = self._get_config()
        try:
            with self._driver.session(database=database) as s:
                s.run(cypher, **params)
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"[Neo4j] Write error: {e}")
            if "defunct" in str(e).lower() or "unavailable" in str(e).lower():
                self._connected = False
            return False

    def _run_read(self, cypher: str, **params) -> List[dict]:
        if not self._ensure_driver():
            return []
        _, _, _, database = self._get_config()
        try:
            with self._driver.session(database=database) as s:
                res = s.run(cypher, **params)
                return [dict(r) for r in res]
        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"[Neo4j] Read error: {e}")
            return []

    def get_status(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        uri, _, password, database = self._get_config()
        configured = bool(HAS_NEO4J and uri and password)
        if configured and not self._connected:
            self._init_driver()

        host_display = uri.split("://")[-1] if uri else "not configured"
        stats: Dict[str, Any] = {
            "configured": configured,
            "connected": self._connected,
            "uri_host": host_display,
            "database": database,
            "error": self._last_error,
            "node_count": 0,
            "relationship_count": 0,
            "tenant_nodes": 0,
            "customer_nodes": 0,
            "business_nodes": 0,
            "message_nodes": 0,
            "mode": "NEO4J_LIVE" if self._connected else "SQLITE_LOCAL_FALLBACK",
        }

        if not self._connected:
            return stats

        rows = self._run_read(
            """
            OPTIONAL MATCH (n)
            WITH count(n) AS total_nodes
            OPTIONAL MATCH ()-[r]->()
            WITH total_nodes, count(r) AS total_rels
            OPTIONAL MATCH (t:Tenant)
            WITH total_nodes, total_rels, count(t) AS tenants
            OPTIONAL MATCH (c:Customer) WHERE $tid IS NULL OR c.tenant_id = $tid
            WITH total_nodes, total_rels, tenants, count(c) AS customers
            OPTIONAL MATCH (b:Business) WHERE $tid IS NULL OR b.tenant_id = $tid
            WITH total_nodes, total_rels, tenants, customers, count(b) AS businesses
            OPTIONAL MATCH (m:ChatMessage) WHERE $tid IS NULL OR m.tenant_id = $tid
            RETURN total_nodes, total_rels, tenants, customers, businesses, count(m) AS messages
            """,
            tid=tenant_id,
        )
        if rows:
            r = rows[0]
            stats.update({
                "node_count": r.get("total_nodes", 0) or 0,
                "relationship_count": r.get("total_rels", 0) or 0,
                "tenant_nodes": r.get("tenants", 0) or 0,
                "customer_nodes": r.get("customers", 0) or 0,
                "business_nodes": r.get("businesses", 0) or 0,
                "message_nodes": r.get("messages", 0) or 0,
            })
        return stats

    # ====================================================================
    # CLOUD PERSISTENCE WRITE-THROUGH (ZERO DATA LOSS ON DEPLOY)
    # ====================================================================

    def upsert_tenant(self, tenant: dict) -> bool:
        tid = str(tenant.get("tenant_id") or "default").strip()
        return self._run_write(
            """
            MERGE (t:Tenant {id: $id})
            SET t.email = $email,
                t.full_name = $full_name,
                t.business_name = $business_name,
                t.custom_system_prompt = $custom_system_prompt,
                t.billing_mode = $billing_mode,
                t.plan_tier = $plan_tier,
                t.plan_quota = $plan_quota,
                t.plan_used = $plan_used,
                t.plan_expires_at = $plan_expires_at,
                t.demo_used = $demo_used,
                t.whatsapp_token = $whatsapp_token,
                t.whatsapp_phone_number_id = $whatsapp_phone_number_id,
                t.whatsapp_verify_token = $whatsapp_verify_token,
                t.deepseek_api_key = $deepseek_api_key,
                t.deepseek_model = $deepseek_model,
                t.groq_api_key = $groq_api_key,
                t.groq_model = $groq_model,
                t.openrouter_api_key = $openrouter_api_key,
                t.openrouter_guard_model = $openrouter_guard_model,
                t.updated_at = $updated_at
            """,
            id=tid,
            email=str(tenant.get("email") or ""),
            full_name=str(tenant.get("full_name") or ""),
            business_name=str(tenant.get("business_name") or ""),
            custom_system_prompt=str(tenant.get("custom_system_prompt") or ""),
            billing_mode=str(tenant.get("billing_mode") or "managed_meta"),
            plan_tier=str(tenant.get("plan_tier") or "payg"),
            plan_quota=int(tenant.get("plan_quota") or 0),
            plan_used=int(tenant.get("plan_used") or 0),
            plan_expires_at=str(tenant.get("plan_expires_at") or ""),
            demo_used=int(tenant.get("demo_used") or 0),
            whatsapp_token=str(tenant.get("whatsapp_token") or ""),
            whatsapp_phone_number_id=str(tenant.get("whatsapp_phone_number_id") or ""),
            whatsapp_verify_token=str(tenant.get("whatsapp_verify_token") or ""),
            deepseek_api_key=str(tenant.get("deepseek_api_key") or ""),
            deepseek_model=str(tenant.get("deepseek_model") or "deepseek-chat"),
            groq_api_key=str(tenant.get("groq_api_key") or ""),
            groq_model=str(tenant.get("groq_model") or "llama-3.3-70b-versatile"),
            openrouter_api_key=str(tenant.get("openrouter_api_key") or ""),
            openrouter_guard_model=str(tenant.get("openrouter_guard_model") or "meta-llama/llama-guard-4-12b"),
            updated_at=_now_iso(),
        )

    def save_message_node(self, msg: dict) -> bool:
        tid = str(msg.get("tenant_id") or "default").strip()
        msg_id = int(msg["id"])
        key = f"{tid}:{msg_id}"
        phone = str(msg.get("phone_number") or "").strip()
        cust_key = f"{tid}:{phone}"
        return self._run_write(
            """
            MERGE (t:Tenant {id: $tid})
            MERGE (c:Customer {key: $cust_key})
            ON CREATE SET c.tenant_id = $tid, c.phone = $phone, c.name = $sender_name, c.created_at = $created_at
            MERGE (t)-[:HAS_CUSTOMER]->(c)
            MERGE (m:ChatMessage {key: $key})
            SET m.id = $id,
                m.tenant_id = $tid,
                m.phone_number = $phone,
                m.sender_name = $sender_name,
                m.message = $message,
                m.direction = $direction,
                m.channel = $channel,
                m.status = $status,
                m.raw_payload = $raw_payload,
                m.ai_model = $ai_model,
                m.latency_ms = $latency_ms,
                m.media_type = $media_type,
                m.media_url = $media_url,
                m.media_filename = $media_filename,
                m.created_at = $created_at
            MERGE (c)-[:HAS_MESSAGE]->(m)
            """,
            key=key,
            id=msg_id,
            tid=tid,
            cust_key=cust_key,
            phone=phone,
            sender_name=str(msg.get("sender_name") or "User"),
            message=str(msg.get("message") or ""),
            direction=str(msg.get("direction") or "inbound"),
            channel=str(msg.get("channel") or "meta_whatsapp"),
            status=str(msg.get("status") or "received"),
            raw_payload=str(msg.get("raw_payload") or "")[:4000],
            ai_model=str(msg.get("ai_model") or ""),
            latency_ms=float(msg.get("latency_ms") or 0.0),
            media_type=str(msg.get("media_type") or ""),
            media_url=str(msg.get("media_url") or ""),
            media_filename=str(msg.get("media_filename") or ""),
            created_at=str(msg.get("created_at") or _now_iso()),
        )

    def delete_message_nodes(self, tenant_id: str, ids: List[int]) -> bool:
        keys = [f"{tenant_id}:{int(i)}" for i in ids if str(i).isdigit()]
        if not keys:
            return True
        return self._run_write(
            "MATCH (m:ChatMessage) WHERE m.key IN $keys DETACH DELETE m",
            keys=keys,
        )

    def delete_conversation_nodes(self, tenant_id: str, phone_number: str) -> bool:
        clean = str(phone_number or "").replace("+", "").strip()
        return self._run_write(
            """
            MATCH (m:ChatMessage)
            WHERE m.tenant_id = $tid AND (m.phone_number = $p1 OR m.phone_number = $p2 OR replace(m.phone_number, '+', '') = $clean)
            DETACH DELETE m
            """,
            tid=tenant_id,
            p1=phone_number,
            p2=f"+{clean}",
            clean=clean,
        )

    def clear_tenant_messages(self, tenant_id: str) -> bool:
        return self._run_write(
            "MATCH (m:ChatMessage {tenant_id: $tid}) DETACH DELETE m",
            tid=tenant_id,
        )

    def upsert_customer_profile_node(self, tenant_id: str, prof: dict) -> bool:
        tid = str(tenant_id or "default").strip()
        phone = str(prof.get("phone_number") or "").strip()
        if not phone:
            return False
        key = f"{tid}:{phone}"
        res = self._run_write(
            """
            MERGE (t:Tenant {id: $tid})
            MERGE (c:Customer {key: $key})
            ON CREATE SET c.tenant_id = $tid, c.phone = $phone
            SET c.name = CASE WHEN $contact_name <> '' THEN $contact_name ELSE coalesce(c.name, $phone) END
            MERGE (t)-[:HAS_CUSTOMER]->(c)
            MERGE (p:CustomerProfile {key: $key})
            SET p.tenant_id = $tid,
                p.phone_number = $phone,
                p.contact_name = $contact_name,
                p.business_name = $business_name,
                p.business_category = $business_category,
                p.area = $area,
                p.has_website = $has_website,
                p.website_url = $website_url,
                p.existing_ecosystem = $existing_ecosystem,
                p.pain_points = $pain_points,
                p.goals = $goals,
                p.data_source = $data_source,
                p.updated_at = $updated_at,
                p.created_at = coalesce(p.created_at, $updated_at)
            MERGE (c)-[:HAS_PROFILE]->(p)
            """,
            tid=tid,
            key=key,
            phone=phone,
            contact_name=str(prof.get("contact_name") or ""),
            business_name=str(prof.get("business_name") or ""),
            business_category=str(prof.get("business_category") or ""),
            area=str(prof.get("area") or ""),
            has_website=str(prof.get("has_website") or ""),
            website_url=str(prof.get("website_url") or ""),
            existing_ecosystem=str(prof.get("existing_ecosystem") or ""),
            pain_points=str(prof.get("pain_points") or ""),
            goals=str(prof.get("goals") or ""),
            data_source=str(prof.get("data_source") or ""),
            updated_at=str(prof.get("updated_at") or _now_iso()),
        )
        # Also mirror entities into the Knowledge Graph
        self.record_customer_knowledge_graph(tenant_id=tid, phone=phone, profile=prof)
        return res

    def save_template_node(self, tpl: dict) -> bool:
        tid = str(tpl.get("tenant_id") or "default")
        tpl_id = int(tpl["id"])
        return self._run_write(
            """
            MERGE (t:Template {key: $key})
            SET t.id = $id, t.tenant_id = $tid, t.title = $title, t.category = $category,
                t.content = $content, t.shortcut = $shortcut, t.created_at = $created_at
            """,
            key=f"{tid}:{tpl_id}",
            id=tpl_id,
            tid=tid,
            title=str(tpl.get("title") or ""),
            category=str(tpl.get("category") or "General"),
            content=str(tpl.get("content") or ""),
            shortcut=str(tpl.get("shortcut") or ""),
            created_at=str(tpl.get("created_at") or _now_iso()),
        )

    def delete_template_node(self, tenant_id: str, tpl_id: int) -> bool:
        return self._run_write(
            "MATCH (t:Template {key: $key}) DETACH DELETE t",
            key=f"{tenant_id}:{int(tpl_id)}",
        )

    def save_lead_node(self, lead: dict) -> bool:
        tid = str(lead.get("tenant_id") or "default")
        phone = str(lead.get("phone_number") or "")
        return self._run_write(
            """
            MERGE (l:Lead {key: $key})
            SET l.id = $id, l.tenant_id = $tid, l.phone_number = $phone,
                l.name = $name, l.source = $source, l.status = $status,
                l.notes = $notes, l.last_messaged_at = $last_messaged_at,
                l.created_at = coalesce(l.created_at, $created_at)
            """,
            key=f"{tid}:{phone}",
            id=int(lead.get("id") or 0),
            tid=tid,
            phone=phone,
            name=str(lead.get("name") or "Lead"),
            source=str(lead.get("source") or "Manual Import"),
            status=str(lead.get("status") or "New"),
            notes=str(lead.get("notes") or ""),
            last_messaged_at=str(lead.get("last_messaged_at") or ""),
            created_at=str(lead.get("created_at") or _now_iso()),
        )

    def delete_lead_node(self, tenant_id: str, lead_id: int) -> bool:
        return self._run_write(
            "MATCH (l:Lead {tenant_id: $tid, id: $id}) DETACH DELETE l",
            tid=tenant_id,
            id=int(lead_id),
        )

    def save_booking_node(self, booking: dict) -> bool:
        tid = str(booking.get("tenant_id") or "default")
        bid = int(booking["id"])
        return self._run_write(
            """
            MERGE (b:Booking {key: $key})
            SET b.id = $id, b.tenant_id = $tid, b.phone_number = $phone,
                b.customer_name = $customer_name, b.service_requested = $service_requested,
                b.booking_date_time = $booking_date_time, b.status = $status,
                b.notes = $notes, b.created_at = coalesce(b.created_at, $created_at)
            """,
            key=f"{tid}:{bid}",
            id=bid,
            tid=tid,
            phone=str(booking.get("phone_number") or ""),
            customer_name=str(booking.get("customer_name") or "Customer"),
            service_requested=str(booking.get("service_requested") or ""),
            booking_date_time=str(booking.get("booking_date_time") or ""),
            status=str(booking.get("status") or "pending"),
            notes=str(booking.get("notes") or ""),
            created_at=str(booking.get("created_at") or _now_iso()),
        )

    def update_booking_node(self, tenant_id: str, booking_id: int, status: str) -> bool:
        return self._run_write(
            "MATCH (b:Booking {key: $key}) SET b.status = $status",
            key=f"{tenant_id}:{int(booking_id)}",
            status=status,
        )

    def upsert_contact_setting_node(self, tenant_id: str, phone_number: str, bot_enabled: int) -> bool:
        return self._run_write(
            """
            MERGE (cs:ContactSetting {key: $key})
            SET cs.tenant_id = $tid, cs.phone_number = $phone, cs.bot_enabled = $bot_enabled
            """,
            key=f"{tenant_id}:{phone_number}",
            tid=tenant_id,
            phone=phone_number,
            bot_enabled=int(bot_enabled),
        )

    def upsert_billing_window_node(self, win: dict) -> bool:
        tid = str(win.get("tenant_id") or "default")
        phone = str(win.get("phone_number") or "")
        return self._run_write(
            """
            MERGE (bw:BillingWindow {key: $key})
            SET bw.tenant_id = $tid, bw.phone_number = $phone,
                bw.billing_mode = $billing_mode, bw.cost_coins = $cost_coins,
                bw.charge_source = $charge_source, bw.opened_at = $opened_at,
                bw.expires_at = $expires_at
            """,
            key=f"{tid}:{phone}",
            tid=tid,
            phone=phone,
            billing_mode=str(win.get("billing_mode") or "managed_meta"),
            cost_coins=float(win.get("cost_coins") or 0),
            charge_source=str(win.get("charge_source") or "free_demo"),
            opened_at=str(win.get("opened_at") or _now_iso()),
            expires_at=str(win.get("expires_at") or _now_iso()),
        )

    def save_security_event_node(self, ev: dict) -> bool:
        tid = str(ev.get("tenant_id") or "default")
        eid = int(ev.get("id") or 0)
        return self._run_write(
            """
            MERGE (se:SecurityEvent {key: $key})
            SET se.id = $id, se.tenant_id = $tid, se.phone_number = $phone,
                se.input_text = $input_text, se.detector = $detector,
                se.reason = $reason, se.blocked = $blocked, se.created_at = $created_at
            """,
            key=f"{tid}:{eid}",
            id=eid,
            tid=tid,
            phone=str(ev.get("phone_number") or ""),
            input_text=str(ev.get("input_text") or "")[:500],
            detector=str(ev.get("detector") or ""),
            reason=str(ev.get("reason") or ""),
            blocked=int(ev.get("blocked") or 0),
            created_at=str(ev.get("created_at") or _now_iso()),
        )

    # ====================================================================
    # LIVE DNA KNOWLEDGE GRAPH (RELATIONSHIP BUILDER IN NEO4J)
    # ====================================================================

    def record_customer_knowledge_graph(
        self,
        tenant_id: str,
        phone: str,
        message_text: str = "",
        profile: Optional[dict] = None,
        service_hint: str = "",
    ) -> bool:
        """
        Builds rich, tenant-isolated Knowledge Graph relationships in Neo4j:
        Customer -> OWNS_BUSINESS -> Business -> IN_CATEGORY / LOCATED_IN / HAS_WEBSITE / USES_TOOL
        Customer -> INQUIRED_ABOUT -> Service
        Customer -> HAD_EPISODE -> Episode
        """
        if not phone:
            return False
        tid = str(tenant_id or "default").strip()
        clean_phone = str(phone).replace("+", "").strip()
        cust_key = f"{tid}:{clean_phone}"
        prof = profile or {}
        now_iso = _now_iso()

        contact_name = str(prof.get("contact_name") or "").strip()
        bname = str(prof.get("business_name") or "").strip()
        bcat = str(prof.get("business_category") or "").strip()
        area = str(prof.get("area") or "").strip()
        website_url = str(prof.get("website_url") or "").strip()
        has_site = str(prof.get("has_website") or "").strip()
        eco_str = str(prof.get("existing_ecosystem") or "").strip()
        eco_list = [x.strip() for x in eco_str.split(",") if x.strip()] if eco_str else []

        biz_key = f"{tid}:{_slug(bname)}" if bname else ""
        site_key = f"{tid}:{website_url or bname or clean_phone}" if (website_url or has_site) else ""

        ep_id = ""
        if message_text and len(message_text.strip()) >= 3:
            ep_id = f"ep_{hashlib.sha256(f'{cust_key}:{message_text}:{now_iso}'.encode()).hexdigest()[:14]}"

        cypher = """
        MERGE (t:Tenant {id: $tid})
        MERGE (c:Customer {key: $cust_key})
        ON CREATE SET c.tenant_id = $tid, c.phone = $phone, c.created_at = $now
        SET c.name = CASE WHEN $contact_name <> '' THEN $contact_name ELSE coalesce(c.name, $phone) END,
            c.updated_at = $now
        MERGE (t)-[:HAS_CUSTOMER]->(c)

        FOREACH (_ IN CASE WHEN $bname <> '' THEN [1] ELSE [] END |
            MERGE (b:Business {key: $biz_key})
            SET b.tenant_id = $tid, b.name = $bname, b.updated_at = $now
            MERGE (c)-[:OWNS_BUSINESS]->(b)
            FOREACH (__ IN CASE WHEN $bcat <> '' THEN [1] ELSE [] END |
                MERGE (cat:Category {name: $bcat})
                MERGE (b)-[:IN_CATEGORY]->(cat)
            )
            FOREACH (__ IN CASE WHEN $area <> '' THEN [1] ELSE [] END |
                MERGE (ar:Area {name: $area})
                MERGE (b)-[:LOCATED_IN]->(ar)
            )
            FOREACH (__ IN CASE WHEN $site_key <> '' THEN [1] ELSE [] END |
                MERGE (w:Website {key: $site_key})
                SET w.url = $website_url, w.has_website = $has_site
                MERGE (b)-[:HAS_WEBSITE]->(w)
            )
            FOREACH (toolName IN $eco_list |
                MERGE (et:EcosystemTool {name: toolName})
                MERGE (b)-[:USES_TOOL]->(et)
            )
        )

        FOREACH (_ IN CASE WHEN $service_hint <> '' THEN [1] ELSE [] END |
            MERGE (sv:Service {name: $service_hint})
            MERGE (c)-[r:INQUIRED_ABOUT]->(sv)
            SET r.updated_at = $now
        )

        FOREACH (_ IN CASE WHEN $ep_id <> '' THEN [1] ELSE [] END |
            MERGE (ep:Episode {id: $ep_id})
            SET ep.tenant_id = $tid, ep.phone = $phone, ep.content = $ep_content, ep.timestamp = $now
            MERGE (c)-[:HAD_EPISODE]->(ep)
        )
        """
        return self._run_write(
            cypher,
            tid=tid,
            cust_key=cust_key,
            phone=clean_phone,
            contact_name=contact_name,
            now=now_iso,
            bname=bname,
            biz_key=biz_key,
            bcat=bcat,
            area=area,
            site_key=site_key,
            website_url=website_url,
            has_site=has_site,
            eco_list=eco_list,
            service_hint=service_hint.strip(),
            ep_id=ep_id,
            ep_content=(message_text or "")[:350],
        )

    def get_customer_subgraph(self, tenant_id: str, phone: str) -> Dict[str, Any]:
        """Fetch live relational subgraph for a single customer within this tenant."""
        tid = str(tenant_id or "default").strip()
        clean = str(phone or "").replace("+", "").strip()
        cust_key = f"{tid}:{clean}"
        if not self._ensure_driver():
            return {"connected": False, "nodes": [], "edges": [], "episodes": [], "summary_prompt": ""}

        rows = self._run_read(
            """
            MATCH (c:Customer {key: $cust_key})
            OPTIONAL MATCH (c)-[:OWNS_BUSINESS]->(b:Business)
            OPTIONAL MATCH (b)-[:IN_CATEGORY]->(cat:Category)
            OPTIONAL MATCH (b)-[:LOCATED_IN]->(ar:Area)
            OPTIONAL MATCH (b)-[:HAS_WEBSITE]->(w:Website)
            OPTIONAL MATCH (b)-[:USES_TOOL]->(et:EcosystemTool)
            OPTIONAL MATCH (c)-[:INQUIRED_ABOUT]->(sv:Service)
            RETURN c.name AS contact_name,
                   b.name AS business_name,
                   collect(DISTINCT cat.name) AS categories,
                   collect(DISTINCT ar.name) AS areas,
                   collect(DISTINCT {url: w.url, status: w.has_website}) AS websites,
                   collect(DISTINCT et.name) AS tools,
                   collect(DISTINCT sv.name) AS services
            """,
            cust_key=cust_key,
        )

        ep_rows = self._run_read(
            """
            MATCH (c:Customer {key: $cust_key})-[:HAD_EPISODE]->(ep:Episode)
            RETURN ep.id AS id, ep.content AS content, ep.timestamp AS timestamp
            ORDER BY ep.timestamp DESC LIMIT 5
            """,
            cust_key=cust_key,
        )

        nodes: List[dict] = [{"id": cust_key, "label": "Customer", "name": clean}]
        edges: List[dict] = []
        summary_lines: List[str] = []

        if rows:
            r = rows[0]
            cname = r.get("contact_name") or clean
            nodes[0]["name"] = cname
            bname = r.get("business_name")
            if bname:
                b_id = f"biz_{_slug(bname)}"
                nodes.append({"id": b_id, "label": "Business", "name": bname})
                edges.append({"source": cname, "relation": "OWNS_BUSINESS", "target": bname})
                summary_lines.append(f"- Graph Edge: ({cname})-[OWNS_BUSINESS]->({bname})")

                for cat in (r.get("categories") or []):
                    if cat:
                        nodes.append({"id": f"cat_{_slug(cat)}", "label": "Category", "name": cat})
                        edges.append({"source": bname, "relation": "IN_CATEGORY", "target": cat})
                        summary_lines.append(f"- Graph Edge: ({bname})-[IN_CATEGORY]->({cat})")

                for area in (r.get("areas") or []):
                    if area:
                        nodes.append({"id": f"area_{_slug(area)}", "label": "Area", "name": area})
                        edges.append({"source": bname, "relation": "LOCATED_IN", "target": area})
                        summary_lines.append(f"- Graph Edge: ({bname})-[LOCATED_IN]->({area})")

                for w in (r.get("websites") or []):
                    if isinstance(w, dict) and (w.get("url") or w.get("status")):
                        wlabel = w.get("url") or f"website:{w.get('status')}"
                        nodes.append({"id": f"web_{_slug(wlabel)}", "label": "Website", "name": wlabel})
                        edges.append({"source": bname, "relation": "HAS_WEBSITE", "target": wlabel})
                        summary_lines.append(f"- Graph Edge: ({bname})-[HAS_WEBSITE]->({wlabel})")

                for tool in (r.get("tools") or []):
                    if tool:
                        nodes.append({"id": f"tool_{_slug(tool)}", "label": "EcosystemTool", "name": tool})
                        edges.append({"source": bname, "relation": "USES_TOOL", "target": tool})
                        summary_lines.append(f"- Graph Edge: ({bname})-[USES_TOOL]->({tool})")

            for sv in (r.get("services") or []):
                if sv:
                    nodes.append({"id": f"svc_{_slug(sv)}", "label": "Service", "name": sv})
                    edges.append({"source": cname, "relation": "INQUIRED_ABOUT", "target": sv})
                    summary_lines.append(f"- Graph Edge: ({cname})-[INQUIRED_ABOUT]->({sv})")

        prompt_str = ""
        if summary_lines:
            prompt_str = "[NEO4J LIVE KNOWLEDGE GRAPH RELATIONSHIPS]:\n" + "\n".join(summary_lines)

        return {
            "connected": self._connected,
            "customer_key": cust_key,
            "nodes": nodes,
            "edges": edges,
            "episodes": ep_rows,
            "summary_prompt": prompt_str,
        }

    def query_tenant_graph(self, tenant_id: str, query: str = "", limit: int = 30) -> Dict[str, Any]:
        """Search tenant-scoped Knowledge Graph entities and relationships."""
        tid = str(tenant_id or "default").strip()
        q = (query or "").strip().lower()
        if not self._ensure_driver():
            return {"connected": False, "edges": [], "query": query}

        rows = self._run_read(
            """
            MATCH (t:Tenant {id: $tid})-[:HAS_CUSTOMER]->(c:Customer)
            OPTIONAL MATCH (c)-[r1]->(n1)
            WHERE NOT (n1:ChatMessage) AND NOT (n1:CustomerProfile) AND NOT (n1:Episode)
            OPTIONAL MATCH (n1)-[r2]->(n2)
            WITH c, r1, n1, r2, n2
            RETURN c.name AS customer_name, c.phone AS phone,
                   type(r1) AS rel1, coalesce(n1.name, n1.url, '') AS target1, labels(n1)[0] AS label1,
                   type(r2) AS rel2, coalesce(n2.name, n2.url, '') AS target2, labels(n2)[0] AS label2
            LIMIT 120
            """,
            tid=tid,
        )

        edges: List[dict] = []
        seen = set()
        for r in rows:
            cname = r.get("customer_name") or r.get("phone") or "Customer"
            if r.get("rel1") and r.get("target1"):
                e1 = {"source": cname, "relation": r["rel1"], "target": r["target1"], "target_type": r.get("label1", "")}
                txt1 = f"{e1['source']} {e1['relation']} {e1['target']}".lower()
                if not q or q in txt1:
                    k1 = (e1["source"], e1["relation"], e1["target"])
                    if k1 not in seen:
                        seen.add(k1)
                        edges.append(e1)
            if r.get("rel2") and r.get("target2") and r.get("target1"):
                e2 = {"source": r["target1"], "relation": r["rel2"], "target": r["target2"], "target_type": r.get("label2", "")}
                txt2 = f"{e2['source']} {e2['relation']} {e2['target']}".lower()
                if not q or q in txt2:
                    k2 = (e2["source"], e2["relation"], e2["target"])
                    if k2 not in seen:
                        seen.add(k2)
                        edges.append(e2)

        return {
            "connected": True,
            "tenant_id": tid,
            "query": query,
            "edges": edges[:limit],
        }

    # ====================================================================
    # STARTUP HYDRATION & MIGRATION (ZERO CHAT LOSS ON DEPLOY)
    # ====================================================================

    def hydrate_and_sync_sqlite(self, conn) -> Dict[str, int]:
        """
        On startup:
        1. Pull persisted records from Neo4j AuraDB into SQLite (`INSERT OR IGNORE`)
           so Render/container redeploys NEVER erase old chats or tenants.
        2. Push any SQLite rows that aren't in Neo4j yet (first migration).
        """
        summary = {"restored_tenants": 0, "restored_messages": 0, "restored_profiles": 0, "restored_leads": 0, "backfilled": 0}
        if not self._ensure_driver():
            return summary

        cur = conn.cursor()

        # 1. Hydrate Tenants
        tenants = self._run_read("MATCH (t:Tenant) RETURN properties(t) AS props")
        for row in tenants:
            p = row.get("props") or {}
            tid = p.get("id")
            if not tid:
                continue
            existing = cur.execute("SELECT tenant_id FROM tenants WHERE tenant_id = ?", (tid,)).fetchone()
            if not existing:
                cur.execute(
                    """
                    INSERT INTO tenants (
                        tenant_id, email, full_name, business_name, custom_system_prompt,
                        billing_mode, plan_tier, plan_quota, plan_used, plan_expires_at, demo_used,
                        whatsapp_token, whatsapp_phone_number_id, whatsapp_verify_token,
                        deepseek_api_key, deepseek_model, groq_api_key, groq_model,
                        openrouter_api_key, openrouter_guard_model
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tid, p.get("email", ""), p.get("full_name", ""), p.get("business_name", ""),
                        p.get("custom_system_prompt", ""), p.get("billing_mode", "managed_meta"),
                        p.get("plan_tier", "payg"), int(p.get("plan_quota") or 0), int(p.get("plan_used") or 0),
                        p.get("plan_expires_at", ""), int(p.get("demo_used") or 0),
                        p.get("whatsapp_token", ""), p.get("whatsapp_phone_number_id", ""),
                        p.get("whatsapp_verify_token", ""), p.get("deepseek_api_key", ""),
                        p.get("deepseek_model", "deepseek-chat"), p.get("groq_api_key", ""),
                        p.get("groq_model", "llama-3.3-70b-versatile"),
                        p.get("openrouter_api_key", ""), p.get("openrouter_guard_model", "meta-llama/llama-guard-4-12b"),
                    ),
                )
                summary["restored_tenants"] += 1

        # 2. Hydrate Chat Messages
        msgs = self._run_read("MATCH (m:ChatMessage) RETURN properties(m) AS props ORDER BY m.id ASC")
        for row in msgs:
            p = row.get("props") or {}
            mid = p.get("id")
            if mid is None:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO messages (
                    id, tenant_id, phone_number, sender_name, message, direction,
                    channel, status, raw_payload, ai_model, latency_ms,
                    media_type, media_url, media_filename, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(mid), p.get("tenant_id") or "default", p.get("phone_number") or "",
                    p.get("sender_name") or "User", p.get("message") or "", p.get("direction") or "inbound",
                    p.get("channel") or "meta_whatsapp", p.get("status") or "received",
                    p.get("raw_payload") or "", p.get("ai_model") or None, float(p.get("latency_ms") or 0.0),
                    p.get("media_type") or None, p.get("media_url") or None,
                    p.get("media_filename") or None, p.get("created_at") or _now_iso(),
                ),
            )
            if cur.rowcount > 0:
                summary["restored_messages"] += 1

        # 3. Hydrate Customer Profiles
        profs = self._run_read("MATCH (p:CustomerProfile) RETURN properties(p) AS props")
        for row in profs:
            p = row.get("props") or {}
            phone = p.get("phone_number")
            if not phone:
                continue
            tid = p.get("tenant_id") or "default"
            cur.execute(
                """
                INSERT OR IGNORE INTO customer_profiles (
                    phone_number, tenant_id, contact_name, business_name, business_category,
                    area, has_website, website_url, existing_ecosystem, pain_points, goals,
                    data_source, updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    phone, tid, p.get("contact_name", ""), p.get("business_name", ""),
                    p.get("business_category", ""), p.get("area", ""), p.get("has_website", ""),
                    p.get("website_url", ""), p.get("existing_ecosystem", ""),
                    p.get("pain_points", ""), p.get("goals", ""), p.get("data_source", ""),
                    p.get("updated_at") or _now_iso(), p.get("created_at") or _now_iso(),
                ),
            )
            if cur.rowcount > 0:
                summary["restored_profiles"] += 1

        # 4. Hydrate Templates
        tpls = self._run_read("MATCH (t:Template) RETURN properties(t) AS props")
        for row in tpls:
            p = row.get("props") or {}
            if p.get("id") is None:
                continue
            cur.execute(
                "INSERT OR IGNORE INTO templates (id, tenant_id, title, category, content, shortcut, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(p["id"]), p.get("tenant_id") or "default", p.get("title") or "Template",
                    p.get("category") or "General", p.get("content") or "",
                    p.get("shortcut") or "", p.get("created_at") or _now_iso(),
                ),
            )

        # 5. Hydrate Leads
        leads = self._run_read("MATCH (l:Lead) RETURN properties(l) AS props")
        for row in leads:
            p = row.get("props") or {}
            phone = p.get("phone_number")
            if not phone:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO leads (id, tenant_id, phone_number, name, source, status, notes, last_messaged_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(p.get("id") or 0) or None, p.get("tenant_id") or "default", phone,
                    p.get("name") or "Lead", p.get("source") or "Manual Import",
                    p.get("status") or "New", p.get("notes") or "",
                    p.get("last_messaged_at") or None, p.get("created_at") or _now_iso(),
                ),
            )
            if cur.rowcount > 0:
                summary["restored_leads"] += 1

        # 6. Hydrate Bookings, ContactSettings, BillingWindows, SecurityEvents
        for row in self._run_read("MATCH (b:Booking) RETURN properties(b) AS props"):
            p = row.get("props") or {}
            if p.get("id") is None:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO bookings (id, tenant_id, phone_number, customer_name, service_requested, booking_date_time, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(p["id"]), p.get("tenant_id") or "default", p.get("phone_number") or "",
                    p.get("customer_name") or "Customer", p.get("service_requested") or "",
                    p.get("booking_date_time") or "", p.get("status") or "pending",
                    p.get("notes") or "", p.get("created_at") or _now_iso(),
                ),
            )

        for row in self._run_read("MATCH (cs:ContactSetting) RETURN properties(cs) AS props"):
            p = row.get("props") or {}
            if not p.get("phone_number"):
                continue
            cur.execute(
                "INSERT OR IGNORE INTO contact_settings (phone_number, tenant_id, bot_enabled) VALUES (?, ?, ?)",
                (p["phone_number"], p.get("tenant_id") or "default", int(p.get("bot_enabled", 1))),
            )

        for row in self._run_read("MATCH (bw:BillingWindow) RETURN properties(bw) AS props"):
            p = row.get("props") or {}
            if not p.get("phone_number"):
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO billing_windows (tenant_id, phone_number, billing_mode, cost_coins, charge_source, opened_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p.get("tenant_id") or "default", p["phone_number"],
                    p.get("billing_mode") or "managed_meta", float(p.get("cost_coins") or 0),
                    p.get("charge_source") or "free_demo", p.get("opened_at") or _now_iso(),
                    p.get("expires_at") or _now_iso(),
                ),
            )

        conn.commit()

        # 7. Backfill any local SQLite rows to Neo4j if Neo4j didn't have them yet
        neo_msg_count = len(msgs)
        local_msgs = cur.execute("SELECT * FROM messages ORDER BY id ASC").fetchall()
        if len(local_msgs) > neo_msg_count:
            for r in local_msgs:
                if self.save_message_node(dict(r)):
                    summary["backfilled"] += 1

        local_profs = cur.execute("SELECT * FROM customer_profiles").fetchall()
        if len(local_profs) > len(profs):
            for r in local_profs:
                self.upsert_customer_profile_node(dict(r).get("tenant_id") or "default", dict(r))

        local_tpls = cur.execute("SELECT * FROM templates").fetchall()
        if len(local_tpls) > len(tpls):
            for r in local_tpls:
                self.save_template_node(dict(r))

        local_leads = cur.execute("SELECT * FROM leads").fetchall()
        if len(local_leads) > len(leads):
            for r in local_leads:
                self.save_lead_node(dict(r))

        local_tenants = cur.execute("SELECT * FROM tenants").fetchall()
        for r in local_tenants:
            self.upsert_tenant(dict(r))

        return summary


neo4j_store = Neo4jStore()
