"""
Supabase Cloud Persistence + Live Temporal DNA Knowledge Graph Store.

Replaces Neo4j with PostgreSQL via Supabase REST API (`orhhmysimejphmtrqhlg.supabase.co`):
1. Mirrors ALL operational SaaS tables (Tenants, Messages, CustomerProfiles, Templates,
   Leads, Bookings, ContactSettings, BillingWindows, SecurityEvents) in `wa_*` tables so
   Render / ephemeral container redeploys NEVER lose historical chats or user accounts.
2. Stores and queries a live Customer <-> Business <-> Ecosystem Knowledge Graph in
   `wa_graph_nodes`, `wa_graph_edges`, and `wa_graph_episodes`.
3. Degrades gracefully to local SQLite if WA_SUPABASE_SECRET_KEY or SQL tables are missing.
"""

import os
import re
import time
import hashlib
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("supabase_store")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(val: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", str(val or "").strip().lower()).strip("_")
    return clean[:64] or "node"


def _postgrest_in_list(values: List[str]) -> str:
    escaped = []
    for v in values:
        s = str(v or "").replace('"', '\\"')
        escaped.append(f'"{s}"')
    return "(" + ",".join(escaped) + ")"


class SupabaseStore:
    """Thread-safe Supabase PostgREST persistence + Knowledge Graph store."""

    def __init__(self, transport: Optional[httpx.BaseTransport] = None):
        self._lock = threading.Lock()
        self._transport = transport
        self._client: Optional[httpx.Client] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._last_checked: float = 0.0

    def _get_config(self) -> Tuple[str, str, str]:
        url = os.getenv("WA_SUPABASE_URL", "").strip().rstrip("/")
        secret = (
            os.getenv("WA_SUPABASE_SECRET_KEY", "")
            or os.getenv("WA_SUPABASE_SERVICE_ROLE_KEY", "")
        ).strip()
        publishable = os.getenv("WA_SUPABASE_PUBLISHABLE_KEY", "").strip()
        return url, secret, publishable

    def _get_client(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                kwargs: Dict[str, Any] = {"timeout": 10.0}
                if self._transport is not None:
                    kwargs["transport"] = self._transport
                self._client = httpx.Client(**kwargs)
            return self._client

    def _headers(
        self,
        key: str,
        prefer: Optional[str] = None,
        range_hdr: Optional[str] = None,
    ) -> Dict[str, str]:
        headers = {
            "apikey": key,
            "Content-Type": "application/json",
        }
        # Legacy JWT keys (eyJ...) go in Authorization as Bearer tokens;
        # new Supabase sb_secret_/sb_publishable_ keys are validated via apikey only.
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        if prefer:
            headers["Prefer"] = prefer
        if range_hdr:
            headers["Range"] = range_hdr
        return headers

    def _is_ready_key(self) -> Tuple[str, str]:
        url, secret, publishable = self._get_config()
        if not url:
            self._connected = False
            self._last_error = "WA_SUPABASE_URL is not configured"
            return "", ""
        key = secret or publishable
        if not key:
            self._connected = False
            self._last_error = "WA_SUPABASE_SECRET_KEY is not configured"
            return url, ""
        return url, key

    def _parse_error_hint(self, status_code: int, text: str, used_secret: bool) -> str:
        low = (text or "").lower()
        if status_code in (401, 403):
            if not used_secret or "secret api key required" in low or "permission denied" in low:
                return (
                    "Set WA_SUPABASE_SECRET_KEY (sb_secret_... or service_role) in Render "
                    "and run supabase_schema.sql in Supabase SQL Editor."
                )
            return f"Supabase auth rejected ({status_code}): {text[:160]}"
        if status_code == 404 or "pgrst205" in low or "could not find the table" in low:
            return "Run supabase_schema.sql in Supabase SQL Editor to create wa_* tables."
        return f"HTTP {status_code}: {text[:180]}"

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Any = None,
        prefer: Optional[str] = None,
        range_hdr: Optional[str] = None,
    ) -> Optional[httpx.Response]:
        url, secret, publishable = self._get_config()
        active_key = secret or publishable
        if not url or not active_key:
            self._connected = False
            self._last_error = "WA_SUPABASE_URL or WA_SUPABASE_SECRET_KEY not configured"
            return None

        full_url = f"{url}/rest/v1/{path.lstrip('/')}"
        headers = self._headers(active_key, prefer=prefer, range_hdr=range_hdr)
        try:
            resp = self._get_client().request(
                method,
                full_url,
                headers=headers,
                params=params,
                json=json_data,
            )
            if 200 <= resp.status_code < 300:
                self._connected = True
                self._last_error = None
                return resp

            err_msg = self._parse_error_hint(resp.status_code, resp.text, bool(secret))
            self._last_error = err_msg
            if resp.status_code in (401, 403, 404):
                self._connected = False
            logger.debug(f"[SupabaseStore] {method} {path} -> {resp.status_code}: {err_msg}")
            return resp
        except Exception as e:
            self._connected = False
            self._last_error = str(e)
            logger.warning(f"[SupabaseStore] Request error ({method} {path}): {e}")
            return None

    def _upsert(self, table: str, payload: Any, on_conflict: str) -> bool:
        resp = self._request(
            "POST",
            table,
            params={"on_conflict": on_conflict},
            json_data=payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def _select(
        self,
        table: str,
        params: Optional[Dict[str, Any]] = None,
        select: str = "*",
    ) -> List[dict]:
        q = dict(params or {})
        q.setdefault("select", select)
        resp = self._request("GET", table, params=q)
        if resp is None or not (200 <= resp.status_code < 300):
            return []
        try:
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _select_all(self, table: str, order: Optional[str] = None) -> List[dict]:
        rows: List[dict] = []
        offset = 0
        page_size = 1000
        while True:
            params: Dict[str, Any] = {
                "select": "*",
                "limit": page_size,
                "offset": offset,
            }
            if order:
                params["order"] = order
            batch = self._select(table, params=params)
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return rows

    def _count_rows(self, table: str, filters: Optional[Dict[str, Any]] = None) -> int:
        params = dict(filters or {})
        params["select"] = "*"
        resp = self._request(
            "GET",
            table,
            params=params,
            prefer="count=exact",
            range_hdr="0-0",
        )
        if resp is None or not (200 <= resp.status_code < 300):
            return 0
        cr = resp.headers.get("Content-Range", "") or resp.headers.get("content-range", "")
        if "/" in cr:
            tail = cr.split("/")[-1].strip()
            if tail.isdigit():
                return int(tail)
        try:
            data = resp.json()
            return len(data) if isinstance(data, list) else 0
        except Exception:
            return 0

    def _ensure_ready(self) -> bool:
        now = time.time()
        if self._connected and (now - self._last_checked) < 30.0:
            return True
        self._last_checked = now
        resp = self._request("GET", "wa_tenants", params={"select": "tenant_id", "limit": 1})
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def get_status(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        url, secret, publishable = self._get_config()
        configured = bool(url and (secret or publishable))
        ready = self._ensure_ready() if configured else False
        host_display = url.split("://")[-1] if url else "not configured"

        stats: Dict[str, Any] = {
            "provider": "supabase",
            "configured": configured,
            "has_secret_key": bool(secret),
            "connected": ready,
            "uri_host": host_display,
            "database": "supabase_postgres",
            "error": self._last_error,
            "node_count": 0,
            "relationship_count": 0,
            "tenant_nodes": 0,
            "customer_nodes": 0,
            "business_nodes": 0,
            "message_nodes": 0,
            "mode": "SUPABASE_LIVE" if ready else "SQLITE_LOCAL_FALLBACK",
        }
        if not ready:
            return stats

        tf = {"tenant_id": f"eq.{tenant_id}"} if tenant_id else None
        stats["node_count"] = self._count_rows("wa_graph_nodes", tf)
        stats["relationship_count"] = self._count_rows("wa_graph_edges", tf)
        stats["tenant_nodes"] = self._count_rows("wa_tenants")
        stats["message_nodes"] = self._count_rows("wa_messages", tf)
        cust_f = dict(tf or {})
        cust_f["label"] = "eq.Customer"
        stats["customer_nodes"] = self._count_rows("wa_graph_nodes", cust_f)
        biz_f = dict(tf or {})
        biz_f["label"] = "eq.Business"
        stats["business_nodes"] = self._count_rows("wa_graph_nodes", biz_f)
        return stats

    # ====================================================================
    # OPERATIONAL SAAS SYNC (ZERO DATA LOSS ON DEPLOY)
    # ====================================================================

    def upsert_tenant(self, tenant: dict) -> bool:
        tid = str(tenant.get("tenant_id") or "default").strip()
        row = {
            "tenant_id": tid,
            "email": str(tenant.get("email") or ""),
            "full_name": str(tenant.get("full_name") or ""),
            "business_name": str(tenant.get("business_name") or ""),
            "custom_system_prompt": str(tenant.get("custom_system_prompt") or ""),
            "billing_mode": str(tenant.get("billing_mode") or "managed_meta"),
            "plan_tier": str(tenant.get("plan_tier") or "payg"),
            "plan_quota": int(tenant.get("plan_quota") or 0),
            "plan_used": int(tenant.get("plan_used") or 0),
            "plan_expires_at": str(tenant.get("plan_expires_at") or ""),
            "demo_used": int(tenant.get("demo_used") or 0),
            "whatsapp_token": str(tenant.get("whatsapp_token") or ""),
            "whatsapp_phone_number_id": str(tenant.get("whatsapp_phone_number_id") or ""),
            "whatsapp_verify_token": str(tenant.get("whatsapp_verify_token") or ""),
            "deepseek_api_key": str(tenant.get("deepseek_api_key") or ""),
            "deepseek_model": str(tenant.get("deepseek_model") or "deepseek-chat"),
            "groq_api_key": str(tenant.get("groq_api_key") or ""),
            "groq_model": str(tenant.get("groq_model") or "llama-3.3-70b-versatile"),
            "openrouter_api_key": str(tenant.get("openrouter_api_key") or ""),
            "openrouter_guard_model": str(tenant.get("openrouter_guard_model") or "meta-llama/llama-guard-4-12b"),
            "updated_at": str(tenant.get("updated_at") or _now_iso()),
        }
        return self._upsert("wa_tenants", row, on_conflict="tenant_id")

    def save_message_node(self, msg: dict) -> bool:
        tid = str(msg.get("tenant_id") or "default").strip()
        msg_id = int(msg["id"])
        row = {
            "msg_key": f"{tid}:{msg_id}",
            "id": msg_id,
            "tenant_id": tid,
            "phone_number": str(msg.get("phone_number") or "").strip(),
            "sender_name": str(msg.get("sender_name") or "User"),
            "message": str(msg.get("message") or ""),
            "direction": str(msg.get("direction") or "inbound"),
            "channel": str(msg.get("channel") or "meta_whatsapp"),
            "status": str(msg.get("status") or "received"),
            "raw_payload": str(msg.get("raw_payload") or "")[:4000],
            "ai_model": str(msg.get("ai_model") or ""),
            "latency_ms": float(msg.get("latency_ms") or 0.0),
            "media_type": str(msg.get("media_type") or ""),
            "media_url": str(msg.get("media_url") or ""),
            "media_filename": str(msg.get("media_filename") or ""),
            "created_at": str(msg.get("created_at") or _now_iso()),
        }
        return self._upsert("wa_messages", row, on_conflict="msg_key")

    def delete_message_nodes(self, tenant_id: str, ids: List[int]) -> bool:
        keys = [f"{tenant_id}:{int(i)}" for i in ids if str(i).isdigit()]
        if not keys:
            return True
        resp = self._request(
            "DELETE",
            "wa_messages",
            params={"msg_key": f"in.{_postgrest_in_list(keys)}"},
        )
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def delete_conversation_nodes(self, tenant_id: str, phone_number: str) -> bool:
        clean = str(phone_number or "").replace("+", "").strip()
        variants = list({str(phone_number or "").strip(), clean, f"+{clean}"})
        variants = [v for v in variants if v]
        if not variants:
            return True
        resp = self._request(
            "DELETE",
            "wa_messages",
            params={
                "tenant_id": f"eq.{tenant_id}",
                "phone_number": f"in.{_postgrest_in_list(variants)}",
            },
        )
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def clear_tenant_messages(self, tenant_id: str) -> bool:
        resp = self._request(
            "DELETE",
            "wa_messages",
            params={"tenant_id": f"eq.{tenant_id}"},
        )
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def upsert_customer_profile_node(self, tenant_id: str, prof: dict) -> bool:
        tid = str(tenant_id or "default").strip()
        phone = str(prof.get("phone_number") or "").strip()
        if not phone:
            return False
        now_iso = _now_iso()
        row = {
            "profile_key": f"{tid}:{phone}",
            "tenant_id": tid,
            "phone_number": phone,
            "contact_name": str(prof.get("contact_name") or ""),
            "business_name": str(prof.get("business_name") or ""),
            "business_category": str(prof.get("business_category") or ""),
            "area": str(prof.get("area") or ""),
            "has_website": str(prof.get("has_website") or ""),
            "website_url": str(prof.get("website_url") or ""),
            "existing_ecosystem": str(prof.get("existing_ecosystem") or ""),
            "pain_points": str(prof.get("pain_points") or ""),
            "goals": str(prof.get("goals") or ""),
            "data_source": str(prof.get("data_source") or ""),
            "updated_at": str(prof.get("updated_at") or now_iso),
            "created_at": str(prof.get("created_at") or now_iso),
        }
        res = self._upsert("wa_customer_profiles", row, on_conflict="profile_key")
        self.record_customer_knowledge_graph(tenant_id=tid, phone=phone, profile=prof)
        return res

    def save_template_node(self, tpl: dict) -> bool:
        tid = str(tpl.get("tenant_id") or "default")
        tpl_id = int(tpl["id"])
        row = {
            "tpl_key": f"{tid}:{tpl_id}",
            "id": tpl_id,
            "tenant_id": tid,
            "title": str(tpl.get("title") or ""),
            "category": str(tpl.get("category") or "General"),
            "content": str(tpl.get("content") or ""),
            "shortcut": str(tpl.get("shortcut") or ""),
            "created_at": str(tpl.get("created_at") or _now_iso()),
        }
        return self._upsert("wa_templates", row, on_conflict="tpl_key")

    def delete_template_node(self, tenant_id: str, tpl_id: int) -> bool:
        resp = self._request(
            "DELETE",
            "wa_templates",
            params={"tpl_key": f"eq.{tenant_id}:{int(tpl_id)}"},
        )
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def save_lead_node(self, lead: dict) -> bool:
        tid = str(lead.get("tenant_id") or "default")
        phone = str(lead.get("phone_number") or "")
        row = {
            "lead_key": f"{tid}:{phone}",
            "id": int(lead.get("id") or 0),
            "tenant_id": tid,
            "phone_number": phone,
            "name": str(lead.get("name") or "Lead"),
            "source": str(lead.get("source") or "Manual Import"),
            "status": str(lead.get("status") or "New"),
            "notes": str(lead.get("notes") or ""),
            "last_messaged_at": str(lead.get("last_messaged_at") or ""),
            "created_at": str(lead.get("created_at") or _now_iso()),
        }
        return self._upsert("wa_leads", row, on_conflict="lead_key")

    def delete_lead_node(self, tenant_id: str, lead_id: int) -> bool:
        resp = self._request(
            "DELETE",
            "wa_leads",
            params={"tenant_id": f"eq.{tenant_id}", "id": f"eq.{int(lead_id)}"},
        )
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def save_booking_node(self, booking: dict) -> bool:
        tid = str(booking.get("tenant_id") or "default")
        bid = int(booking["id"])
        row = {
            "booking_key": f"{tid}:{bid}",
            "id": bid,
            "tenant_id": tid,
            "phone_number": str(booking.get("phone_number") or ""),
            "customer_name": str(booking.get("customer_name") or "Customer"),
            "service_requested": str(booking.get("service_requested") or ""),
            "booking_date_time": str(booking.get("booking_date_time") or ""),
            "status": str(booking.get("status") or "pending"),
            "notes": str(booking.get("notes") or ""),
            "created_at": str(booking.get("created_at") or _now_iso()),
        }
        return self._upsert("wa_bookings", row, on_conflict="booking_key")

    def update_booking_node(self, tenant_id: str, booking_id: int, status: str) -> bool:
        resp = self._request(
            "PATCH",
            "wa_bookings",
            params={"booking_key": f"eq.{tenant_id}:{int(booking_id)}"},
            json_data={"status": status},
            prefer="return=minimal",
        )
        return bool(resp is not None and 200 <= resp.status_code < 300)

    def upsert_contact_setting_node(self, tenant_id: str, phone_number: str, bot_enabled: int) -> bool:
        row = {
            "setting_key": f"{tenant_id}:{phone_number}",
            "tenant_id": tenant_id,
            "phone_number": phone_number,
            "bot_enabled": int(bot_enabled),
        }
        return self._upsert("wa_contact_settings", row, on_conflict="setting_key")

    def upsert_billing_window_node(self, win: dict) -> bool:
        tid = str(win.get("tenant_id") or "default")
        phone = str(win.get("phone_number") or "")
        row = {
            "window_key": f"{tid}:{phone}",
            "tenant_id": tid,
            "phone_number": phone,
            "billing_mode": str(win.get("billing_mode") or "managed_meta"),
            "cost_coins": float(win.get("cost_coins") or 0),
            "charge_source": str(win.get("charge_source") or "free_demo"),
            "opened_at": str(win.get("opened_at") or _now_iso()),
            "expires_at": str(win.get("expires_at") or _now_iso()),
        }
        return self._upsert("wa_billing_windows", row, on_conflict="window_key")

    def save_security_event_node(self, ev: dict) -> bool:
        tid = str(ev.get("tenant_id") or "default")
        eid = int(ev.get("id") or 0)
        row = {
            "event_key": f"{tid}:{eid}",
            "id": eid,
            "tenant_id": tid,
            "phone_number": str(ev.get("phone_number") or ""),
            "input_text": str(ev.get("input_text") or "")[:500],
            "detector": str(ev.get("detector") or ""),
            "reason": str(ev.get("reason") or ""),
            "blocked": int(ev.get("blocked") or 0),
            "created_at": str(ev.get("created_at") or _now_iso()),
        }
        return self._upsert("wa_security_events", row, on_conflict="event_key")

    # ====================================================================
    # LIVE DNA KNOWLEDGE GRAPH IN SUPABASE POSTGRES
    # ====================================================================

    def record_customer_knowledge_graph(
        self,
        tenant_id: str,
        phone: str,
        message_text: str = "",
        profile: Optional[dict] = None,
        service_hint: str = "",
    ) -> bool:
        if not phone:
            return False
        tid = str(tenant_id or "default").strip()
        clean_phone = str(phone).replace("+", "").strip()
        cust_key = f"{tid}:customer:{clean_phone}"
        prof = profile or {}
        now_iso = _now_iso()

        contact_name = str(prof.get("contact_name") or "").strip() or clean_phone
        bname = str(prof.get("business_name") or "").strip()
        bcat = str(prof.get("business_category") or "").strip()
        area = str(prof.get("area") or "").strip()
        website_url = str(prof.get("website_url") or "").strip()
        has_site = str(prof.get("has_website") or "").strip()
        eco_str = str(prof.get("existing_ecosystem") or "").strip()
        eco_list = [x.strip() for x in eco_str.split(",") if x.strip()] if eco_str else []

        nodes: List[dict] = [
            {
                "node_key": cust_key,
                "tenant_id": tid,
                "label": "Customer",
                "name": contact_name,
                "meta": {"phone": clean_phone},
                "updated_at": now_iso,
            }
        ]
        edges: List[dict] = []

        def _add_edge(src_key: str, src_name: str, rel: str, tgt_key: str, tgt_name: str, tgt_label: str):
            edges.append({
                "edge_key": f"{src_key}|{rel}|{tgt_key}",
                "tenant_id": tid,
                "source_key": src_key,
                "source_name": src_name,
                "relation": rel,
                "target_key": tgt_key,
                "target_name": tgt_name,
                "target_label": tgt_label,
                "updated_at": now_iso,
            })

        if bname:
            biz_key = f"{tid}:biz:{_slug(bname)}"
            nodes.append({
                "node_key": biz_key,
                "tenant_id": tid,
                "label": "Business",
                "name": bname,
                "meta": {},
                "updated_at": now_iso,
            })
            _add_edge(cust_key, contact_name, "OWNS_BUSINESS", biz_key, bname, "Business")

            if bcat:
                cat_key = f"{tid}:cat:{_slug(bcat)}"
                nodes.append({
                    "node_key": cat_key,
                    "tenant_id": tid,
                    "label": "Category",
                    "name": bcat,
                    "meta": {},
                    "updated_at": now_iso,
                })
                _add_edge(biz_key, bname, "IN_CATEGORY", cat_key, bcat, "Category")

            if area:
                area_key = f"{tid}:area:{_slug(area)}"
                nodes.append({
                    "node_key": area_key,
                    "tenant_id": tid,
                    "label": "Area",
                    "name": area,
                    "meta": {},
                    "updated_at": now_iso,
                })
                _add_edge(biz_key, bname, "LOCATED_IN", area_key, area, "Area")

            if website_url or has_site:
                wlabel = website_url or f"website:{has_site}"
                web_key = f"{tid}:web:{_slug(wlabel)}"
                nodes.append({
                    "node_key": web_key,
                    "tenant_id": tid,
                    "label": "Website",
                    "name": wlabel,
                    "meta": {"url": website_url, "has_website": has_site},
                    "updated_at": now_iso,
                })
                _add_edge(biz_key, bname, "HAS_WEBSITE", web_key, wlabel, "Website")

            for tool_name in eco_list:
                tool_key = f"{tid}:tool:{_slug(tool_name)}"
                nodes.append({
                    "node_key": tool_key,
                    "tenant_id": tid,
                    "label": "EcosystemTool",
                    "name": tool_name,
                    "meta": {},
                    "updated_at": now_iso,
                })
                _add_edge(biz_key, bname, "USES_TOOL", tool_key, tool_name, "EcosystemTool")

        if service_hint and service_hint.strip():
            sh = service_hint.strip()
            svc_key = f"{tid}:svc:{_slug(sh)}"
            nodes.append({
                "node_key": svc_key,
                "tenant_id": tid,
                "label": "Service",
                "name": sh,
                "meta": {},
                "updated_at": now_iso,
            })
            _add_edge(cust_key, contact_name, "INQUIRED_ABOUT", svc_key, sh, "Service")

        ok = self._upsert("wa_graph_nodes", nodes, on_conflict="node_key")
        if edges:
            ok = self._upsert("wa_graph_edges", edges, on_conflict="edge_key") and ok

        if message_text and len(message_text.strip()) >= 3:
            ep_id = f"ep_{hashlib.sha256(f'{tid}:{clean_phone}:{message_text}:{now_iso}'.encode()).hexdigest()[:14]}"
            self._upsert(
                "wa_graph_episodes",
                {
                    "id": ep_id,
                    "tenant_id": tid,
                    "phone": clean_phone,
                    "content": message_text[:350],
                    "timestamp": now_iso,
                },
                on_conflict="id",
            )
        return ok

    def get_customer_subgraph(self, tenant_id: str, phone: str) -> Dict[str, Any]:
        tid = str(tenant_id or "default").strip()
        clean = str(phone or "").replace("+", "").strip()
        cust_key = f"{tid}:customer:{clean}"
        if not self._ensure_ready():
            return {"connected": False, "nodes": [], "edges": [], "episodes": [], "summary_prompt": ""}

        cust_nodes = self._select(
            "wa_graph_nodes",
            params={"tenant_id": f"eq.{tid}", "node_key": f"eq.{cust_key}", "limit": 1},
        )
        cust_name = (cust_nodes[0].get("name") if cust_nodes else "") or clean

        hop1 = self._select(
            "wa_graph_edges",
            params={"tenant_id": f"eq.{tid}", "source_key": f"eq.{cust_key}", "limit": 50},
        )
        target_keys = list({e["target_key"] for e in hop1 if e.get("target_key")})
        hop2: List[dict] = []
        if target_keys:
            hop2 = self._select(
                "wa_graph_edges",
                params={
                    "tenant_id": f"eq.{tid}",
                    "source_key": f"in.{_postgrest_in_list(target_keys)}",
                    "limit": 100,
                },
            )

        episodes = self._select(
            "wa_graph_episodes",
            params={
                "tenant_id": f"eq.{tid}",
                "phone": f"eq.{clean}",
                "order": "timestamp.desc",
                "limit": 5,
            },
            select="id,content,timestamp",
        )

        nodes_map: Dict[str, dict] = {
            cust_key: {"id": cust_key, "label": "Customer", "name": cust_name}
        }
        edges: List[dict] = []
        summary_lines: List[str] = []
        seen_edges = set()

        for row in hop1 + hop2:
            tkey = row.get("target_key") or ""
            tname = row.get("target_name") or ""
            tlabel = row.get("target_label") or "Entity"
            sname = row.get("source_name") or cust_name
            rel = row.get("relation") or ""
            if tkey and tkey not in nodes_map:
                nodes_map[tkey] = {"id": tkey, "label": tlabel, "name": tname}
            ek = (sname, rel, tname)
            if rel and tname and ek not in seen_edges:
                seen_edges.add(ek)
                edges.append({"source": sname, "relation": rel, "target": tname})
                summary_lines.append(f"- Graph Edge: ({sname})-[{rel}]->({tname})")

        summary_prompt = (
            "[SUPABASE LIVE KNOWLEDGE GRAPH RELATIONSHIPS]:\n" + "\n".join(summary_lines)
            if summary_lines
            else ""
        )

        return {
            "connected": True,
            "customer_key": cust_key,
            "nodes": list(nodes_map.values()),
            "edges": edges,
            "episodes": episodes,
            "summary_prompt": summary_prompt,
        }

    def query_tenant_graph(self, tenant_id: str, query: str = "", limit: int = 30) -> Dict[str, Any]:
        tid = str(tenant_id or "default").strip()
        q = (query or "").strip().lower()
        if not self._ensure_ready():
            return {"connected": False, "edges": [], "query": query}

        rows = self._select(
            "wa_graph_edges",
            params={"tenant_id": f"eq.{tid}", "order": "updated_at.desc", "limit": 150},
        )
        edges: List[dict] = []
        seen = set()
        for r in rows:
            src = r.get("source_name") or ""
            rel = r.get("relation") or ""
            tgt = r.get("target_name") or ""
            txt = f"{src} {rel} {tgt}".lower()
            if q and q not in txt:
                continue
            k = (src, rel, tgt)
            if k not in seen:
                seen.add(k)
                edges.append({
                    "source": src,
                    "relation": rel,
                    "target": tgt,
                    "target_type": r.get("target_label", ""),
                })
                if len(edges) >= limit:
                    break

        return {
            "connected": True,
            "tenant_id": tid,
            "query": query,
            "edges": edges,
        }

    # ====================================================================
    # STARTUP HYDRATION & MIGRATION (ZERO CHAT LOSS ON DEPLOY)
    # ====================================================================

    def _upsert_batches(self, table: str, rows: List[dict], on_conflict: str, chunk_size: int = 50) -> int:
        uploaded = 0
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i : i + chunk_size]
            if self._upsert(table, chunk, on_conflict=on_conflict):
                uploaded += len(chunk)
        return uploaded

    def hydrate_and_sync_sqlite(self, conn) -> Dict[str, int]:
        summary = {
            "restored_tenants": 0,
            "restored_messages": 0,
            "restored_profiles": 0,
            "restored_leads": 0,
            "backfilled": 0,
        }
        if not self._ensure_ready():
            return summary

        cur = conn.cursor()

        # 1. Tenants
        tenants = self._select_all("wa_tenants")
        for p in tenants:
            tid = p.get("tenant_id")
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
                        p.get("openrouter_api_key", ""),
                        p.get("openrouter_guard_model", "meta-llama/llama-guard-4-12b"),
                    ),
                )
                summary["restored_tenants"] += 1

        # 2. Messages
        msgs = self._select_all("wa_messages", order="id.asc")
        for p in msgs:
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
                    p.get("sender_name") or "User", p.get("message") or "",
                    p.get("direction") or "inbound", p.get("channel") or "meta_whatsapp",
                    p.get("status") or "received", p.get("raw_payload") or "",
                    p.get("ai_model") or None, float(p.get("latency_ms") or 0.0),
                    p.get("media_type") or None, p.get("media_url") or None,
                    p.get("media_filename") or None, p.get("created_at") or _now_iso(),
                ),
            )
            if cur.rowcount > 0:
                summary["restored_messages"] += 1

        # 3. Customer Profiles
        profs = self._select_all("wa_customer_profiles")
        for p in profs:
            phone = p.get("phone_number")
            if not phone:
                continue
            cur.execute(
                """
                INSERT OR IGNORE INTO customer_profiles (
                    phone_number, tenant_id, contact_name, business_name, business_category,
                    area, has_website, website_url, existing_ecosystem, pain_points, goals,
                    data_source, updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    phone, p.get("tenant_id") or "default", p.get("contact_name", ""),
                    p.get("business_name", ""), p.get("business_category", ""), p.get("area", ""),
                    p.get("has_website", ""), p.get("website_url", ""),
                    p.get("existing_ecosystem", ""), p.get("pain_points", ""),
                    p.get("goals", ""), p.get("data_source", ""),
                    p.get("updated_at") or _now_iso(), p.get("created_at") or _now_iso(),
                ),
            )
            if cur.rowcount > 0:
                summary["restored_profiles"] += 1

        # 4. Templates
        tpls = self._select_all("wa_templates")
        for p in tpls:
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

        # 5. Leads
        leads = self._select_all("wa_leads")
        for p in leads:
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

        # 6. Bookings, ContactSettings, BillingWindows, SecurityEvents
        for p in self._select_all("wa_bookings"):
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

        for p in self._select_all("wa_contact_settings"):
            if not p.get("phone_number"):
                continue
            cur.execute(
                "INSERT OR IGNORE INTO contact_settings (phone_number, tenant_id, bot_enabled) VALUES (?, ?, ?)",
                (p["phone_number"], p.get("tenant_id") or "default", int(p.get("bot_enabled", 1))),
            )

        for p in self._select_all("wa_billing_windows"):
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

        for p in self._select_all("wa_security_events"):
            if p.get("id") is None:
                continue
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO security_events (id, tenant_id, phone_number, input_text, detector, reason, blocked, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(p["id"]), p.get("tenant_id") or "default", p.get("phone_number") or "",
                        p.get("input_text") or "", p.get("detector") or "",
                        p.get("reason") or "", int(p.get("blocked", 1)),
                        p.get("created_at") or _now_iso(),
                    ),
                )
            except Exception:
                pass

        conn.commit()

        # 7. Batch-backfill local SQLite rows missing in Supabase
        local_tenants = [dict(r) for r in cur.execute("SELECT * FROM tenants").fetchall()]
        if len(local_tenants) > len(tenants):
            t_rows = [
                {
                    "tenant_id": str(t.get("tenant_id") or "default"),
                    "email": str(t.get("email") or ""),
                    "full_name": str(t.get("full_name") or ""),
                    "business_name": str(t.get("business_name") or ""),
                    "custom_system_prompt": str(t.get("custom_system_prompt") or ""),
                    "billing_mode": str(t.get("billing_mode") or "managed_meta"),
                    "plan_tier": str(t.get("plan_tier") or "payg"),
                    "plan_quota": int(t.get("plan_quota") or 0),
                    "plan_used": int(t.get("plan_used") or 0),
                    "plan_expires_at": str(t.get("plan_expires_at") or ""),
                    "demo_used": int(t.get("demo_used") or 0),
                    "whatsapp_token": str(t.get("whatsapp_token") or ""),
                    "whatsapp_phone_number_id": str(t.get("whatsapp_phone_number_id") or ""),
                    "whatsapp_verify_token": str(t.get("whatsapp_verify_token") or ""),
                    "deepseek_api_key": str(t.get("deepseek_api_key") or ""),
                    "deepseek_model": str(t.get("deepseek_model") or "deepseek-chat"),
                    "groq_api_key": str(t.get("groq_api_key") or ""),
                    "groq_model": str(t.get("groq_model") or "llama-3.3-70b-versatile"),
                    "openrouter_api_key": str(t.get("openrouter_api_key") or ""),
                    "openrouter_guard_model": str(t.get("openrouter_guard_model") or "meta-llama/llama-guard-4-12b"),
                    "updated_at": str(t.get("updated_at") or _now_iso()),
                }
                for t in local_tenants
            ]
            self._upsert_batches("wa_tenants", t_rows, on_conflict="tenant_id")

        local_msgs = [dict(r) for r in cur.execute("SELECT * FROM messages ORDER BY id ASC").fetchall()]
        if len(local_msgs) > len(msgs):
            existing_msg_keys = {f"{m.get('tenant_id') or 'default'}:{m.get('id')}" for m in msgs}
            missing_msgs = []
            for m in local_msgs:
                tid = str(m.get("tenant_id") or "default")
                mid = int(m["id"])
                key = f"{tid}:{mid}"
                if key not in existing_msg_keys:
                    missing_msgs.append({
                        "msg_key": key,
                        "id": mid,
                        "tenant_id": tid,
                        "phone_number": str(m.get("phone_number") or ""),
                        "sender_name": str(m.get("sender_name") or "User"),
                        "message": str(m.get("message") or ""),
                        "direction": str(m.get("direction") or "inbound"),
                        "channel": str(m.get("channel") or "meta_whatsapp"),
                        "status": str(m.get("status") or "received"),
                        "raw_payload": str(m.get("raw_payload") or "")[:4000],
                        "ai_model": str(m.get("ai_model") or ""),
                        "latency_ms": float(m.get("latency_ms") or 0.0),
                        "media_type": str(m.get("media_type") or ""),
                        "media_url": str(m.get("media_url") or ""),
                        "media_filename": str(m.get("media_filename") or ""),
                        "created_at": str(m.get("created_at") or _now_iso()),
                    })
            summary["backfilled"] += self._upsert_batches("wa_messages", missing_msgs, on_conflict="msg_key")

        local_profs = [dict(r) for r in cur.execute("SELECT * FROM customer_profiles").fetchall()]
        if len(local_profs) > len(profs):
            for r in local_profs:
                self.upsert_customer_profile_node(r.get("tenant_id") or "default", r)

        local_tpls = [dict(r) for r in cur.execute("SELECT * FROM templates").fetchall()]
        if len(local_tpls) > len(tpls):
            for r in local_tpls:
                self.save_template_node(r)

        local_leads = [dict(r) for r in cur.execute("SELECT * FROM leads").fetchall()]
        if len(local_leads) > len(leads):
            for r in local_leads:
                self.save_lead_node(r)

        return summary


supabase_store = SupabaseStore()


def get_cloud_store():
    """Return Supabase Postgres store by default, falling back to Neo4j only if Supabase URL is unset and Neo4j is set."""
    if os.getenv("WA_SUPABASE_URL", "").strip():
        return supabase_store
    if os.getenv("NEO4J_URI", "").strip() and os.getenv("NEO4J_PASSWORD", "").strip():
        try:
            from api.neo4j_store import neo4j_store
            return neo4j_store
        except Exception:
            pass
    return supabase_store
