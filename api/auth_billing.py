"""
Growhaz Multi-Tenant Authentication, Wallet Sync & Conversation Window Billing Engine.

- Authenticates users directly against Growhaz's Supabase Auth project (same email + password).
- Reads real Growhaz Coin balance (`coin_balances`) and deducts Coins (`spend_user_coins` RPC)
  using the user's verified Supabase JWT (1 Coin = ₹1).
- Enforces 24-hour customer conversation pricing:
    * Managed Meta + Infra: ₹2 / 24h conversation (₹1 Infra + ₹1 Meta)
      Monthly Plans: Starter ₹999 (600 convs) • Growth ₹2,499 (2,000 convs) • Pro ₹4,999 (5,000 convs)
    * Own Meta Account (Infra-Only): ₹1 / 24h conversation (50% cost)
      Monthly Plans: Starter ₹499 (600 convs) • Growth ₹1,199 (2,000 convs) • Pro ₹2,499 (5,000 convs)
- Grants 3 Free Demo conversations for new users before requiring Meta setup or Coins.
"""

import os
import time
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import httpx
from fastapi import Request, HTTPException

from api import db

logger = logging.getLogger("auth_billing")

DEFAULT_SUPABASE_URL = "https://hkigsjwppfbtkuqhaxsp.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhraWdzandwcGZidGt1cWhheHNwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjkxODY2MjEsImV4cCI6MjA4NDc2MjYyMX0."
    "wNueoaWZWlJY5TnQiZQKEfKwaSPhyt69X3M80ezO-Gc"
)

FREE_DEMO_LIMIT = 3
CONVERSATION_WINDOW_HOURS = 24
GROWHAZ_WALLET_URL = "https://www.growhaz.in/wallet"
GROWHAZ_MENTOR_SETUP_URL = "https://www.growhaz.in/mentorship?topic=meta-whatsapp-setup"

PAYG_RATES = {
    "managed_meta": 2,
    "byo_meta": 1,
}

PLANS: Dict[str, Dict[str, Any]] = {
    "starter": {
        "id": "starter",
        "name": "Starter",
        "quota": 600,
        "managed_meta_price": 999,
        "byo_meta_price": 499,
        "description": "Up to 600 unique 24-hour conversations / month",
    },
    "growth": {
        "id": "growth",
        "name": "Growth",
        "quota": 2000,
        "managed_meta_price": 2499,
        "byo_meta_price": 1199,
        "description": "Up to 2,000 unique 24-hour conversations / month",
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "quota": 5000,
        "managed_meta_price": 4999,
        "byo_meta_price": 2499,
        "description": "Up to 5,000 unique 24-hour conversations / month",
    },
}

# Short-lived in-memory cache of validated Supabase JWTs (keyed by sha256 hash)
_JWT_CACHE: Dict[str, Dict[str, Any]] = {}
_JWT_CACHE_TTL = 60.0


def _sb_url() -> str:
    return (os.getenv("SUPABASE_URL", DEFAULT_SUPABASE_URL) or DEFAULT_SUPABASE_URL).rstrip("/")


def _sb_anon() -> str:
    return (os.getenv("SUPABASE_ANON_KEY", DEFAULT_SUPABASE_ANON_KEY) or DEFAULT_SUPABASE_ANON_KEY).strip()


def _sb_headers(access_token: str = "") -> Dict[str, str]:
    h = {
        "apikey": _sb_anon(),
        "Content-Type": "application/json",
    }
    if access_token:
        h["Authorization"] = f"Bearer {access_token}"
    return h


def supabase_sign_in(email: str, password: str) -> Dict[str, Any]:
    url = f"{_sb_url()}/auth/v1/token?grant_type=password"
    with httpx.Client(timeout=15.0) as client:
        res = client.post(url, headers=_sb_headers(), json={"email": email.strip(), "password": password})
        data = res.json() if res.content else {}
        if res.status_code != 200:
            msg = data.get("error_description") or data.get("msg") or data.get("message") or "Invalid email or password"
            raise HTTPException(status_code=401, detail=msg)
        return data


def supabase_sign_up(email: str, password: str, full_name: str = "") -> Dict[str, Any]:
    url = f"{_sb_url()}/auth/v1/signup"
    payload = {
        "email": email.strip(),
        "password": password,
        "data": {"full_name": (full_name or email.split("@")[0]).strip()},
    }
    with httpx.Client(timeout=15.0) as client:
        res = client.post(url, headers=_sb_headers(), json=payload)
        data = res.json() if res.content else {}
        if res.status_code not in (200, 201):
            msg = data.get("error_description") or data.get("msg") or data.get("message") or "Registration failed"
            raise HTTPException(status_code=400, detail=msg)
        return data


def supabase_verify_jwt(access_token: str) -> Optional[Dict[str, Any]]:
    tok = (access_token or "").strip()
    if not tok or len(tok) < 20:
        return None

    thash = hashlib.sha256(tok.encode("utf-8")).hexdigest()
    cached = _JWT_CACHE.get(thash)
    if cached and (time.time() - cached["cached_at"]) < _JWT_CACHE_TTL:
        return cached["user"]

    url = f"{_sb_url()}/auth/v1/user"
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(url, headers=_sb_headers(tok))
            if res.status_code != 200:
                return None
            u = res.json()
            meta = u.get("user_metadata") or {}
            info = {
                "user_id": u.get("id", ""),
                "email": (u.get("email") or "").lower(),
                "full_name": meta.get("full_name") or meta.get("name") or (u.get("email") or "User").split("@")[0],
            }
            if not info["user_id"]:
                return None
            _JWT_CACHE[thash] = {"user": info, "cached_at": time.time()}
            return info
    except Exception as e:
        logger.warning(f"[Auth] Supabase JWT check error: {e}")
        return None


def supabase_check_is_admin(access_token: str, user_id: str, email: str) -> bool:
    owner_emails = {
        e.strip().lower()
        for e in os.getenv("OWNER_ADMIN_EMAIL", "info.growhaz@gmail.com,omuikey@gmail.com").split(",")
        if e.strip()
    }
    if email and email.lower() in owner_emails:
        return True

    url = f"{_sb_url()}/rest/v1/user_roles?user_id=eq.{user_id}&role=eq.admin&select=role"
    try:
        with httpx.Client(timeout=6.0) as client:
            res = client.get(url, headers=_sb_headers(access_token))
            if res.status_code == 200:
                rows = res.json()
                return isinstance(rows, list) and len(rows) > 0
    except Exception:
        pass
    return False


def supabase_get_coin_balance(access_token: str, user_id: str) -> Dict[str, Any]:
    url = f"{_sb_url()}/rest/v1/coin_balances?user_id=eq.{user_id}&select=balance,total_earned,total_spent"
    try:
        with httpx.Client(timeout=8.0) as client:
            res = client.get(url, headers=_sb_headers(access_token))
            if res.status_code == 200:
                rows = res.json()
                if isinstance(rows, list) and rows:
                    row = rows[0]
                    return {
                        "balance": float(row.get("balance") or 0),
                        "total_earned": float(row.get("total_earned") or 0),
                        "total_spent": float(row.get("total_spent") or 0),
                        "synced": True,
                    }
                return {"balance": 0.0, "total_earned": 0.0, "total_spent": 0.0, "synced": True}
    except Exception as e:
        logger.warning(f"[Wallet] Balance fetch warning: {e}")
    return {"balance": 0.0, "total_earned": 0.0, "total_spent": 0.0, "synced": False}


def supabase_spend_coins(access_token: str, user_id: str, amount: float, description: str) -> tuple[bool, str]:
    url = f"{_sb_url()}/rest/v1/rpc/spend_user_coins"
    payload = {
        "p_user_id": user_id,
        "p_amount": amount,
        "p_description": description,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(url, headers=_sb_headers(access_token), json=payload)
            if res.status_code in (200, 204):
                return True, "OK"
            err = ""
            try:
                err = res.json().get("message") or res.text
            except Exception:
                err = res.text
            return False, err or f"HTTP {res.status_code}"
    except Exception as e:
        return False, str(e)


def extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Growhaz-Token", "").strip()


def resolve_tenant_from_request(request: Request, require_auth: bool = True) -> Optional[Dict[str, Any]]:
    tok = extract_bearer_token(request)
    if not tok:
        if require_auth:
            raise HTTPException(status_code=401, detail="Please sign in with your Growhaz account.")
        return None

    user = supabase_verify_jwt(tok)
    if not user:
        if require_auth:
            raise HTTPException(status_code=401, detail="Session expired. Please sign in again with your Growhaz account.")
        return None

    is_admin = supabase_check_is_admin(tok, user["user_id"], user["email"])
    sandbox_self = request.headers.get("X-Tenant-Sandbox", "").lower() == "self"
    workspace_id = "default" if (is_admin and not sandbox_self) else user["user_id"]

    tenant = db.ensure_tenant(
        tenant_id=workspace_id,
        email=user["email"],
        full_name=user["full_name"],
    )
    tenant["is_admin"] = is_admin
    tenant["supabase_user_id"] = user["user_id"]
    tenant["access_token"] = tok
    return tenant


def get_effective_billing_mode(tenant: dict) -> str:
    has_own_meta = bool((tenant.get("whatsapp_token") or "").strip() and (tenant.get("whatsapp_phone_number_id") or "").strip())
    mode = (tenant.get("billing_mode") or "managed_meta").strip()
    if mode == "byo_meta" and has_own_meta:
        return "byo_meta"
    return "managed_meta" if mode != "byo_meta" else "byo_meta"


def get_billing_summary(tenant: dict, access_token: str = "") -> Dict[str, Any]:
    tid = tenant["tenant_id"]
    is_admin = bool(tenant.get("is_admin"))
    sb_uid = tenant.get("supabase_user_id") or tid
    tok = access_token or tenant.get("access_token") or ""

    wallet = supabase_get_coin_balance(tok, sb_uid) if tok else {"balance": 0.0, "total_earned": 0.0, "total_spent": 0.0, "synced": False}
    has_own_meta = bool((tenant.get("whatsapp_token") or "").strip() and (tenant.get("whatsapp_phone_number_id") or "").strip())
    has_env_meta = bool(os.getenv("WHATSAPP_TOKEN", "").strip() and os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip())
    default_mode = "byo_meta" if (has_own_meta or (is_admin and has_env_meta)) else "managed_meta"
    mode = (tenant.get("billing_mode") or default_mode).strip()
    if mode == "managed_meta" and is_admin and has_env_meta and not tenant.get("plan_tier"):
        mode = "byo_meta"
    if mode not in ("managed_meta", "byo_meta"):
        mode = "managed_meta"

    demo_used = int(tenant.get("demo_used") or 0)
    demo_remaining = max(0, FREE_DEMO_LIMIT - demo_used)

    plan_tier = (tenant.get("plan_tier") or "payg").strip()
    plan_quota = int(tenant.get("plan_quota") or 0)
    plan_used = int(tenant.get("plan_used") or 0)
    plan_expires = tenant.get("plan_expires_at") or ""
    plan_active = False
    if plan_tier in PLANS and plan_expires:
        try:
            exp_dt = datetime.fromisoformat(plan_expires.replace("Z", "+00:00"))
            plan_active = exp_dt > datetime.now(timezone.utc)
        except Exception:
            plan_active = False

    unit_rate = PAYG_RATES[mode]

    return {
        "tenant_id": tid,
        "email": tenant.get("email", ""),
        "full_name": tenant.get("full_name", ""),
        "is_admin": is_admin,
        "wallet": wallet,
        "billing_mode": mode,
        "unit_cost_coins": unit_rate,
        "has_own_meta": has_own_meta,
        "managed_meta_available": has_env_meta,
        "meta_configured": has_own_meta or (is_admin and has_env_meta),
        "needs_meta_setup": (not has_own_meta) and (not is_admin),
        "demo_limit": FREE_DEMO_LIMIT,
        "demo_used": demo_used,
        "demo_remaining": demo_remaining,
        "plan": {
            "tier": plan_tier if plan_active else "payg",
            "active": plan_active,
            "quota": plan_quota if plan_active else 0,
            "used": plan_used if plan_active else 0,
            "remaining": max(0, plan_quota - plan_used) if plan_active else 0,
            "expires_at": plan_expires if plan_active else "",
        },
        "plans_catalog": PLANS,
        "wallet_url": GROWHAZ_WALLET_URL,
        "mentor_setup_url": GROWHAZ_MENTOR_SETUP_URL,
    }


def estimate_send_billing(tenant: dict, phones: List[str], access_token: str = "") -> Dict[str, Any]:
    tid = tenant["tenant_id"]
    summary = get_billing_summary(tenant, access_token=access_token)
    clean_phones = []
    seen = set()
    for p in phones:
        norm = db.normalize_phone_key(p) or str(p or "").replace("+", "").strip()
        if norm and norm not in seen:
            seen.add(norm)
            clean_phones.append(norm)

    active_count = 0
    new_needed = 0
    for p in clean_phones:
        if db.is_billing_window_active(tid, p):
            active_count += 1
        else:
            new_needed += 1

    rem_demo = summary["demo_remaining"] if not summary["has_own_meta"] and not summary["is_admin"] else 0
    demo_covered = min(new_needed, rem_demo)
    after_demo = max(0, new_needed - demo_covered)

    plan_rem = summary["plan"]["remaining"] if summary["plan"]["active"] else 0
    plan_covered = min(after_demo, plan_rem)
    billable_new = max(0, after_demo - plan_covered)

    unit_cost = summary["unit_cost_coins"]
    total_coins = billable_new * unit_cost
    wallet_bal = summary["wallet"]["balance"]

    return {
        "total_recipients": len(clean_phones),
        "already_active_24h": active_count,
        "demo_covered": demo_covered,
        "plan_covered": plan_covered,
        "billable_new_windows": billable_new,
        "unit_cost_coins": summary["unit_cost_coins"],
        "total_coins_required": total_coins,
        "wallet_balance": wallet_bal,
        "can_afford": wallet_bal >= total_coins,
        "billing_mode": summary["billing_mode"],
        "meta_configured": summary["meta_configured"],
        "demo_remaining": summary["demo_remaining"],
    }


def charge_and_open_window(
    tenant: dict,
    phone_number: str,
    access_token: str = "",
    is_demo_channel: bool = False,
) -> Dict[str, Any]:
    """
    Validate & charge for opening (or reusing) a 24-hour conversation window for `phone_number`.
    Order:
      1. Already active 24h billing window -> ₹0
      2. If admin owner workspace -> ₹0 (tracked)
      3. If user hasn't connected Meta yet and demo_used < 3 -> consumes 1 Free Demo (₹0)
      4. If active monthly plan with remaining quota -> consumes 1 plan slot (₹0 extra)
      5. Otherwise deducts ₹2 (Managed Meta) or ₹1 (Own Meta) Coin via Growhaz Wallet RPC
    """
    tid = tenant["tenant_id"]
    norm_phone = db.normalize_phone_key(phone_number) or str(phone_number or "").replace("+", "").strip()
    if not norm_phone:
        return {"allowed": False, "code": "INVALID_PHONE", "message": "Invalid phone number."}

    # 1. Active 24h billing window already paid
    if db.is_billing_window_active(tid, norm_phone):
        return {"allowed": True, "charged": 0, "source": "active_24h_window"}

    mode = (tenant.get("billing_mode") or "managed_meta").strip()
    if mode not in PAYG_RATES:
        mode = "managed_meta"
    has_own_meta = bool((tenant.get("whatsapp_token") or "").strip() and (tenant.get("whatsapp_phone_number_id") or "").strip())
    has_env_meta = bool(os.getenv("WHATSAPP_TOKEN", "").strip() and os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip())
    is_admin = bool(tenant.get("is_admin"))
    if mode == "managed_meta" and is_admin and has_env_meta and not tenant.get("plan_tier"):
        mode = "byo_meta"

    now_dt = datetime.now(timezone.utc)
    exp_dt = now_dt + timedelta(hours=CONVERSATION_WINDOW_HOURS)

    # 2. Simulator / demo channel without Meta credentials (free preview only)
    if is_demo_channel and is_admin:
        db.record_billing_window(tid, norm_phone, mode, 0, "simulator_preview", now_dt.isoformat(), exp_dt.isoformat())
        return {"allowed": True, "charged": 0, "source": "simulator_preview"}

    # 3. Free 3-Demo trial when user has not connected their own Meta account yet
    demo_used = int(tenant.get("demo_used") or 0)
    if not (has_own_meta or (is_admin and has_env_meta)) and demo_used < FREE_DEMO_LIMIT:
        new_demo = db.increment_tenant_demo_used(tid)
        tenant["demo_used"] = new_demo
        db.record_billing_window(tid, norm_phone, mode, 0, "free_demo", now_dt.isoformat(), exp_dt.isoformat())
        return {
            "allowed": True,
            "charged": 0,
            "source": "free_demo",
            "demo_remaining": max(0, FREE_DEMO_LIMIT - new_demo),
        }

    # If BYO Meta mode selected for real Meta sending without credentials after 3 demos
    if mode == "byo_meta" and not has_own_meta and not is_demo_channel:
        return {
            "allowed": False,
            "code": "SETUP_META_REQUIRED",
            "message": (
                "Your 3 Free Demos are used! Connect your Meta WhatsApp Token & Phone Number ID in Settings "
                "to send on your Own Meta plan (₹1/conv), or book a 1-on-1 Mentor Setup session on Growhaz."
            ),
            "mentor_setup_url": GROWHAZ_MENTOR_SETUP_URL,
        }

    # 4. Active monthly plan quota
    plan_tier = (tenant.get("plan_tier") or "payg").strip()
    plan_quota = int(tenant.get("plan_quota") or 0)
    plan_used = int(tenant.get("plan_used") or 0)
    plan_expires = tenant.get("plan_expires_at") or ""
    if plan_tier in PLANS and plan_expires and plan_used < plan_quota:
        try:
            if datetime.fromisoformat(plan_expires.replace("Z", "+00:00")) > now_dt:
                new_used = db.increment_tenant_plan_used(tid)
                tenant["plan_used"] = new_used
                db.record_billing_window(tid, norm_phone, mode, 0, f"plan:{plan_tier}", now_dt.isoformat(), exp_dt.isoformat())
                return {
                    "allowed": True,
                    "charged": 0,
                    "source": f"plan:{plan_tier}",
                    "plan_remaining": max(0, plan_quota - new_used),
                }
        except Exception:
            pass

    # 5. Pay-As-You-Go Growhaz Wallet Coin deduction (₹2 Managed / ₹1 Own Meta)
    unit_cost = PAYG_RATES[mode]
    sb_uid = tenant.get("supabase_user_id") or tid
    tok = access_token or tenant.get("access_token") or ""
    if not tok:
        return {
            "allowed": False,
            "code": "WALLET_AUTH_REQUIRED",
            "message": "Please sign in with your Growhaz account to use wallet coins.",
        }

    ok, msg = supabase_spend_coins(
        tok,
        sb_uid,
        unit_cost,
        f"WhatsApp 24h conversation ({mode}) for +{norm_phone}",
    )
    if not ok:
        bal = supabase_get_coin_balance(tok, sb_uid).get("balance", 0)
        return {
            "allowed": False,
            "code": "INSUFFICIENT_COINS",
            "needed": unit_cost,
            "balance": bal,
            "billing_mode": mode,
            "wallet_url": GROWHAZ_WALLET_URL,
            "message": (
                f"Insufficient Growhaz Coins (need ₹{unit_cost} / {unit_cost} coin{'s' if unit_cost > 1 else ''}, "
                f"current balance: {bal:.0f}). Add coins on Growhaz Wallet first!"
            ),
        }

    db.record_billing_window(tid, norm_phone, mode, unit_cost, "wallet_coins", now_dt.isoformat(), exp_dt.isoformat())
    return {
        "allowed": True,
        "charged": unit_cost,
        "source": "wallet_coins",
    }


def subscribe_tenant_plan(tenant: dict, plan_id: str, billing_mode: str, access_token: str = "") -> Dict[str, Any]:
    pid = (plan_id or "").strip().lower()
    if pid not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan selected. Choose starter, growth, or pro.")

    mode = (billing_mode or tenant.get("billing_mode") or "managed_meta").strip()
    if mode not in ("managed_meta", "byo_meta"):
        raise HTTPException(status_code=400, detail="Invalid billing_mode. Choose managed_meta or byo_meta.")

    plan = PLANS[pid]
    price_coins = plan["byo_meta_price"] if mode == "byo_meta" else plan["managed_meta_price"]
    quota = plan["quota"]

    sb_uid = tenant.get("supabase_user_id") or tenant["tenant_id"]
    tok = access_token or tenant.get("access_token") or ""
    is_admin = bool(tenant.get("is_admin"))

    if not is_admin:
        if not tok:
            raise HTTPException(status_code=401, detail="Authentication required.")
        ok, err_msg = supabase_spend_coins(
            tok,
            sb_uid,
            price_coins,
            f"Growhaz WhatsApp {plan['name']} Plan ({mode}, {quota} convs/mo)",
        )
        if not ok:
            bal = supabase_get_coin_balance(tok, sb_uid).get("balance", 0)
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient Growhaz Coins: need {price_coins} Coins (₹{price_coins}), wallet has {bal:.0f}. Please add coins on Growhaz Wallet ({GROWHAZ_WALLET_URL}).",
            )

    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    updated = db.update_tenant_plan(
        tenant_id=tenant["tenant_id"],
        billing_mode=mode,
        plan_tier=pid,
        plan_quota=quota,
        plan_expires_at=expires_at,
    )
    return {
        "success": True,
        "message": f"Activated {plan['name']} Plan ({mode}, {quota} convs/30 days)!",
        "billing": get_billing_summary(updated | {"is_admin": is_admin, "supabase_user_id": sb_uid, "access_token": tok}, tok),
    }
