import os
import re
import json
import time
import hmac
import hashlib
import asyncio
import logging
import httpx
from fastapi import FastAPI, Request, Response, Form, Query, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv, set_key

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

load_dotenv(ENV_PATH)

# Import internal modules AFTER loading .env so Supabase Cloud URL & keys are immediately available
try:
    from api import db
    from api.bot_engine import generate_ai_reply
    from api.dna_service import dynamic_dna
    from api.supabase_store import get_cloud_store
    from api import security_guard
    from api import auth_billing
    from api import webhook_runtime
    from api import voice_service
    from api.whatsapp_service import (
        get_env_var,
        send_meta_whatsapp_message,
        send_meta_typing_indicator,
        upload_meta_media,
        send_meta_whatsapp_media,
        download_meta_media,
        UPLOAD_DIR,
    )
except ImportError:
    import db
    from bot_engine import generate_ai_reply
    from dna_service import dynamic_dna
    from supabase_store import get_cloud_store
    import security_guard
    import auth_billing
    import webhook_runtime
    import voice_service
    from whatsapp_service import (
        get_env_var,
        send_meta_whatsapp_message,
        send_meta_typing_indicator,
        upload_meta_media,
        send_meta_whatsapp_media,
        download_meta_media,
        UPLOAD_DIR,
    )

neo4j_store = get_cloud_store()

db.init_db()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp_support_bot")

app = FastAPI(title="Growhaz • Multi-Tenant WhatsApp AI SaaS & CRM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and uploaded media
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

SERVER_START_TIME = time.time()

# In-memory typing status tracker scoped by (tenant_id, phone)
ACTIVE_TYPING_CHATS: dict[str, float] = {}


def _typing_key(phone: str, tenant_id: str = "default") -> str:
    key = db.normalize_phone_key(phone) or str(phone or "").replace("+", "").strip()
    tid = str(tenant_id or "default").strip() or "default"
    return f"{tid}:{key}" if key else ""


def set_typing_state(phone: str, active: bool, tenant_id: str = "default"):
    tkey = _typing_key(phone, tenant_id)
    if not tkey:
        return
    if active:
        ACTIVE_TYPING_CHATS[tkey] = time.time()
    else:
        ACTIVE_TYPING_CHATS.pop(tkey, None)


def is_chat_typing(phone: str, tenant_id: str = "default") -> bool:
    tkey = _typing_key(phone, tenant_id)
    if not tkey:
        return False
    ts = ACTIVE_TYPING_CHATS.get(tkey)
    if not ts:
        return False
    if (time.time() - ts) > 30.0:
        ACTIVE_TYPING_CHATS.pop(tkey, None)
        return False
    return True


def _resolve_tenant_credentials(tenant: dict) -> dict:
    """Resolve effective AI + Meta + OpenRouter Guard credentials for a tenant without leaking platform keys."""
    tid = str((tenant or {}).get("tenant_id") or "default")
    is_admin = bool((tenant or {}).get("is_admin")) or tid == "default"

    deepseek_key = (tenant.get("deepseek_api_key") or "").strip()
    if not deepseek_key or deepseek_key.startswith("sk_your"):
        deepseek_key = get_env_var("DEEPSEEK_API_KEY")
    deepseek_model = (tenant.get("deepseek_model") or get_env_var("DEEPSEEK_MODEL", "deepseek-chat")).strip()

    groq_key = (tenant.get("groq_api_key") or "").strip()
    if not groq_key or groq_key.startswith("gsk_your"):
        groq_key = get_env_var("GROQ_API_KEY")
    groq_model = (tenant.get("groq_model") or get_env_var("GROQ_MODEL", "llama-3.3-70b-versatile")).strip()

    openrouter_key = (tenant.get("openrouter_api_key") or get_env_var("OPENROUTER_API_KEY")).strip()
    openrouter_guard_model = (tenant.get("openrouter_guard_model") or get_env_var("OPENROUTER_GUARD_MODEL", security_guard.DEFAULT_GUARD_MODEL)).strip()

    own_wa_token = (tenant.get("whatsapp_token") or "").strip()
    own_wa_phone_id = (tenant.get("whatsapp_phone_number_id") or "").strip()
    own_verify_token = (tenant.get("whatsapp_verify_token") or "").strip()

    billing_mode = (tenant.get("billing_mode") or "managed_meta").strip()
    if own_wa_token and own_wa_phone_id:
        wa_token = own_wa_token
        wa_phone_id = own_wa_phone_id
        has_own_meta = True
    elif is_admin or billing_mode == "managed_meta":
        wa_token = get_env_var("WHATSAPP_TOKEN")
        wa_phone_id = get_env_var("WHATSAPP_PHONE_NUMBER_ID")
        has_own_meta = False
    else:
        wa_token = ""
        wa_phone_id = ""
        has_own_meta = False

    verify_token = own_verify_token or get_env_var("WHATSAPP_VERIFY_TOKEN", "")
    own_secret = (tenant.get("meta_app_secret") or "").strip()
    app_secret = own_secret or (get_env_var("META_APP_SECRET", "") if (is_admin or not has_own_meta) else "")
    return {
        "tenant_id": tid,
        "deepseek_api_key": deepseek_key,
        "deepseek_model": deepseek_model,
        "groq_api_key": groq_key,
        "groq_model": groq_model,
        "openrouter_api_key": openrouter_key,
        "openrouter_guard_model": openrouter_guard_model,
        "whatsapp_token": wa_token,
        "whatsapp_phone_number_id": wa_phone_id,
        "whatsapp_verify_token": verify_token,
        "meta_app_secret": app_secret,
        "has_own_meta": has_own_meta,
    }


def _pick_real_recipient_name(explicit_name: str, profile: dict, phone_key: str) -> str:
    """Choose best human/business name without falling back to 'Customer' or 'Lead #N'."""
    for candidate in (
        explicit_name,
        profile.get("contact_name", "") if profile else "",
        profile.get("business_name", "") if profile else "",
    ):
        val = str(candidate or "").strip()
        if not val:
            continue
        low = val.lower()
        if low in {"customer", "lead", "user", "unknown", "business", "business lead", "valued business", "there"}:
            continue
        if re.match(r"^(lead|business|unnamed lead|contact)\s*#?\d+$", low):
            continue
        if val.isdigit() or val == phone_key:
            continue
        return val
    return ""


def render_template_placeholders(
    text: str,
    phone: str = "",
    explicit_name: str = "",
    profile: dict = None,
    tenant_id: str = "default",
) -> str:
    """Resolve {{name}}, {{business}}, {{area}}, {{phone}}, {{service}}, {{date_time}} per recipient."""
    raw = str(text or "")
    if "{{" not in raw:
        return raw

    phone_key = db.normalize_phone_key(phone) if phone else ""
    clean_phone = phone_key or re.sub(r"\D", "", str(phone or ""))
    prof = profile if profile is not None else (db.get_customer_profile(phone, tenant_id=tenant_id) if phone else {})

    resolved_name = _pick_real_recipient_name(explicit_name, prof, clean_phone) or "there"
    resolved_business = (
        prof.get("business_name")
        if db._is_meaningful_profile_val(prof.get("business_name", ""), "business_name")
        else (resolved_name if resolved_name != "there" else "your business")
    )
    resolved_area = (
        prof.get("area")
        if db._is_meaningful_profile_val(prof.get("area", ""), "area")
        else "your area"
    )
    resolved_category = (
        prof.get("business_category")
        if db._is_meaningful_profile_val(prof.get("business_category", ""), "business_category")
        else "business"
    )

    out = re.sub(r"\{\{\s*(?:name|customer_name|user_name)\s*\}\}", lambda _m: resolved_name, raw, flags=re.IGNORECASE)
    out = re.sub(r"\{\{\s*(?:business|business_name|company|company_name)\s*\}\}", lambda _m: resolved_business, out, flags=re.IGNORECASE)
    out = re.sub(r"\{\{\s*(?:area|city|locality|location)\s*\}\}", lambda _m: resolved_area, out, flags=re.IGNORECASE)
    out = re.sub(r"\{\{\s*(?:category|business_category|industry)\s*\}\}", lambda _m: resolved_category, out, flags=re.IGNORECASE)
    out = re.sub(r"\{\{\s*phone\s*\}\}", lambda _m: clean_phone, out, flags=re.IGNORECASE)
    out = re.sub(r"\{\{\s*service\s*\}\}", lambda _m: "Website, App & WhatsApp Automation", out, flags=re.IGNORECASE)
    out = re.sub(r"\{\{\s*(?:date_time|datetime|date)\s*\}\}", lambda _m: "your preferred time", out, flags=re.IGNORECASE)
    return out


def get_ai_reply(
    prompt: str,
    customer_id: str = "",
    tenant: Optional[dict] = None,
    channel: str = "whatsapp",
    sender_name: str = "",
    is_voice: bool = False,
) -> tuple[str, float, str]:
    """Route AI responses through Fail-Safe Security Shield -> Agent Guardrails -> DNA Graph -> DeepSeek/Groq -> Sanitizer."""
    tcfg = tenant or {"tenant_id": "default"}
    creds = _resolve_tenant_credentials(tcfg)
    return generate_ai_reply(
        user_prompt=prompt,
        deepseek_api_key=creds["deepseek_api_key"],
        deepseek_model=creds["deepseek_model"],
        groq_api_key=creds["groq_api_key"],
        groq_model=creds["groq_model"],
        customer_id=customer_id,
        tenant_id=creds["tenant_id"],
        tenant_config=tcfg,
        openrouter_api_key=creds["openrouter_api_key"],
        openrouter_guard_model=creds["openrouter_guard_model"],
        channel=channel,
        sender_name=sender_name,
        is_voice=is_voice,
    )


@app.get("/api/health")
@app.get("/health")
async def health_check():
    """Health check endpoint for Render, UptimeRobot, and cron services."""
    cloud = get_cloud_store().get_status()
    return JSONResponse({
        "status": "healthy",
        "service": "growhaz-whatsapp-saas",
        "provider": cloud.get("provider", "supabase"),
        "cloud_connected": cloud.get("connected", False),
        "neo4j_connected": cloud.get("connected", False),
        "cloud_error": cloud.get("error"),
        "openrouter_guard_configured": bool(get_env_var("OPENROUTER_API_KEY")),
        "security_fail_closed": os.getenv("SECURITY_FAIL_CLOSED", "true").strip().lower() not in {"0", "false", "no"},
        "webhook_signature_enforced": bool(get_env_var("META_APP_SECRET")) or os.getenv("WEBHOOK_SIGNATURE_REQUIRED", "false").lower() in {"1", "true", "yes"},
        "queue": webhook_runtime.webhook_queue.get_stats(),
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 1),
        "timestamp": int(time.time()),
    })


async def keep_alive_worker():
    """Background task that pings both this service and dna-modal every 4 minutes so Render never sleeps."""
    await asyncio.sleep(30)
    while True:
        try:
            render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
            base_url = (
                (f"https://{render_hostname}" if render_hostname else None)
                or os.getenv("RENDER_EXTERNAL_URL")
                or os.getenv("APP_URL")
                or "https://whatsapp-bot-qtm1.onrender.com"
            ).rstrip("/")
            dna_url = (os.getenv("DNA_API_URL") or "https://dna-modal.onrender.com").strip().rstrip("/")

            targets = []
            if "localhost" not in base_url and "127.0.0.1" not in base_url:
                targets.append(f"{base_url}/api/health")
            if dna_url and "localhost" not in dna_url and "127.0.0.1" not in dna_url:
                targets.append(f"{dna_url}/ping")

            if targets:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    results = await asyncio.gather(*(client.get(u) for u in targets), return_exceptions=True)
                    for u, res in zip(targets, results):
                        if isinstance(res, Exception):
                            logger.warning(f"[Keep-Alive] Ping failed for {u}: {res}")
                        else:
                            logger.info(f"[Keep-Alive] Heartbeat {u} -> {res.status_code}")
        except Exception as e:
            logger.warning(f"[Keep-Alive] Warning: keep-alive loop error: {e}")
        await asyncio.sleep(240)


@app.on_event("startup")
async def startup_tasks():
    # Restore persistent chats, tenants, profiles, templates & billing from Supabase Cloud DB
    sync_summary = await asyncio.to_thread(db.sync_with_neo4j_on_boot)
    logger.info(f"[Startup] Cloud DB sync summary: {sync_summary}")
    webhook_runtime.webhook_queue.set_handler(_process_meta_webhook_job)
    await webhook_runtime.webhook_queue.start()
    asyncio.create_task(keep_alive_worker())


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ====================================================================
# 0. GROWHAZ AUTHENTICATION & BILLING / WALLET ENDPOINTS
# ====================================================================

@app.post("/api/auth/login")
async def auth_login(request: Request):
    allowed, retry_after = webhook_runtime.rate_limiter.allow(f"auth_login:{_client_ip(request)}", max_calls=20, window_sec=60)
    if not allowed:
        return JSONResponse({"error": f"Too many login attempts. Retry in {retry_after}s."}, status_code=429)
    data = await request.json()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        return JSONResponse({"error": "Email and password are required."}, status_code=400)

    sb_res = await asyncio.to_thread(auth_billing.supabase_sign_in, email, password)
    access_token = sb_res.get("access_token", "")
    user = await asyncio.to_thread(auth_billing.supabase_verify_jwt, access_token)
    if not user:
        return JSONResponse({"error": "Failed to verify Growhaz session."}, status_code=401)

    is_admin = await asyncio.to_thread(auth_billing.supabase_check_is_admin, access_token, user["user_id"], user["email"])
    workspace_id = "default" if is_admin else user["user_id"]
    tenant = db.ensure_tenant(workspace_id, email=user["email"], full_name=user["full_name"])
    tenant.update({"is_admin": is_admin, "supabase_user_id": user["user_id"], "access_token": access_token})
    billing = await asyncio.to_thread(auth_billing.get_billing_summary, tenant, access_token)

    return JSONResponse({
        "success": True,
        "access_token": access_token,
        "user": {**user, "is_admin": is_admin},
        "billing": billing,
    })


@app.post("/api/auth/register")
async def auth_register(request: Request):
    allowed, retry_after = webhook_runtime.rate_limiter.allow(f"auth_reg:{_client_ip(request)}", max_calls=15, window_sec=60)
    if not allowed:
        return JSONResponse({"error": f"Too many registration attempts. Retry in {retry_after}s."}, status_code=429)
    data = await request.json()
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or len(password) < 6:
        return JSONResponse({"error": "Valid email and password (min 6 characters) are required."}, status_code=400)

    sb_res = await asyncio.to_thread(auth_billing.supabase_sign_up, email, password, full_name)
    access_token = sb_res.get("access_token") or (sb_res.get("session") or {}).get("access_token") or ""
    if not access_token:
        return JSONResponse({
            "success": True,
            "needs_email_verification": True,
            "message": "Account created on Growhaz! Please check your email to verify your account, then sign in.",
        })

    user = await asyncio.to_thread(auth_billing.supabase_verify_jwt, access_token)
    tenant = db.ensure_tenant(user["user_id"], email=user["email"], full_name=user["full_name"])
    tenant.update({"is_admin": False, "supabase_user_id": user["user_id"], "access_token": access_token})
    billing = await asyncio.to_thread(auth_billing.get_billing_summary, tenant, access_token)

    return JSONResponse({
        "success": True,
        "access_token": access_token,
        "user": {**user, "is_admin": False},
        "billing": billing,
    })


@app.post("/api/auth/sso")
async def auth_sso(request: Request):
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    tok = (data.get("access_token") or auth_billing.extract_bearer_token(request) or "").strip()
    if not tok:
        raise HTTPException(status_code=401, detail="Missing Growhaz SSO token.")
    user = await asyncio.to_thread(auth_billing.supabase_verify_jwt, tok)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired Growhaz session.")

    is_admin = await asyncio.to_thread(auth_billing.supabase_check_is_admin, tok, user["user_id"], user["email"])
    workspace_id = "default" if is_admin else user["user_id"]
    tenant = db.ensure_tenant(workspace_id, email=user["email"], full_name=user["full_name"])
    tenant.update({"is_admin": is_admin, "supabase_user_id": user["user_id"], "access_token": tok})
    billing = await asyncio.to_thread(auth_billing.get_billing_summary, tenant, tok)

    return JSONResponse({
        "success": True,
        "access_token": tok,
        "user": {**user, "is_admin": is_admin},
        "billing": billing,
    })


@app.get("/api/auth/me")
async def auth_me(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    billing = await asyncio.to_thread(auth_billing.get_billing_summary, tenant, tenant.get("access_token", ""))
    return JSONResponse({
        "success": True,
        "user": {
            "user_id": tenant.get("supabase_user_id"),
            "tenant_id": tenant.get("tenant_id"),
            "email": tenant.get("email"),
            "full_name": tenant.get("full_name"),
            "is_admin": tenant.get("is_admin", False),
        },
        "billing": billing,
    })


@app.get("/api/billing/status")
async def billing_status(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    summary = await asyncio.to_thread(auth_billing.get_billing_summary, tenant, tenant.get("access_token", ""))
    return JSONResponse({"success": True, "billing": summary})


@app.post("/api/billing/mode")
async def billing_update_mode(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    mode = (data.get("billing_mode") or "").strip()
    if mode not in ("managed_meta", "byo_meta"):
        return JSONResponse({"error": "Invalid billing_mode. Must be 'managed_meta' or 'byo_meta'."}, status_code=400)
    updated = db.update_tenant_settings(tenant["tenant_id"], billing_mode=mode)
    updated.update({"is_admin": tenant.get("is_admin"), "supabase_user_id": tenant.get("supabase_user_id"), "access_token": tenant.get("access_token")})
    summary = await asyncio.to_thread(auth_billing.get_billing_summary, updated, tenant.get("access_token", ""))
    return JSONResponse({"success": True, "billing": summary})


@app.post("/api/billing/subscribe")
async def billing_subscribe(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    plan_id = (data.get("plan_id") or "").strip()
    mode = (data.get("billing_mode") or tenant.get("billing_mode") or "managed_meta").strip()
    res = await asyncio.to_thread(auth_billing.subscribe_tenant_plan, tenant, plan_id, mode, tenant.get("access_token", ""))
    return JSONResponse(res)


@app.post("/api/billing/estimate")
async def billing_estimate(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    phones = data.get("phone_numbers") or []
    if isinstance(phones, str):
        phones = [p.strip() for p in re.split(r"[\n,;]+", phones) if p.strip()]
    est = await asyncio.to_thread(auth_billing.estimate_send_billing, tenant, phones, tenant.get("access_token", ""))
    return JSONResponse({"success": True, "estimate": est})


# ====================================================================
# 1. WEBHOOKS (META CLOUD API & TWILIO — TENANT AWARE)
# ====================================================================

async def _verify_meta_webhook_impl(
    tenant_id: str,
    hub_mode: str,
    hub_verify_token: str,
    hub_challenge: str,
):
    received_token = (hub_verify_token or "").strip().strip('"').strip("'")
    tenant = db.find_tenant_for_webhook(tenant_id=tenant_id, verify_token=received_token)
    tid = tenant.get("tenant_id", "default")
    expected_token = (tenant.get("whatsapp_verify_token") or get_env_var("WHATSAPP_VERIFY_TOKEN", "")).strip()
    is_valid = bool(received_token and expected_token and webhook_runtime.hmac.compare_digest(received_token, expected_token))
    if not is_valid and tid == "default":
        env_tok = (get_env_var("WHATSAPP_VERIFY_TOKEN", "") or "").strip()
        is_valid = bool(received_token and env_tok and webhook_runtime.hmac.compare_digest(received_token, env_tok))

    db.save_webhook_log(
        endpoint=f"/api/webhook/{tid}" if tenant_id else "/api/webhook",
        method="GET",
        payload={"hub.mode": hub_mode, "hub.verify_token": "***", "hub.challenge": hub_challenge},
        status_code=200 if (hub_mode == "subscribe" and is_valid) else 403,
        tenant_id=tid,
    )

    if hub_mode == "subscribe" and is_valid:
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    return PlainTextResponse(content="Forbidden: Verification token mismatch or unconfigured", status_code=403)


async def _process_meta_webhook_job(job: dict):
    """Background worker handler executed with exponential-backoff retries + DLQ."""
    tid = str(job.get("tenant_id") or "default")
    tenant = db.get_tenant(tid)
    creds = _resolve_tenant_credentials(tenant)
    incoming_phone_id = str(job.get("incoming_phone_id") or "")
    sender_name = str(job.get("sender_name") or "Customer")
    msg = dict(job.get("msg") or {})
    msg_type = msg.get("type")
    sender_id = str(msg.get("from") or "")
    if not sender_id:
        return

    user_text = ""
    media_type = None
    media_url = None
    media_filename = None
    is_voice = False
    voice_unclear_reply = ""

    if msg_type == "text":
        user_text = msg.get("text", {}).get("body", "").strip()
    elif msg_type == "image":
        media_type = "image"
        img_data = msg.get("image", {})
        user_text = img_data.get("caption", "").strip()
        media_id = img_data.get("id")
        if media_id:
            media_url, media_filename, _ = await asyncio.to_thread(
                download_meta_media, media_id, ".jpg", creds["whatsapp_token"]
            )
        if not user_text:
            user_text = "📷 [Photo Received]"
    elif msg_type == "document":
        media_type = "document"
        doc_data = msg.get("document", {})
        user_text = doc_data.get("caption", "").strip()
        media_id = doc_data.get("id")
        orig_fname = doc_data.get("filename", "")
        if media_id:
            media_url, media_filename, _ = await asyncio.to_thread(
                download_meta_media, media_id, ".pdf", creds["whatsapp_token"]
            )
        if orig_fname:
            media_filename = orig_fname
        if not user_text:
            user_text = f"📄 [Document: {media_filename or 'File'}]"
    elif msg_type == "audio":
        media_type = "audio"
        is_voice = True
        aud_data = msg.get("audio", {})
        media_id = aud_data.get("id")
        if media_id:
            media_url, media_filename, _ = await asyncio.to_thread(
                download_meta_media, media_id, ".ogg", creds["whatsapp_token"]
            )
        if media_filename:
            local_audio = os.path.join(UPLOAD_DIR, media_filename)
            tx = await asyncio.to_thread(voice_service.transcribe_audio_with_groq, local_audio, creds["groq_api_key"])
            if tx.get("ok") and tx.get("text"):
                user_text = tx["text"].strip()
            else:
                voice_unclear_reply = (
                    "🎤 I couldn't hear that voice message clearly (or transcription confidence was low). "
                    "Could you please type your message or send a clearer audio note?"
                )
                user_text = f"🎤 [Voice Note: {media_filename}]"
        else:
            user_text = "🎤 [Voice Note Received]"
            voice_unclear_reply = "🎤 Received your voice note, though I couldn't download it cleanly. Could you type your inquiry?"

    db.save_message(
        phone_number=sender_id,
        sender_name=sender_name,
        message=user_text,
        direction="inbound",
        channel="meta_whatsapp",
        raw_payload=msg,
        media_type=media_type,
        media_url=media_url,
        media_filename=media_filename,
        tenant_id=tid,
    )
    if sender_name and sender_name.strip().lower() not in {"customer", "user", "unknown"}:
        db.upsert_customer_profile(
            sender_id,
            overwrite_existing=False,
            tenant_id=tid,
            contact_name=sender_name.strip(),
            data_source="whatsapp_chat",
        )

    bot_active = db.is_bot_enabled_for_contact(sender_id, tenant_id=tid)
    if not bot_active:
        return

    incoming_wamid = msg.get("id")
    target_phone_id = incoming_phone_id or creds["whatsapp_phone_number_id"]
    if incoming_wamid and creds["whatsapp_token"]:
        try:
            await asyncio.to_thread(send_meta_typing_indicator, incoming_wamid, target_phone_id, creds["whatsapp_token"])
        except Exception as _te:
            logger.debug(f"Typing indicator warning: {_te}")

    set_typing_state(sender_id, True, tenant_id=tid)
    try:
        if media_type in ("image", "document"):
            reply = (
                f"Thank you for sharing your {media_type}! 📄\n\n"
                f"We have received your file at *{tenant.get('business_name') or 'Growhaz'}*. "
                "Our team is reviewing it and will update you shortly."
            )
            latency_ms = 0.0
            engine_used = "Growhaz Assistant"
        elif voice_unclear_reply:
            reply = voice_unclear_reply
            latency_ms = 0.0
            engine_used = "Voice Pipeline (Clarification)"
        else:
            try:
                dynamic_dna.record_interaction(
                    customer_id=f"{tid}:{sender_id}",
                    action="received_message",
                    target_id="chat_interaction",
                    attributes={"snippet": user_text[:60]},
                )
            except Exception:
                pass
            reply, latency_ms, engine_used = await asyncio.to_thread(
                get_ai_reply,
                user_text,
                sender_id,
                tenant,
                "meta_whatsapp",
                sender_name,
                is_voice,
            )
    finally:
        set_typing_state(sender_id, False, tenant_id=tid)

    success, send_res = await asyncio.to_thread(
        send_meta_whatsapp_message,
        sender_id,
        reply,
        target_phone_id,
        creds["whatsapp_token"],
    )

    db.save_message(
        phone_number=sender_id,
        sender_name="Support Agent (AI)",
        message=reply,
        direction="outbound",
        channel="meta_whatsapp",
        status="sent" if success else "failed",
        raw_payload=send_res,
        ai_model=engine_used,
        latency_ms=latency_ms,
        tenant_id=tid,
    )


webhook_runtime.webhook_queue.set_handler(_process_meta_webhook_job)


async def _handle_meta_webhook_impl(request: Request, explicit_tenant_id: str = ""):
    ip_ok, retry_after = webhook_runtime.rate_limiter.allow(
        f"webhook_ip:{_client_ip(request)}", max_calls=120, window_sec=60
    )
    if not ip_ok:
        return JSONResponse({"error": f"Rate limit exceeded. Retry in {retry_after}s."}, status_code=429)

    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as e:
        db.save_webhook_log(
            endpoint="/api/webhook",
            method="POST",
            payload=str(e),
            status_code=400,
            tenant_id=explicit_tenant_id or "default",
        )
        return JSONResponse({"status": "invalid json"}, status_code=400)

    # Identify tenant for HMAC signature check
    first_phone_id = ""
    try:
        entries = body.get("entry", [])
        if entries:
            changes = entries[0].get("changes", [])
            if changes:
                first_phone_id = (changes[0].get("value", {}).get("metadata", {}).get("phone_number_id") or "").strip()
    except Exception:
        first_phone_id = ""

    pre_tenant = db.find_tenant_for_webhook(tenant_id=explicit_tenant_id, phone_number_id=first_phone_id)
    pre_tid = pre_tenant.get("tenant_id", "default")
    pre_creds = _resolve_tenant_credentials(pre_tenant)
    sig_required = os.getenv("WEBHOOK_SIGNATURE_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}
    app_secret = pre_creds.get("meta_app_secret", "")

    if app_secret or sig_required:
        sig_hdr = request.headers.get("X-Hub-Signature-256", "")
        if sig_required and not app_secret:
            return JSONResponse({"error": "Webhook signature verification required but META_APP_SECRET is not configured."}, status_code=403)
        sig_ok, sig_reason = webhook_runtime.verify_meta_signature(raw_body, sig_hdr, app_secret)
        if not sig_ok:
            db.save_security_event(pre_tid, "meta_webhook", f"Rejected webhook POST: {sig_reason}", "X-Hub-Signature-256", sig_reason, True)
            db.log_action_audit(pre_tid, _client_ip(request), "webhook_signature_check", "rejected", "high", "", {"reason": sig_reason})
            return JSONResponse({"error": sig_reason}, status_code=403)

    webhook_runtime.webhook_queue.set_handler(_process_meta_webhook_job)
    try:
        entries = body.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                val = change.get("value", {})
                metadata = val.get("metadata", {})
                incoming_phone_id = (metadata.get("phone_number_id") or "").strip()

                tenant = db.find_tenant_for_webhook(tenant_id=explicit_tenant_id, phone_number_id=incoming_phone_id)
                tid = tenant.get("tenant_id", "default")
                if tid == "default" and incoming_phone_id:
                    os.environ["WHATSAPP_PHONE_NUMBER_ID"] = incoming_phone_id

                db.save_webhook_log(
                    endpoint=f"/api/webhook/{tid}" if explicit_tenant_id else "/api/webhook",
                    method="POST",
                    payload=body,
                    status_code=200,
                    tenant_id=tid,
                )

                contacts = val.get("contacts", [])
                sender_name = contacts[0].get("profile", {}).get("name", "Customer") if contacts else "Customer"

                for msg in val.get("messages", []):
                    msg_type = msg.get("type")
                    if msg_type in ["text", "image", "document", "audio"]:
                        sender_id = msg.get("from")
                        if not sender_id:
                            continue

                        event_id = str(msg.get("id") or hashlib.sha256(json.dumps(msg, sort_keys=True).encode()).hexdigest()[:24])
                        if not db.claim_webhook_event(tid, event_id, sender_id):
                            logger.info(f"[Webhook Dedup] Skipping duplicate message event {event_id} for tenant={tid}")
                            continue

                        s_ok, _ = webhook_runtime.rate_limiter.allow(
                            f"wh_sender:{tid}:{sender_id}", max_calls=30, window_sec=60
                        )
                        if not s_ok:
                            db.log_action_audit(tid, sender_id, "webhook_sender_rate_limit", "throttled", "medium", sender_id, {"event_id": event_id})
                            continue

                        await webhook_runtime.webhook_queue.enqueue({
                            "tenant_id": tid,
                            "incoming_phone_id": incoming_phone_id,
                            "sender_name": sender_name,
                            "event_id": event_id,
                            "phone_number": sender_id,
                            "msg": msg,
                        })
    except Exception as err:
        logger.error(f"Error handling Meta WhatsApp webhook: {err}")

    return JSONResponse({"status": "success"}, status_code=200)


@app.get("/api/webhook")
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    return await _verify_meta_webhook_impl("", hub_mode, hub_verify_token, hub_challenge)


@app.get("/api/webhook/{tenant_id}")
@app.get("/webhook/{tenant_id}")
async def verify_tenant_webhook(
    tenant_id: str,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    return await _verify_meta_webhook_impl(tenant_id, hub_mode, hub_verify_token, hub_challenge)


@app.post("/api/webhook")
@app.post("/webhook")
async def handle_meta_webhook(request: Request):
    return await _handle_meta_webhook_impl(request, "")


@app.post("/api/webhook/{tenant_id}")
@app.post("/webhook/{tenant_id}")
async def handle_tenant_meta_webhook(tenant_id: str, request: Request):
    return await _handle_meta_webhook_impl(request, tenant_id)


@app.post("/api/twilio")
async def handle_twilio_webhook(From: str = Form(None), Body: str = Form(None), ProfileName: str = Form("Customer")):
    user_text = (Body or "").strip()
    sender_id = (From or "unknown").replace("whatsapp:", "")
    tid = "default"
    tenant = db.get_tenant(tid)

    db.save_webhook_log(endpoint="/api/twilio", method="POST", payload={"From": From, "Body": Body, "ProfileName": ProfileName}, tenant_id=tid)

    if not user_text:
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")

    db.save_message(phone_number=sender_id, sender_name=ProfileName, message=user_text, direction="inbound", channel="twilio", tenant_id=tid)
    if ProfileName and ProfileName.strip().lower() not in {"customer", "user", "unknown"}:
        db.upsert_customer_profile(sender_id, overwrite_existing=False, tenant_id=tid, contact_name=ProfileName.strip(), data_source="twilio")

    bot_active = db.is_bot_enabled_for_contact(sender_id, tenant_id=tid)
    reply = "Your message has been received by our support team."
    engine_used = "Support Desk"
    latency_ms = 0.0

    if bot_active:
        set_typing_state(sender_id, True, tenant_id=tid)
        try:
            reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, user_text, sender_id, tenant)
        finally:
            set_typing_state(sender_id, False, tenant_id=tid)

    db.save_message(phone_number=sender_id, sender_name="Support Agent (AI)", message=reply, direction="outbound", channel="twilio", status="sent", ai_model=engine_used, latency_ms=latency_ms, tenant_id=tid)

    escaped = reply.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escaped}</Message></Response>', media_type="application/xml")


# ====================================================================
# 2. TENANT DASHBOARD DATA, KNOWLEDGE GRAPH, SECURITY, & ACTIONS
# ====================================================================

@app.get("/api/dashboard/stats")
async def get_dashboard_stats(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    creds = _resolve_tenant_credentials(tenant)
    stats = db.get_stats(tenant_id=tid)
    stats["deepseek_configured"] = bool(creds["deepseek_api_key"] and not creds["deepseek_api_key"].startswith("sk_your"))
    stats["deepseek_model"] = creds["deepseek_model"]
    stats["groq_configured"] = bool(creds["groq_api_key"] and not creds["groq_api_key"].startswith("gsk_your"))
    stats["groq_model"] = creds["groq_model"]
    stats["meta_configured"] = bool(creds["whatsapp_token"] and creds["whatsapp_phone_number_id"])
    stats["openrouter_guard_configured"] = bool(creds["openrouter_api_key"])
    stats["openrouter_guard_model"] = creds["openrouter_guard_model"]
    stats["neo4j"] = neo4j_store.get_status(tenant_id=tid)
    return JSONResponse(stats)


@app.get("/api/dashboard/conversations")
async def get_conversations(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    convs = db.get_conversations(tenant_id=tid)
    for c in convs:
        c["is_typing"] = is_chat_typing(c.get("phone_number", ""), tenant_id=tid)
    return JSONResponse({"conversations": convs})


@app.get("/api/dashboard/messages")
async def get_messages(request: Request, phone: str = Query(None), limit: int = Query(200)):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    messages = db.get_messages(phone_number=phone, limit=limit, tenant_id=tid)
    bot_enabled = db.is_bot_enabled_for_contact(phone, tenant_id=tid) if phone else True
    is_typing = is_chat_typing(phone, tenant_id=tid) if phone else False
    profile = db.get_customer_profile(phone, tenant_id=tid) if phone else None
    return JSONResponse({
        "messages": messages,
        "phone": phone,
        "bot_enabled": bot_enabled,
        "is_typing": is_typing,
        "customer_profile": profile,
    })


@app.get("/api/dashboard/dna/{phone}")
async def get_customer_dna(phone: str, request: Request):
    """Retrieves customer's dynamic DNA predictions, Neo4j subgraph, and relational bonds."""
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    try:
        clean_phone = phone.strip()
        scoped_id = f"{tid}:{clean_phone}"
        pred = dynamic_dna.predict_customer_behavior(scoped_id)
        facts = dynamic_dna.decode_customer_facts(scoped_id)
        neo_sub = await asyncio.to_thread(neo4j_store.get_customer_subgraph, tid, clean_phone)

        rels_data = []
        if dynamic_dna.system:
            rels = dynamic_dna.system.relation_registry.retrieve_relations(subject_id=scoped_id)
            for r in rels:
                rels_data.append({
                    "id": r.id,
                    "subject": r.subject_id,
                    "relation_type": r.relation_type,
                    "object": r.object_id,
                    "confidence": r.confidence,
                    "strength": r.strength,
                    "timestamp": r.timestamp,
                })

        return JSONResponse({
            "success": True,
            "dna": {"prediction": pred, "facts": facts, "relations": rels_data},
            "neo4j_graph": neo_sub,
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/api/dashboard/graph/status")
async def get_graph_status(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    neo_status = await asyncio.to_thread(neo4j_store.get_status, tid)
    dna_atoms = dynamic_dna.system.dna_registry.count() if dynamic_dna.system else 0
    dna_assemblies = dynamic_dna.system.assembly_engine.count() if dynamic_dna.system else 0
    return JSONResponse({
        "success": True,
        "neo4j": neo_status,
        "dna_memory": {"atoms": dna_atoms, "assemblies": dna_assemblies},
    })


@app.get("/api/dashboard/graph/customer/{phone}")
async def get_graph_customer(phone: str, request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    sub = await asyncio.to_thread(neo4j_store.get_customer_subgraph, tid, phone)
    profile = db.get_customer_profile(phone, tenant_id=tid)
    return JSONResponse({"success": True, "profile": profile, "graph": sub})


@app.post("/api/dashboard/graph/query")
async def query_graph(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    data = await request.json()
    query = (data.get("query") or "").strip()
    res = await asyncio.to_thread(neo4j_store.query_tenant_graph, tid, query, 35)
    dna_hits = dynamic_dna.search_related_concepts(query, top_k=5) if query else []
    return JSONResponse({"success": True, "neo4j": res, "dna_matches": dna_hits})


@app.get("/api/dashboard/security-events")
async def list_security_events(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    creds = _resolve_tenant_credentials(tenant)
    events = db.get_security_events(tenant_id=tid, limit=30)
    return JSONResponse({
        "success": True,
        "openrouter_configured": bool(creds["openrouter_api_key"]),
        "guard_model": creds["openrouter_guard_model"],
        "events": events,
    })


@app.get("/api/dashboard/audit-logs")
async def list_audit_logs(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    audits = db.get_action_audits(tenant_id=tenant["tenant_id"], limit=50)
    return JSONResponse({"success": True, "audits": audits})


@app.get("/api/dashboard/dead-letters")
async def list_dead_letters(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    jobs = db.get_dead_letter_jobs(tenant_id=tenant["tenant_id"], limit=30)
    return JSONResponse({"success": True, "jobs": jobs, "queue": webhook_runtime.webhook_queue.get_stats()})


@app.post("/api/dashboard/test-guard")
async def test_prompt_guard(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    creds = _resolve_tenant_credentials(tenant)
    data = await request.json()
    text = (data.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Text to inspect is required."}, status_code=400)

    res = await asyncio.to_thread(
        security_guard.evaluate_user_input,
        text,
        creds["openrouter_api_key"],
        creds["openrouter_guard_model"],
    )
    if res.get("blocked"):
        db.save_security_event(tid, "security_tester", text, res.get("detector", "Guard"), res.get("reason", ""), True)
    return JSONResponse({"success": True, **res})


@app.get("/api/dashboard/templates")
async def get_templates(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    return JSONResponse({"templates": db.get_templates(tenant_id=tenant["tenant_id"])})


@app.post("/api/dashboard/templates")
async def add_template(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    t_id = db.save_template(
        title=data.get("title", "Custom Template"),
        category=data.get("category", "General"),
        content=data.get("content", ""),
        shortcut=data.get("shortcut", ""),
        tenant_id=tenant["tenant_id"],
    )
    return JSONResponse({"success": bool(t_id), "id": t_id})


@app.delete("/api/dashboard/templates")
async def delete_template(request: Request, id: int = Query(...)):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    success = db.delete_template(id, tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success})


@app.post("/api/dashboard/contact/bot-toggle")
async def toggle_contact_bot(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    phone = data.get("phone", "")
    enabled = bool(data.get("enabled", True))
    success = db.set_bot_enabled_for_contact(phone, enabled, tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success, "phone": phone, "bot_enabled": enabled})


@app.get("/api/dashboard/bookings")
async def get_bookings(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    return JSONResponse({"bookings": db.get_bookings(tenant_id=tenant["tenant_id"])})


@app.post("/api/dashboard/bookings/update")
async def update_booking(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    success = db.update_booking_status(data.get("id"), data.get("status"), tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success})


@app.post("/api/dashboard/bookings/add")
async def add_booking(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    b_id = db.add_manual_booking(
        phone_number=data.get("phone", ""),
        customer_name=data.get("name", "Customer"),
        service=data.get("service", "General Support"),
        date_time=data.get("date_time", "Pending Schedule"),
        status=data.get("status", "confirmed"),
        notes=data.get("notes", ""),
        tenant_id=tenant["tenant_id"],
    )
    return JSONResponse({"success": bool(b_id), "id": b_id})


@app.post("/api/dashboard/trigger-ai-reply")
async def trigger_ai_reply(request: Request):
    """Force generate an AI bot reply to a specific customer's latest message."""
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    data = await request.json()
    phone = (data.get("phone") or "").strip()
    prompt = (data.get("prompt") or "").strip()

    if not prompt and phone:
        msgs = db.get_messages(phone_number=phone, limit=5, tenant_id=tid)
        inbounds = [m for m in msgs if m["direction"] == "inbound"]
        if inbounds:
            prompt = inbounds[-1]["message"]

    if not prompt:
        prompt = "Hello! How can customer support help me today?"

    set_typing_state(phone, True, tenant_id=tid)
    try:
        reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, prompt, phone, tenant)
    finally:
        set_typing_state(phone, False, tenant_id=tid)

    msg_id = None
    if phone:
        msg_id = db.save_message(
            phone_number=phone,
            sender_name="Support Agent (AI)",
            message=reply,
            direction="outbound",
            channel="meta_whatsapp",
            status="sent",
            ai_model=engine_used,
            latency_ms=latency_ms,
            tenant_id=tid,
        )

    return JSONResponse({
        "success": True,
        "message_id": msg_id,
        "reply": reply,
        "engine": engine_used,
        "latency_ms": latency_ms,
    })


@app.post("/api/dashboard/send")
async def send_dashboard_reply(request: Request):
    """Send or simulate a dashboard message (enforcing 3 free demos + 24h billing window)."""
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    ok_rate, retry_sec = webhook_runtime.rate_limiter.allow(f"dash_send:{tid}", max_calls=60, window_sec=60)
    if not ok_rate:
        return JSONResponse({"error": f"Send rate limit exceeded. Retry in {retry_sec}s."}, status_code=429)
    creds = _resolve_tenant_credentials(tenant)

    data = await request.json()
    phone = (data.get("phone") or "+14155550199").strip()
    customer_name = (data.get("name") or "Customer").strip()
    msg_input = (data.get("message") or "").strip()
    role = data.get("role", "customer")
    send_via_meta = bool(data.get("send_via_meta", False))

    if not phone or not msg_input:
        return JSONResponse({"error": "Phone number and message text are required."}, status_code=400)

    is_demo_channel = not (send_via_meta and creds["whatsapp_token"] and creds["whatsapp_phone_number_id"])
    bill = await asyncio.to_thread(
        auth_billing.charge_and_open_window,
        tenant,
        phone,
        tenant.get("access_token", ""),
        is_demo_channel=is_demo_channel,
    )
    if not bill.get("allowed"):
        return JSONResponse(bill, status_code=402)

    # Case 1: Customer Simulator turn
    if role == "customer":
        inbound_id = db.save_message(
            phone_number=phone,
            sender_name=customer_name,
            message=msg_input,
            direction="inbound",
            channel="simulator",
            status="received",
            tenant_id=tid,
        )
        if customer_name and customer_name.lower() not in {"customer", "user", "unknown"}:
            db.upsert_customer_profile(phone, overwrite_existing=False, tenant_id=tid, contact_name=customer_name, data_source="simulator")

        bot_active = db.is_bot_enabled_for_contact(phone, tenant_id=tid)
        ai_reply = ""
        latency_ms = 0.0
        engine_used = ""
        outbound_id = None

        if bot_active:
            set_typing_state(phone, True, tenant_id=tid)
            try:
                ai_reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, msg_input, phone, tenant)
            finally:
                set_typing_state(phone, False, tenant_id=tid)

            outbound_id = db.save_message(
                phone_number=phone,
                sender_name="Support Agent (AI)",
                message=ai_reply,
                direction="outbound",
                channel="simulator",
                status="sent",
                ai_model=engine_used,
                latency_ms=latency_ms,
                tenant_id=tid,
            )

        return JSONResponse({
            "success": True,
            "inbound_id": inbound_id,
            "outbound_id": outbound_id,
            "customer_message": msg_input,
            "ai_reply": ai_reply,
            "engine": engine_used,
            "latency_ms": latency_ms,
            "billing": bill,
        })

    # Case 2: Agent or AI Reply
    if role == "ai":
        set_typing_state(phone, True, tenant_id=tid)
        try:
            reply_body, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, msg_input, phone, tenant)
        finally:
            set_typing_state(phone, False, tenant_id=tid)
        sender_name = "Support Agent (AI)"
    else:
        reply_body = render_template_placeholders(msg_input, phone=phone, explicit_name=customer_name, tenant_id=tid)
        latency_ms = 0.0
        engine_used = None
        sender_name = tenant.get("business_name") or "Growhaz Support"
        db.set_bot_enabled_for_contact(phone, False, tenant_id=tid)

    status = "sent"
    meta_payload = {}
    if send_via_meta:
        success, meta_res = await asyncio.to_thread(
            send_meta_whatsapp_message,
            phone,
            reply_body,
            creds["whatsapp_phone_number_id"],
            creds["whatsapp_token"],
        )
        status = "sent" if success else "failed"
        meta_payload = {"meta_api_response": meta_res}

    msg_id = db.save_message(
        phone_number=phone,
        sender_name=sender_name,
        message=reply_body,
        direction="outbound",
        channel="manual_admin" if role != "ai" else "meta_whatsapp",
        status=status,
        raw_payload=meta_payload,
        ai_model=engine_used,
        latency_ms=latency_ms,
        tenant_id=tid,
    )

    return JSONResponse({
        "success": True,
        "message_id": msg_id,
        "phone": phone,
        "message": reply_body,
        "engine": engine_used,
        "status": status,
        "latency_ms": latency_ms,
        "billing": bill,
    })


@app.post("/api/dashboard/send-media")
async def send_dashboard_media(
    request: Request,
    phone: str = Form(...),
    caption: str = Form(""),
    media_type: str = Form("image"),
    send_via_meta: bool = Form(True),
    file: UploadFile = File(None),
    media_url: str = Form(None),
):
    """Send photo or document to customer from dashboard."""
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    creds = _resolve_tenant_credentials(tenant)

    phone = (phone or "").strip()
    caption = (caption or "").strip()
    if not phone:
        return JSONResponse({"error": "Phone number is required"}, status_code=400)

    is_demo_channel = not (send_via_meta and creds["whatsapp_token"] and creds["whatsapp_phone_number_id"])
    bill = await asyncio.to_thread(auth_billing.charge_and_open_window, tenant, phone, tenant.get("access_token", ""), is_demo_channel)
    if not bill.get("allowed"):
        return JSONResponse(bill, status_code=402)

    filename = ""
    saved_url = media_url or ""
    mime_type = "application/octet-stream"
    meta_id = None
    meta_payload = {}
    status = "sent"

    if file and file.filename:
        filename = file.filename
        mime_type = file.content_type or ("image/jpeg" if media_type == "image" else "application/pdf")
        contents = await file.read()

        clean_fname = f"{int(time.time())}_{filename.replace(' ', '_')}"
        local_path = os.path.join(UPLOAD_DIR, clean_fname)
        with open(local_path, "wb") as f:
            f.write(contents)
        saved_url = f"/uploads/{clean_fname}"

        if send_via_meta and creds["whatsapp_token"] and creds["whatsapp_phone_number_id"]:
            meta_id = upload_meta_media(contents, filename, mime_type, phone_id=creds["whatsapp_phone_number_id"], token=creds["whatsapp_token"])

    if not saved_url and not meta_id:
        return JSONResponse({"error": "Please provide a file or media URL"}, status_code=400)

    if send_via_meta:
        success, meta_res = send_meta_whatsapp_media(
            recipient_number=phone,
            media_type=media_type,
            media_id=meta_id,
            media_link=saved_url if not meta_id and saved_url.startswith("http") else None,
            caption=caption,
            filename=filename or ("document.pdf" if media_type == "document" else "image.jpg"),
            phone_id=creds["whatsapp_phone_number_id"],
            token=creds["whatsapp_token"],
        )
        status = "sent" if success else "failed"
        meta_payload = {"meta_api_response": meta_res}

    display_msg = caption if caption else ("📷 Photo" if media_type == "image" else f"📄 Document: {filename or 'File'}")
    msg_id = db.save_message(
        phone_number=phone,
        sender_name=tenant.get("business_name") or "Growhaz Support",
        message=display_msg,
        direction="outbound",
        channel="manual_admin",
        status=status,
        raw_payload=meta_payload,
        media_type=media_type,
        media_url=saved_url,
        media_filename=filename,
        tenant_id=tid,
    )

    db.set_bot_enabled_for_contact(phone, False, tenant_id=tid)

    return JSONResponse({
        "success": True,
        "message_id": msg_id,
        "phone": phone,
        "media_type": media_type,
        "media_url": saved_url,
        "media_filename": filename,
        "caption": caption,
        "status": status,
        "billing": bill,
    })


@app.post("/api/dashboard/simulate-inbound")
async def simulate_inbound(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    data = await request.json()
    phone = (data.get("phone") or "+14155550199").strip()
    name = (data.get("name") or "Sarah Jenkins").strip()
    user_msg = (data.get("message") or "Hi! I need help with a website security scan.").strip()
    auto_reply = data.get("auto_reply", True)

    bill = await asyncio.to_thread(auth_billing.charge_and_open_window, tenant, phone, tenant.get("access_token", ""), is_demo_channel=True)
    if not bill.get("allowed"):
        return JSONResponse(bill, status_code=402)

    in_id = db.save_message(
        phone_number=phone,
        sender_name=name,
        message=user_msg,
        direction="inbound",
        channel="simulator",
        status="received",
        tenant_id=tid,
    )
    if name and name.lower() not in {"customer", "user", "unknown"}:
        db.upsert_customer_profile(phone, overwrite_existing=False, tenant_id=tid, contact_name=name, data_source="simulator")

    out_id = None
    ai_reply = ""
    latency_ms = 0.0
    engine_used = ""

    bot_active = db.is_bot_enabled_for_contact(phone, tenant_id=tid)
    if auto_reply and bot_active:
        set_typing_state(phone, True, tenant_id=tid)
        try:
            ai_reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, user_msg, phone, tenant)
        finally:
            set_typing_state(phone, False, tenant_id=tid)

        out_id = db.save_message(
            phone_number=phone,
            sender_name="Support Agent (AI)",
            message=ai_reply,
            direction="outbound",
            channel="simulator",
            status="sent",
            ai_model=engine_used,
            latency_ms=latency_ms,
            tenant_id=tid,
        )

    return JSONResponse({
        "success": True,
        "inbound_id": in_id,
        "outbound_id": out_id,
        "phone": phone,
        "user_message": user_msg,
        "ai_reply": ai_reply,
        "engine": engine_used,
        "latency_ms": latency_ms,
        "billing": bill,
    })


@app.post("/api/dashboard/test-ai")
async def test_ai_endpoint(request: Request):
    """Test AI bot reply (including OpenRouter security guard & Neo4j graph)."""
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    creds = _resolve_tenant_credentials(tenant)
    data = await request.json()
    prompt = data.get("prompt", "Hello, what services does Growhaz provide?")
    phone = (data.get("phone") or "").strip()
    reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, prompt, phone, tenant)
    return JSONResponse({
        "prompt": prompt,
        "reply": reply,
        "engine": engine_used,
        "latency_ms": latency_ms,
        "deepseek_configured": bool(creds["deepseek_api_key"] and not creds["deepseek_api_key"].startswith("sk_your")),
        "groq_configured": bool(creds["groq_api_key"] and not creds["groq_api_key"].startswith("gsk_your")),
    })


@app.get("/api/dashboard/settings")
async def get_settings(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    is_admin = bool(tenant.get("is_admin"))

    def _mask(k: str) -> str:
        val = (k or "").strip()
        if not val:
            return ""
        return (val[:4] + "..." + val[-4:]) if len(val) > 8 else "Configured"

    own_ds = (tenant.get("deepseek_api_key") or "").strip()
    own_groq = (tenant.get("groq_api_key") or "").strip()
    own_wa = (tenant.get("whatsapp_token") or "").strip()
    own_or = (tenant.get("openrouter_api_key") or "").strip()
    own_app_sec = (tenant.get("meta_app_secret") or "").strip()

    if is_admin:
        own_ds = own_ds or get_env_var("DEEPSEEK_API_KEY")
        own_groq = own_groq or get_env_var("GROQ_API_KEY")
        own_wa = own_wa or get_env_var("WHATSAPP_TOKEN")
        own_or = own_or or get_env_var("OPENROUTER_API_KEY")
        own_app_sec = own_app_sec or get_env_var("META_APP_SECRET")

    base_url = (get_env_var("APP_URL") or str(request.base_url)).rstrip("/")
    webhook_url = f"{base_url}/api/webhook" if tid == "default" else f"{base_url}/api/webhook/{tid}"

    return JSONResponse({
        "tenant_id": tid,
        "is_admin": is_admin,
        "business_name": tenant.get("business_name") or "",
        "custom_system_prompt": tenant.get("custom_system_prompt") or "",
        "billing_mode": tenant.get("billing_mode") or "managed_meta",
        "webhook_url": webhook_url,
        "deepseek_api_key_set": bool(own_ds and not own_ds.startswith("sk_your")),
        "deepseek_api_key_masked": _mask(own_ds),
        "deepseek_model": tenant.get("deepseek_model") or get_env_var("DEEPSEEK_MODEL", "deepseek-chat"),
        "groq_api_key_set": bool(own_groq and not own_groq.startswith("gsk_your")),
        "groq_api_key_masked": _mask(own_groq),
        "groq_model": tenant.get("groq_model") or get_env_var("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "whatsapp_token_set": bool(own_wa and not own_wa.startswith("your_meta")),
        "whatsapp_token_masked": _mask(own_wa),
        "whatsapp_phone_number_id": (tenant.get("whatsapp_phone_number_id") or (get_env_var("WHATSAPP_PHONE_NUMBER_ID") if is_admin else "")),
        "whatsapp_verify_token": (tenant.get("whatsapp_verify_token") or get_env_var("WHATSAPP_VERIFY_TOKEN", "")),
        "meta_app_secret_set": bool(own_app_sec),
        "meta_app_secret_masked": _mask(own_app_sec),
        "openrouter_guard_set": bool(own_or or get_env_var("OPENROUTER_API_KEY")),
        "openrouter_guard_masked": _mask(own_or) if is_admin else ("Platform Shield Active" if get_env_var("OPENROUTER_API_KEY") else ""),
        "openrouter_guard_model": tenant.get("openrouter_guard_model") or get_env_var("OPENROUTER_GUARD_MODEL", security_guard.DEFAULT_GUARD_MODEL),
    })


@app.post("/api/dashboard/settings")
async def save_settings(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    is_admin = bool(tenant.get("is_admin"))
    data = await request.json()

    updates = {}
    for key in ("business_name", "custom_system_prompt", "deepseek_model", "groq_model", "whatsapp_phone_number_id", "whatsapp_verify_token", "billing_mode"):
        if key in data and data.get(key) is not None:
            updates[key] = str(data.get(key)).strip()

    for secret_key, env_key in [
        ("deepseek_api_key", "DEEPSEEK_API_KEY"),
        ("groq_api_key", "GROQ_API_KEY"),
        ("whatsapp_token", "WHATSAPP_TOKEN"),
        ("meta_app_secret", "META_APP_SECRET"),
        ("openrouter_api_key", "OPENROUTER_API_KEY"),
    ]:
        val = (data.get(secret_key) or "").strip()
        if val and "..." not in val:
            if secret_key == "openrouter_api_key" and not is_admin:
                continue
            updates[secret_key] = val
            if is_admin:
                os.environ[env_key] = val
                try:
                    set_key(ENV_PATH, env_key, val)
                except Exception:
                    pass

    if is_admin:
        for norm_k, env_k in [
            ("deepseek_model", "DEEPSEEK_MODEL"),
            ("groq_model", "GROQ_MODEL"),
            ("whatsapp_phone_number_id", "WHATSAPP_PHONE_NUMBER_ID"),
            ("whatsapp_verify_token", "WHATSAPP_VERIFY_TOKEN"),
            ("openrouter_guard_model", "OPENROUTER_GUARD_MODEL"),
        ]:
            val = (data.get(norm_k) or "").strip()
            if val:
                os.environ[env_k] = val
                try:
                    set_key(ENV_PATH, env_k, val)
                except Exception:
                    pass

    if data.get("openrouter_guard_model") and is_admin:
        updates["openrouter_guard_model"] = str(data["openrouter_guard_model"]).strip()

    # Auto-switch billing mode to byo_meta (half price) when a user connects their own Meta credentials
    if not is_admin and updates.get("whatsapp_token") and (updates.get("whatsapp_phone_number_id") or tenant.get("whatsapp_phone_number_id")):
        if "billing_mode" not in updates:
            updates["billing_mode"] = "byo_meta"

    db.update_tenant_settings(tid, **updates)
    return JSONResponse({"success": True, "message": "Settings saved & synced to cloud!"})


@app.delete("/api/dashboard/messages")
async def delete_messages_endpoint(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    ids = data.get("ids", [])
    if isinstance(ids, (int, str)):
        ids = [ids]
    success = db.delete_messages(ids, tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success, "deleted_count": len(ids)})


@app.delete("/api/dashboard/conversation")
async def delete_conv(request: Request, phone: str = Query(...)):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    success = db.delete_contact(phone, tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success, "phone": phone})


@app.delete("/api/dashboard/clear")
async def clear_all(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    success = db.clear_data(tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success})


@app.get("/api/dashboard/webhooks")
async def get_webhooks(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    return JSONResponse({"logs": db.get_webhook_logs(50, tenant_id=tenant["tenant_id"])})


@app.post("/api/chat")
async def direct_chat(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    data = await request.json()
    msg = data.get("message", "")
    phone = data.get("phone", "+18005550199")
    if not msg:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    db.save_message(phone, msg, "inbound", "Customer", "simulator", tenant_id=tid)
    set_typing_state(phone, True, tenant_id=tid)
    try:
        reply, latency, engine = await asyncio.to_thread(get_ai_reply, msg, phone, tenant)
    finally:
        set_typing_state(phone, False, tenant_id=tid)
    db.save_message(phone, reply, "outbound", "Support Agent (AI)", "simulator", "sent", None, engine, latency, tenant_id=tid)
    return JSONResponse({"reply": reply, "model": engine, "latency_ms": latency})


# ====================================================================
# BULK BROADCAST & LEADS CRM ENDPOINTS (TENANT SCOPED + BILLED)
# ====================================================================

@app.post("/api/dashboard/broadcast")
async def bulk_broadcast(request: Request):
    """Send bulk WhatsApp messages (per-tenant Meta or Demo) with 24h conversation billing."""
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    creds = _resolve_tenant_credentials(tenant)
    access_token = tenant.get("access_token", "")

    data = await request.json()
    personalized_items = data.get("personalized_messages", [])
    numbers_raw = data.get("phone_numbers", [])
    default_message = (data.get("message") or "").strip()
    send_via_meta = bool(data.get("send_via_meta", True))
    add_as_leads = bool(data.get("add_as_leads", True))
    lead_source = (data.get("lead_source") or "Bulk Broadcast").strip()
    raw_recipient_names = data.get("recipient_names") or {}
    recipient_names = {}
    if isinstance(raw_recipient_names, dict):
        for k, v in raw_recipient_names.items():
            nk = db.normalize_phone_key(k) or re.sub(r"\D", "", str(k or ""))
            if nk and str(v or "").strip():
                recipient_names[nk] = str(v).strip()

    is_demo_channel = not (send_via_meta and creds["whatsapp_token"] and creds["whatsapp_phone_number_id"])

    # Case 1: Personalized AI Campaign
    if personalized_items and isinstance(personalized_items, list):
        results = []
        sent_count = 0
        failed_count = 0
        total_coins_charged = 0.0

        for item in personalized_items:
            raw_phone = item.get("phone") or item.get("contact_number") or ""
            digits = db.normalize_phone_key(raw_phone) or re.sub(r"[^0-9]", "", str(raw_phone))

            lead_name = (item.get("name") or item.get("business_name") or "").strip()
            item_msg = (item.get("message") or item.get("personalized_message") or default_message).strip()
            item_category = (item.get("category") or item.get("business_category") or "").strip()
            item_area = (item.get("area") or item.get("area_or_locality") or "").strip()
            item_website = (item.get("website") or item.get("Website_or_Social_Link") or "").strip()

            if not digits or len(digits) < 10:
                failed_count += 1
                results.append({
                    "phone": raw_phone or "N/A",
                    "name": lead_name or "Unknown",
                    "status": "failed",
                    "error": "Missing or invalid phone number (requires 10+ digits)",
                })
                continue

            if not item_msg:
                failed_count += 1
                results.append({
                    "phone": digits,
                    "name": lead_name or digits,
                    "status": "failed",
                    "error": "Message content was empty for this lead",
                })
                continue

            # Billing check / coin charge per 24h unique window
            bill = await asyncio.to_thread(auth_billing.charge_and_open_window, tenant, digits, access_token, is_demo_channel)
            if not bill.get("allowed"):
                failed_count += 1
                results.append({
                    "phone": digits,
                    "name": lead_name or digits,
                    "status": "failed",
                    "error": bill.get("message") or "Billing limit reached",
                    "billing_code": bill.get("code"),
                })
                continue
            total_coins_charged += float(bill.get("charged") or 0)

            profile_kwargs = {
                "business_name": lead_name,
                "business_category": item_category,
                "area": item_area,
                "data_source": "csv_campaign",
            }
            if item_website:
                low_web = item_website.lower()
                if "instagram.com" in low_web:
                    profile_kwargs["existing_ecosystem"] = "Instagram"
                elif "facebook.com" in low_web or "fb.com" in low_web:
                    profile_kwargs["existing_ecosystem"] = "Facebook"
                elif "wa.me/" in low_web or "whatsapp.com" in low_web:
                    profile_kwargs["existing_ecosystem"] = "WhatsApp"
                else:
                    profile_kwargs["website_url"] = item_website
                    profile_kwargs["has_website"] = "yes"
            stored_profile = db.upsert_customer_profile(digits, overwrite_existing=True, tenant_id=tid, **profile_kwargs)

            resolved_msg = security_guard.sanitize_outbound_reply(
                render_template_placeholders(
                    item_msg,
                    phone=digits,
                    explicit_name=lead_name,
                    profile=stored_profile,
                    tenant_id=tid,
                )
            )
            display_name = lead_name or stored_profile.get("business_name") or stored_profile.get("contact_name") or "Growhaz Support"

            status = "sent"
            err_msg = None
            meta_res = {}

            if send_via_meta:
                success, meta_res = await asyncio.to_thread(
                    send_meta_whatsapp_message,
                    digits,
                    resolved_msg,
                    creds["whatsapp_phone_number_id"],
                    creds["whatsapp_token"],
                )
                if success:
                    status = "sent"
                    sent_count += 1
                else:
                    status = "failed"
                    failed_count += 1
                    err_msg = str(meta_res)
                    try:
                        if isinstance(meta_res, str) and meta_res.strip().startswith("{"):
                            parsed = json.loads(meta_res)
                            if isinstance(parsed, dict) and "error" in parsed:
                                err_info = parsed["error"]
                                err_msg = str(err_info.get("message") if isinstance(err_info, dict) else err_info)
                        elif isinstance(meta_res, dict):
                            err_info = meta_res.get("error", meta_res)
                            err_msg = str(err_info.get("message") if isinstance(err_info, dict) else err_info)
                    except Exception:
                        pass
            else:
                status = "simulated"
                sent_count += 1

            db.save_message(
                phone_number=digits,
                sender_name=display_name,
                message=resolved_msg,
                direction="outbound",
                channel="ai_campaign" if send_via_meta else "simulator",
                status=status,
                raw_payload={"campaign": True, "lead_name": display_name, "meta_response": meta_res},
                tenant_id=tid,
            )

            if add_as_leads:
                lead_notes = f"{item_category} • {item_area}".strip(" •")
                db.add_or_update_lead(
                    phone_number=digits,
                    name=display_name if display_name != "Growhaz Support" else "Lead",
                    source=lead_source,
                    notes=lead_notes,
                    status="Contacted" if status in ["sent", "simulated"] else "New",
                    tenant_id=tid,
                )
                db.record_lead_messaged(digits, status="Contacted" if status in ["sent", "simulated"] else "Failed", tenant_id=tid)

            results.append({
                "phone": digits,
                "name": display_name,
                "status": status,
                "error": err_msg,
                "resolved_message": resolved_msg,
                "coins_charged": bill.get("charged", 0),
                "charge_source": bill.get("source", ""),
            })

            if send_via_meta and len(personalized_items) > 1:
                await asyncio.sleep(0.2)

        billing_after = await asyncio.to_thread(auth_billing.get_billing_summary, db.get_tenant(tid) | {"is_admin": tenant.get("is_admin"), "supabase_user_id": tenant.get("supabase_user_id"), "access_token": access_token}, access_token)
        return JSONResponse({
            "success": True,
            "mode": "personalized",
            "total": len(personalized_items),
            "sent": sent_count,
            "failed": failed_count,
            "coins_charged": total_coins_charged,
            "billing": billing_after,
            "results": results,
        })

    # Case 2: Standard Single-Message Broadcast
    if not default_message:
        return JSONResponse({"error": "Message content cannot be empty"}, status_code=400)

    if isinstance(numbers_raw, str):
        numbers_raw = [n.strip() for n in re.split(r"[\n,;]+", numbers_raw) if n.strip()]

    clean_numbers = []
    seen = set()
    for raw in numbers_raw:
        digits = db.normalize_phone_key(raw) or re.sub(r"[^0-9]", "", str(raw))
        if len(digits) >= 10 and digits not in seen:
            clean_numbers.append(digits)
            seen.add(digits)

    if not clean_numbers:
        return JSONResponse({"error": "No valid phone numbers found. Please enter 10+ digit numbers with country code."}, status_code=400)

    results = []
    sent_count = 0
    failed_count = 0
    total_coins_charged = 0.0

    for phone in clean_numbers:
        bill = await asyncio.to_thread(auth_billing.charge_and_open_window, tenant, phone, access_token, is_demo_channel)
        if not bill.get("allowed"):
            failed_count += 1
            results.append({
                "phone": phone,
                "name": recipient_names.get(phone, "Lead"),
                "status": "failed",
                "error": bill.get("message") or "Billing limit reached",
                "billing_code": bill.get("code"),
            })
            continue
        total_coins_charged += float(bill.get("charged") or 0)

        explicit_n = recipient_names.get(phone, "")
        profile = db.get_customer_profile(phone, tenant_id=tid)
        if explicit_n and db._is_meaningful_profile_val(explicit_n, "contact_name"):
            profile = db.upsert_customer_profile(phone, overwrite_existing=False, tenant_id=tid, contact_name=explicit_n, data_source="broadcast")
        final_msg = security_guard.sanitize_outbound_reply(
            render_template_placeholders(default_message, phone=phone, explicit_name=explicit_n, profile=profile, tenant_id=tid)
        )
        display_name = _pick_real_recipient_name(explicit_n, profile, phone) or "Lead"

        status = "sent"
        err_msg = None
        meta_res = {}

        if send_via_meta:
            success, meta_res = await asyncio.to_thread(
                send_meta_whatsapp_message,
                phone,
                final_msg,
                creds["whatsapp_phone_number_id"],
                creds["whatsapp_token"],
            )
            if success:
                status = "sent"
                sent_count += 1
            else:
                status = "failed"
                failed_count += 1
                err_msg = str(meta_res)
                try:
                    if isinstance(meta_res, str) and meta_res.strip().startswith("{"):
                        parsed = json.loads(meta_res)
                        if isinstance(parsed, dict) and "error" in parsed:
                            err_info = parsed["error"]
                            err_msg = str(err_info.get("message") if isinstance(err_info, dict) else err_info)
                    elif isinstance(meta_res, dict):
                        err_info = meta_res.get("error", meta_res)
                        err_msg = str(err_info.get("message") if isinstance(err_info, dict) else err_info)
                except Exception:
                    pass
        else:
            status = "simulated"
            sent_count += 1

        db.save_message(
            phone_number=phone,
            sender_name=display_name if display_name != "Lead" else (tenant.get("business_name") or "Growhaz Support"),
            message=final_msg,
            direction="outbound",
            channel="bulk_broadcast" if send_via_meta else "simulator",
            status=status,
            raw_payload={"broadcast": True, "meta_response": meta_res},
            tenant_id=tid,
        )

        if add_as_leads:
            db.add_or_update_lead(
                phone_number=phone,
                name=display_name,
                source=lead_source,
                status="Contacted" if status in ["sent", "simulated"] else "New",
                tenant_id=tid,
            )
            db.record_lead_messaged(phone, status="Contacted" if status in ["sent", "simulated"] else "Failed", tenant_id=tid)

        results.append({
            "phone": phone,
            "name": display_name,
            "status": status,
            "error": err_msg,
            "resolved_message": final_msg,
            "coins_charged": bill.get("charged", 0),
            "charge_source": bill.get("source", ""),
        })

        if send_via_meta and len(clean_numbers) > 1:
            await asyncio.sleep(0.2)

    billing_after = await asyncio.to_thread(auth_billing.get_billing_summary, db.get_tenant(tid) | {"is_admin": tenant.get("is_admin"), "supabase_user_id": tenant.get("supabase_user_id"), "access_token": access_token}, access_token)
    return JSONResponse({
        "success": True,
        "mode": "standard",
        "total": len(clean_numbers),
        "sent": sent_count,
        "failed": failed_count,
        "coins_charged": total_coins_charged,
        "billing": billing_after,
        "results": results,
    })


@app.post("/api/dashboard/ai-personalize-campaign")
async def ai_personalize_campaign(request: Request):
    """Generate customized, ecosystem-focused AI outreach messages concurrently across a list of businesses."""
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    creds = _resolve_tenant_credentials(tenant)

    try:
        from api.bot_engine import generate_personalized_campaign_pitch

        data = await request.json()
        leads = data.get("leads", [])
        campaign_goal = (data.get("campaign_goal") or "Helping integrate practical technology (website, automation & WhatsApp workflows) into your existing business ecosystem").strip()
        tone = (data.get("tone") or "friendly_warm").strip()
        custom_notes = (data.get("custom_notes") or "").strip()

        if not leads or not isinstance(leads, list):
            return JSONResponse({"error": "A list of leads/businesses is required."}, status_code=400)

        sem = asyncio.Semaphore(5)

        async def _gen_one(idx: int, lead: dict) -> dict:
            b_name = (lead.get("business_name") or lead.get("name") or lead.get("Business_Name") or "").strip()
            b_cat = (lead.get("category") or lead.get("business_category") or lead.get("Business_Category") or "").strip()
            b_area = (lead.get("area") or lead.get("area_or_locality") or lead.get("Area_or_Locality") or "").strip()
            b_phone = (lead.get("phone") or lead.get("contact_number") or lead.get("Contact_Number") or "").strip()
            b_web = (lead.get("website") or lead.get("website_url") or lead.get("Website_or_Social_Link") or "").strip()
            b_eco = (lead.get("existing_ecosystem") or "").strip()

            if b_phone:
                stored = db.get_customer_profile(b_phone, tenant_id=tid)
                if not db._is_meaningful_profile_val(b_name, "business_name") and stored.get("business_name"):
                    b_name = stored["business_name"]
                if not db._is_meaningful_profile_val(b_cat, "business_category") and stored.get("business_category"):
                    b_cat = stored["business_category"]
                if not db._is_meaningful_profile_val(b_area, "area") and stored.get("area"):
                    b_area = stored["area"]
                if not b_web and stored.get("website_url"):
                    b_web = stored["website_url"]
                if not b_eco and stored.get("existing_ecosystem"):
                    b_eco = stored["existing_ecosystem"]

            async with sem:
                try:
                    pitch, eng = await asyncio.to_thread(
                        generate_personalized_campaign_pitch,
                        business_name=b_name,
                        category=b_cat,
                        area=b_area,
                        campaign_goal=campaign_goal,
                        tone=tone,
                        custom_notes=custom_notes,
                        deepseek_api_key=creds["deepseek_api_key"],
                        deepseek_model=creds["deepseek_model"],
                        groq_api_key=creds["groq_api_key"],
                        groq_model=creds["groq_model"],
                        website_url=b_web,
                        existing_ecosystem=b_eco,
                    )
                except Exception as item_err:
                    logger.warning(f"[Campaign AI] Error generating pitch for {b_name or idx}: {item_err}")
                    if b_name:
                        area_txt = f" in {b_area}" if b_area else ""
                        pitch = (
                            f"Hello {b_name} team! 👋 Greetings from Growhaz. We help {b_cat or 'local businesses'}{area_txt} "
                            "integrate automated WhatsApp replies and web tools smoothly into their existing workflow. "
                            "Do you already have a website, or would you like a quick 2-minute example?"
                        )
                    else:
                        pitch = (
                            "Hello! 👋 Greetings from Growhaz. We help business owners integrate practical technology smoothly into their existing workflow. "
                            "Before sharing suggestions, could you share your business name, what work you do, and whether you already have a website?"
                        )
                    eng = "Fallback Template"

            updated_lead = dict(lead)
            updated_lead["business_name"] = b_name
            updated_lead["category"] = b_cat
            updated_lead["area"] = b_area
            updated_lead["phone"] = b_phone
            updated_lead["website"] = b_web
            updated_lead["personalized_message"] = pitch
            updated_lead["engine_used"] = eng
            return updated_lead

        personalized_leads = list(await asyncio.gather(*[_gen_one(i, l) for i, l in enumerate(leads)]))
        engine_used = personalized_leads[0]["engine_used"] if personalized_leads else "AI Engine"

        return JSONResponse({
            "success": True,
            "total": len(personalized_leads),
            "engine_used": engine_used,
            "leads": personalized_leads,
        })
    except Exception as e:
        logger.error(f"[Campaign AI] Error in personalize campaign: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/dashboard/leads")
async def get_all_leads(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    leads = db.get_leads(tenant_id=tenant["tenant_id"])
    return JSONResponse({"leads": leads, "total": len(leads)})


@app.post("/api/dashboard/leads")
async def add_leads_endpoint(request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    tid = tenant["tenant_id"]
    data = await request.json()
    numbers_raw = data.get("phone_numbers", [])
    name = (data.get("name") or "Lead").strip()
    source = (data.get("source") or "Manual Import").strip()
    notes = (data.get("notes") or "").strip()
    status = (data.get("status") or "New").strip()

    if isinstance(numbers_raw, str):
        numbers_raw = [n.strip() for n in re.split(r"[\n,;]+", numbers_raw) if n.strip()]

    added = 0
    for raw in numbers_raw:
        digits = db.normalize_phone_key(raw) or re.sub(r"[^0-9]", "", str(raw))
        if len(digits) >= 10:
            db.add_or_update_lead(digits, name=name, source=source, status=status, notes=notes, tenant_id=tid)
            added += 1

    return JSONResponse({"success": True, "added_count": added})


@app.delete("/api/dashboard/leads/{lead_id}")
async def delete_lead_endpoint(lead_id: int, request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    success = db.delete_lead(lead_id, tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success, "lead_id": lead_id})


@app.put("/api/dashboard/leads/{lead_id}/status")
async def update_lead_status_endpoint(lead_id: int, request: Request):
    tenant = await asyncio.to_thread(auth_billing.resolve_tenant_from_request, request, True)
    data = await request.json()
    status = data.get("status", "Contacted")
    success = db.update_lead_status(lead_id, status, tenant_id=tenant["tenant_id"])
    return JSONResponse({"success": success, "lead_id": lead_id, "status": status})


# ====================================================================
# 3. DASHBOARD USER INTERFACE & POLICIES
# ====================================================================

@app.api_route("/dashboard", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_dashboard():
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Growhaz Support Hub</h1><p>Dashboard template not found.</p>")


@app.api_route("/privacy", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/privacy-policy", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_privacy():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Privacy Policy - Growhaz WhatsApp Bot</title>
        <style>body{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#333;}</style>
    </head>
    <body>
        <h1>Privacy Policy</h1>
        <p><strong>Effective Date:</strong> November 18, 2026</p>
        <p>This Privacy Policy describes how Growhaz ("we", "our") collects, uses, and safeguards information when you interact with our WhatsApp automation service.</p>
        <h2>1. Information We Collect</h2>
        <p>We receive incoming WhatsApp messages, sender phone numbers, and message timestamps through the official Meta WhatsApp Cloud API to provide automated customer support and booking assistance.</p>
        <h2>2. How We Use Information</h2>
        <p>Your messages are processed strictly to answer customer inquiries, manage service appointments, and generate relevant support responses via AI and automated workflows.</p>
        <h2>3. Data Protection</h2>
        <p>We do not sell, rent, or trade your personal information. Data transmitted is encrypted using standard HTTPS/TLS protocols.</p>
        <h2>4. Contact & Data Deletion</h2>
        <p>If you wish to request deletion of your contact records, email us at <a href="mailto:info.growhaz@gmail.com">info.growhaz@gmail.com</a>.</p>
    </body>
    </html>
    """)


@app.api_route("/terms", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/terms-of-service", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_terms():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Terms of Service - Growhaz WhatsApp Bot</title>
        <style>body{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#333;}</style>
    </head>
    <body>
        <h1>Terms of Service</h1>
        <p><strong>Effective Date:</strong> November 18, 2026</p>
        <h2>1. Acceptance of Terms</h2>
        <p>By interacting with the Growhaz WhatsApp bot, you agree to these Terms of Service.</p>
        <h2>2. Service Description</h2>
        <p>Growhaz provides automated messaging and customer support services via WhatsApp Business Platform.</p>
        <h2>3. User Conduct</h2>
        <p>Users agree not to transmit spam, abusive language, or prohibited content through the messaging interface.</p>
        <h2>4. Contact</h2>
        <p>For questions or support, contact <a href="mailto:info.growhaz@gmail.com">info.growhaz@gmail.com</a>.</p>
    </body>
    </html>
    """)


@app.api_route("/data-deletion", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/user-data-deletion", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_data_deletion():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>User Data Deletion Instructions - Growhaz</title>
        <style>body{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.6;color:#333;}</style>
    </head>
    <body>
        <h1>User Data Deletion Instructions</h1>
        <p>In accordance with Meta Platform policies, users have the right to request deletion of their data collected via our WhatsApp application.</p>
        <h2>How to Request Data Deletion:</h2>
        <ol>
            <li>Send an email to <strong>info.growhaz@gmail.com</strong> with the subject <em>"Data Deletion Request"</em>.</li>
            <li>Include your WhatsApp phone number (with country code).</li>
            <li>We will delete all associated chat logs, contact information, and booking records from our database within 48 hours.</li>
            <li>You will receive a confirmation email once your data has been completely erased.</li>
        </ol>
    </body>
    </html>
    """)
