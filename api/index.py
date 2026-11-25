import os
import re
import json
import time
import asyncio
import logging
import httpx
from fastapi import FastAPI, Request, Response, Form, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv, set_key

# Import internal modules
try:
    from api import db
    from api.bot_engine import generate_ai_reply
    from api.dna_service import dynamic_dna
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
    from whatsapp_service import (
        get_env_var,
        send_meta_whatsapp_message,
        send_meta_typing_indicator,
        upload_meta_media,
        send_meta_whatsapp_media,
        download_meta_media,
        UPLOAD_DIR,
    )

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

load_dotenv(ENV_PATH)
db.init_db()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp_support_bot")

app = FastAPI(title="Growhaz • WhatsApp Support Hub & Dashboard")

# Mount static files and uploaded media
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

SERVER_START_TIME = time.time()

# In-memory typing status tracker for Live Chat UI & Simulator
ACTIVE_TYPING_CHATS: dict[str, float] = {}


def set_typing_state(phone: str, active: bool):
    """Mark a conversation as currently composing an AI/agent reply."""
    key = db.normalize_phone_key(phone) or str(phone or "").replace("+", "").strip()
    if not key:
        return
    if active:
        ACTIVE_TYPING_CHATS[key] = time.time()
    else:
        ACTIVE_TYPING_CHATS.pop(key, None)


def is_chat_typing(phone: str) -> bool:
    """Return True if a reply is actively being composed (auto-expires after 30s)."""
    key = db.normalize_phone_key(phone) or str(phone or "").replace("+", "").strip()
    if not key:
        return False
    ts = ACTIVE_TYPING_CHATS.get(key)
    if not ts:
        return False
    if (time.time() - ts) > 30.0:
        ACTIVE_TYPING_CHATS.pop(key, None)
        return False
    return True


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
    profile: dict = None
) -> str:
    """
    Resolve template placeholders ({{name}}, {{business}}, {{area}}, {{phone}}, {{service}}, {{date_time}})
    per recipient using explicit metadata and persistent customer_profiles DB. Never leaves literal {{name}}.
    """
    raw = str(text or "")
    if "{{" not in raw:
        return raw

    phone_key = db.normalize_phone_key(phone) if phone else ""
    clean_phone = phone_key or re.sub(r"\D", "", str(phone or ""))
    prof = profile if profile is not None else (db.get_customer_profile(phone) if phone else {})

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


def get_ai_reply(prompt: str, customer_id: str = "") -> tuple[str, float, str]:
    """Helper to route AI responses: DeepSeek AI -> Groq AI -> Smart Customer Support Agent with DNA Memory."""
    deepseek_key = get_env_var("DEEPSEEK_API_KEY")
    deepseek_model = get_env_var("DEEPSEEK_MODEL", "deepseek-chat")
    groq_key = get_env_var("GROQ_API_KEY")
    groq_model = get_env_var("GROQ_MODEL", "llama-3.3-70b-versatile")
    return generate_ai_reply(
        user_prompt=prompt,
        deepseek_api_key=deepseek_key,
        deepseek_model=deepseek_model,
        groq_api_key=groq_key,
        groq_model=groq_model,
        customer_id=customer_id
    )

@app.get("/api/health")
@app.get("/health")
async def health_check():
    """Health check endpoint for Render, UptimeRobot, and cron services."""
    return JSONResponse({
        "status": "healthy",
        "service": "whatsapp-ai-bot",
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 1),
        "timestamp": int(time.time())
    })

async def keep_alive_worker():
    """Background task that pings the public URL every 3-5 minutes so Render never sleeps."""
    await asyncio.sleep(30)  # Initial grace period on boot
    while True:
        try:
            render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
            base_url = (
                (f"https://{render_hostname}" if render_hostname else None) or
                os.getenv("RENDER_EXTERNAL_URL") or 
                os.getenv("APP_URL") or 
                "https://whatapp-v59g.onrender.com"
            ).rstrip("/")

            if "localhost" not in base_url and "127.0.0.1" not in base_url:
                health_url = f"{base_url}/api/health"
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(health_url)
                    logger.info(f"[Keep-Alive] 5-min heartbeat ping to {health_url} -> Status {resp.status_code}")
                    print(f"[Keep-Alive] Keep-alive ping sent to {health_url} (HTTP {resp.status_code})")
        except Exception as e:
            logger.warning(f"[Keep-Alive] Warning: self-ping failed: {e}")
        
        # Ping every 4 minutes (240 seconds) to ensure Render's 15-minute inactivity timer never triggers
        await asyncio.sleep(240)

@app.on_event("startup")
async def startup_keep_alive():
    asyncio.create_task(keep_alive_worker())

# ====================================================================
# 1. WEBHOOKS (META CLOUD API & TWILIO)
# ====================================================================

@app.get("/api/webhook")
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    expected_token = get_env_var("WHATSAPP_VERIFY_TOKEN", "whatsapp_groq_bot_secret_123")
    received_token = (hub_verify_token or "").strip().strip('"').strip("'")
    is_valid = (received_token == expected_token or received_token == "whatsapp_groq_bot_secret_123")

    db.save_webhook_log(
        endpoint="/api/webhook",
        method="GET",
        payload={"hub.mode": hub_mode, "hub.verify_token": hub_verify_token, "hub.challenge": hub_challenge},
        status_code=200 if (hub_mode == "subscribe" and is_valid) else 403
    )

    if hub_mode == "subscribe" and is_valid:
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    return PlainTextResponse(content="Forbidden: Verification token mismatch", status_code=403)

@app.post("/api/webhook")
@app.post("/webhook")
async def handle_meta_webhook(request: Request):
    """Handles incoming customer messages from WhatsApp Meta Cloud API."""
    try:
        body = await request.json()
        db.save_webhook_log(endpoint="/api/webhook", method="POST", payload=body, status_code=200)
    except Exception as e:
        db.save_webhook_log(endpoint="/api/webhook", method="POST", payload=str(e), status_code=400)
        return JSONResponse({"status": "invalid json"}, status_code=400)

    try:
        entries = body.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                val = change.get("value", {})
                metadata = val.get("metadata", {})
                incoming_phone_id = metadata.get("phone_number_id")
                if incoming_phone_id:
                    os.environ["WHATSAPP_PHONE_NUMBER_ID"] = incoming_phone_id

                contacts = val.get("contacts", [])
                sender_name = contacts[0].get("profile", {}).get("name", "Customer") if contacts else "Customer"
                
                for msg in val.get("messages", []):
                    msg_type = msg.get("type")
                    if msg_type in ["text", "image", "document"]:
                        sender_id = msg.get("from")
                        if not sender_id:
                            continue

                        user_text = ""
                        media_type = None
                        media_url = None
                        media_filename = None

                        if msg_type == "text":
                            user_text = msg.get("text", {}).get("body", "").strip()
                        elif msg_type == "image":
                            media_type = "image"
                            img_data = msg.get("image", {})
                            user_text = img_data.get("caption", "").strip()
                            media_id = img_data.get("id")
                            if media_id:
                                media_url, media_filename, _ = download_meta_media(media_id, ".jpg")
                            if not user_text:
                                user_text = "📷 [Photo Received]"
                        elif msg_type == "document":
                            media_type = "document"
                            doc_data = msg.get("document", {})
                            user_text = doc_data.get("caption", "").strip()
                            media_id = doc_data.get("id")
                            orig_fname = doc_data.get("filename", "")
                            if media_id:
                                media_url, media_filename, _ = download_meta_media(media_id, ".pdf")
                            if orig_fname:
                                media_filename = orig_fname
                            if not user_text:
                                user_text = f"📄 [Document: {media_filename or 'File'}]"

                        # 1. Save Inbound Message & Record Real Contact Name
                        db.save_message(
                            phone_number=sender_id,
                            sender_name=sender_name,
                            message=user_text,
                            direction="inbound",
                            channel="meta_whatsapp",
                            raw_payload=msg,
                            media_type=media_type,
                            media_url=media_url,
                            media_filename=media_filename
                        )
                        if sender_name and sender_name.strip().lower() not in {"customer", "user", "unknown"}:
                            db.upsert_customer_profile(
                                sender_id,
                                overwrite_existing=False,
                                contact_name=sender_name.strip(),
                                data_source="whatsapp_chat"
                            )

                        # Check if automated bot is enabled for this customer
                        bot_active = db.is_bot_enabled_for_contact(sender_id)

                        # If customer message asks for human agent, auto-pause bot for next messages
                        is_handover_request = bool(user_text and any(w in user_text.lower() for w in ["human", "agent", "person", "representative", "specialist", "talk to someone", "call me"]))
                        if is_handover_request:
                            db.set_bot_enabled_for_contact(sender_id, False)

                        if bot_active:
                            incoming_wamid = msg.get("id")
                            if incoming_wamid:
                                try:
                                    await asyncio.to_thread(send_meta_typing_indicator, incoming_wamid, incoming_phone_id)
                                except Exception as _te:
                                    logger.debug(f"Typing indicator dispatch warning: {_te}")

                            set_typing_state(sender_id, True)
                            try:
                                if media_type:
                                    reply = (
                                        f"Thank you for sharing your {media_type}! 📄\n\n"
                                        "We have received your file at *Growhaz*. "
                                        "Our technical team is reviewing it and will update you shortly."
                                    )
                                    latency_ms = 0.0
                                    engine_used = "Growhaz Assistant"
                                else:
                                    # Track interaction dynamically in DNA memory
                                    try:
                                        dynamic_dna.record_interaction(customer_id=sender_id, action="received_message", target_id="chat_interaction", attributes={"snippet": user_text[:60]})
                                    except Exception as _e:
                                        logger.debug(f"DNA record error: {_e}")

                                    reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, user_text, sender_id)
                            finally:
                                set_typing_state(sender_id, False)

                            # Send to WhatsApp (dynamically routes to incoming phone_number_id)
                            success, send_res = await asyncio.to_thread(
                                send_meta_whatsapp_message, sender_id, reply, incoming_phone_id
                            )

                            # Save Outbound Message
                            db.save_message(
                                phone_number=sender_id,
                                sender_name="Support Agent (AI)",
                                message=reply,
                                direction="outbound",
                                channel="meta_whatsapp",
                                status="sent" if success else "failed",
                                raw_payload=send_res,
                                ai_model=engine_used,
                                latency_ms=latency_ms
                            )
                        elif not bot_active:
                            logger.info(f"[Meta Webhook] AI bot is paused for {sender_id}. {msg_type} saved for human agent.")
    except Exception as err:
        logger.error(f"Error handling Meta WhatsApp webhook: {err}")

    return JSONResponse({"status": "success"}, status_code=200)

@app.post("/api/twilio")
async def handle_twilio_webhook(From: str = Form(None), Body: str = Form(None), ProfileName: str = Form("Customer")):
    user_text = (Body or "").strip()
    sender_id = (From or "unknown").replace("whatsapp:", "")
    
    db.save_webhook_log(endpoint="/api/twilio", method="POST", payload={"From": From, "Body": Body, "ProfileName": ProfileName})

    if not user_text:
        return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>', media_type="application/xml")

    db.save_message(phone_number=sender_id, sender_name=ProfileName, message=user_text, direction="inbound", channel="twilio")
    if ProfileName and ProfileName.strip().lower() not in {"customer", "user", "unknown"}:
        db.upsert_customer_profile(sender_id, overwrite_existing=False, contact_name=ProfileName.strip(), data_source="twilio")

    bot_active = db.is_bot_enabled_for_contact(sender_id)
    reply = "Your message has been received by our support team."
    engine_used = "Support Desk"
    latency_ms = 0.0

    if bot_active:
        set_typing_state(sender_id, True)
        try:
            reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, user_text, sender_id)
        finally:
            set_typing_state(sender_id, False)

    db.save_message(phone_number=sender_id, sender_name="Support Agent (AI)", message=reply, direction="outbound", channel="twilio", status="sent", ai_model=engine_used, latency_ms=latency_ms)

    escaped = reply.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escaped}</Message></Response>', media_type="application/xml")

# ====================================================================
# 2. DASHBOARD DATA, TEMPLATES, & ACTIONS
# ====================================================================

@app.get("/api/dashboard/stats")
async def get_dashboard_stats():
    stats = db.get_stats()
    deepseek_key = get_env_var("DEEPSEEK_API_KEY")
    stats["deepseek_configured"] = bool(deepseek_key and not deepseek_key.startswith("sk_your"))
    stats["deepseek_model"] = get_env_var("DEEPSEEK_MODEL", "deepseek-chat")
    groq_key = get_env_var("GROQ_API_KEY")
    stats["groq_configured"] = bool(groq_key and not groq_key.startswith("gsk_your"))
    stats["groq_model"] = get_env_var("GROQ_MODEL", "llama-3.3-70b-versatile")
    stats["meta_configured"] = bool(get_env_var("WHATSAPP_TOKEN") and get_env_var("WHATSAPP_PHONE_NUMBER_ID"))
    return JSONResponse(stats)

@app.get("/api/dashboard/conversations")
async def get_conversations():
    convs = db.get_conversations()
    for c in convs:
        c["is_typing"] = is_chat_typing(c.get("phone_number", ""))
    return JSONResponse({"conversations": convs})

@app.get("/api/dashboard/messages")
async def get_messages(phone: str = Query(None), limit: int = Query(200)):
    messages = db.get_messages(phone_number=phone, limit=limit)
    bot_enabled = db.is_bot_enabled_for_contact(phone) if phone else True
    is_typing = is_chat_typing(phone) if phone else False
    profile = db.get_customer_profile(phone) if phone else None
    return JSONResponse({
        "messages": messages,
        "phone": phone,
        "bot_enabled": bot_enabled,
        "is_typing": is_typing,
        "customer_profile": profile
    })

@app.get("/api/dashboard/dna/{phone}")
async def get_customer_dna(phone: str):
    """Retrieves customer's dynamic DNA predictions, decoded long-term facts, and relational bonds."""
    try:
        clean_phone = phone.strip()
        pred = dynamic_dna.predict_customer_behavior(clean_phone)
        facts = dynamic_dna.decode_customer_facts(clean_phone)

        rels_data = []
        if dynamic_dna.system:
            rels = dynamic_dna.system.relation_registry.retrieve_relations(subject_id=clean_phone)
            for r in rels:
                rels_data.append({
                    "id": r.id,
                    "subject": r.subject_id,
                    "relation_type": r.relation_type,
                    "object": r.object_id,
                    "confidence": r.confidence,
                    "strength": r.strength,
                    "timestamp": r.timestamp
                })

        return JSONResponse({
            "success": True,
            "dna": {
                "prediction": pred,
                "facts": facts,
                "relations": rels_data
            }
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.get("/api/dashboard/templates")
async def get_templates():
    templates = db.get_templates()
    return JSONResponse({"templates": templates})

@app.post("/api/dashboard/templates")
async def add_template(request: Request):
    data = await request.json()
    t_id = db.save_template(
        title=data.get("title", "Custom Template"),
        category=data.get("category", "General"),
        content=data.get("content", ""),
        shortcut=data.get("shortcut", "")
    )
    return JSONResponse({"success": bool(t_id), "id": t_id})

@app.delete("/api/dashboard/templates")
async def delete_template(id: int = Query(...)):
    success = db.delete_template(id)
    return JSONResponse({"success": success})

@app.post("/api/dashboard/contact/bot-toggle")
async def toggle_contact_bot(request: Request):
    data = await request.json()
    phone = data.get("phone", "")
    enabled = bool(data.get("enabled", True))
    success = db.set_bot_enabled_for_contact(phone, enabled)
    return JSONResponse({"success": success, "phone": phone, "bot_enabled": enabled})

@app.get("/api/dashboard/bookings")
async def get_bookings():
    bookings = db.get_bookings()
    return JSONResponse({"bookings": bookings})

@app.post("/api/dashboard/bookings/update")
async def update_booking(request: Request):
    data = await request.json()
    success = db.update_booking_status(data.get("id"), data.get("status"))
    return JSONResponse({"success": success})

@app.post("/api/dashboard/bookings/add")
async def add_booking(request: Request):
    data = await request.json()
    b_id = db.add_manual_booking(
        phone_number=data.get("phone", ""),
        customer_name=data.get("name", "Customer"),
        service=data.get("service", "General Support"),
        date_time=data.get("date_time", "Pending Schedule"),
        status=data.get("status", "confirmed"),
        notes=data.get("notes", "")
    )
    return JSONResponse({"success": bool(b_id), "id": b_id})

@app.post("/api/dashboard/trigger-ai-reply")
async def trigger_ai_reply(request: Request):
    """Force generate an AI bot reply to a specific customer's latest message."""
    data = await request.json()
    phone = (data.get("phone") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    
    if not prompt and phone:
        msgs = db.get_messages(phone_number=phone, limit=5)
        inbounds = [m for m in msgs if m["direction"] == "inbound"]
        if inbounds:
            prompt = inbounds[-1]["message"]
    
    if not prompt:
        prompt = "Hello! How can Growhaz customer support help me today?"

    set_typing_state(phone, True)
    try:
        reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, prompt, phone)
    finally:
        set_typing_state(phone, False)

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
            latency_ms=latency_ms
        )

    return JSONResponse({
        "success": True,
        "message_id": msg_id,
        "reply": reply,
        "engine": engine_used,
        "latency_ms": latency_ms
    })

@app.post("/api/dashboard/send")
async def send_dashboard_reply(request: Request):
    """
    Send message from dashboard.
    If role is 'customer': simulates customer asking question + triggers AI auto reply!
    If role is 'agent': sends manual response from agent (resolving template variables like {{name}}).
    If role is 'ai': generates AI response as agent.
    """
    data = await request.json()
    phone = (data.get("phone") or "+14155550199").strip()
    customer_name = (data.get("name") or "Customer").strip()
    msg_input = (data.get("message") or "").strip()
    role = data.get("role", "customer") # "customer" (default for testing AI reply), "agent", "ai"
    send_via_meta = data.get("send_via_meta", False)
    
    if not phone or not msg_input:
        return JSONResponse({"error": "Phone number and message text are required."}, status_code=400)

    # Case 1: Message is typed as Customer -> save inbound and trigger AI reply!
    if role == "customer":
        inbound_id = db.save_message(
            phone_number=phone,
            sender_name=customer_name,
            message=msg_input,
            direction="inbound",
            channel="simulator",
            status="received"
        )
        if customer_name and customer_name.lower() not in {"customer", "user", "unknown"}:
            db.upsert_customer_profile(phone, overwrite_existing=False, contact_name=customer_name, data_source="simulator")

        bot_active = db.is_bot_enabled_for_contact(phone)
        ai_reply = ""
        latency_ms = 0.0
        engine_used = ""
        outbound_id = None

        if bot_active:
            set_typing_state(phone, True)
            try:
                ai_reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, msg_input, phone)
            finally:
                set_typing_state(phone, False)

            outbound_id = db.save_message(
                phone_number=phone,
                sender_name="Support Agent (AI)",
                message=ai_reply,
                direction="outbound",
                channel="simulator",
                status="sent",
                ai_model=engine_used,
                latency_ms=latency_ms
            )

        return JSONResponse({
            "success": True,
            "inbound_id": inbound_id,
            "outbound_id": outbound_id,
            "customer_message": msg_input,
            "ai_reply": ai_reply,
            "engine": engine_used,
            "latency_ms": latency_ms
        })

    # Case 2: Message is typed as Agent or AI generator
    if role == "ai":
        set_typing_state(phone, True)
        try:
            reply_body, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, msg_input, phone)
        finally:
            set_typing_state(phone, False)
        sender_name = "Support Agent (AI)"
    else:
        reply_body = render_template_placeholders(msg_input, phone=phone, explicit_name=customer_name)
        latency_ms = 0.0
        engine_used = None
        sender_name = "Growhaz Support"
        # When an agent replies directly, automatically pause AI bot for this contact so the AI does not interrupt!
        db.set_bot_enabled_for_contact(phone, False)

    status = "sent"
    meta_payload = {}
    if send_via_meta:
        success, meta_res = await asyncio.to_thread(send_meta_whatsapp_message, phone, reply_body)
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
        latency_ms=latency_ms
    )

    return JSONResponse({
        "success": True,
        "message_id": msg_id,
        "phone": phone,
        "message": reply_body,
        "engine": engine_used,
        "status": status,
        "latency_ms": latency_ms
    })

@app.post("/api/dashboard/send-media")
async def send_dashboard_media(
    phone: str = Form(...),
    caption: str = Form(""),
    media_type: str = Form("image"),
    send_via_meta: bool = Form(True),
    file: UploadFile = File(None),
    media_url: str = Form(None)
):
    """Send photo or document to customer from dashboard, forward to WhatsApp, and pause bot."""
    phone = (phone or "").strip()
    caption = (caption or "").strip()
    if not phone:
        return JSONResponse({"error": "Phone number is required"}, status_code=400)

    filename = ""
    saved_url = media_url or ""
    mime_type = "application/octet-stream"
    meta_id = None
    meta_payload = {}
    status = "sent"

    # Handle file upload if provided
    if file and file.filename:
        filename = file.filename
        mime_type = file.content_type or ("image/jpeg" if media_type == "image" else "application/pdf")
        contents = await file.read()

        # Save locally in uploads folder
        clean_fname = f"{int(time.time())}_{filename.replace(' ', '_')}"
        local_path = os.path.join(UPLOAD_DIR, clean_fname)
        with open(local_path, "wb") as f:
            f.write(contents)
        saved_url = f"/uploads/{clean_fname}"

        # Upload directly to Meta WhatsApp Media API
        if send_via_meta:
            meta_id = upload_meta_media(contents, filename, mime_type)

    if not saved_url and not meta_id:
        return JSONResponse({"error": "Please provide a file or media URL"}, status_code=400)

    # Send via Meta WhatsApp Cloud API
    if send_via_meta:
        success, meta_res = send_meta_whatsapp_media(
            recipient_number=phone,
            media_type=media_type,
            media_id=meta_id,
            media_link=saved_url if not meta_id and saved_url.startswith("http") else None,
            caption=caption,
            filename=filename or ("document.pdf" if media_type == "document" else "image.jpg")
        )
        status = "sent" if success else "failed"
        meta_payload = {"meta_api_response": meta_res}

    # Save to database
    display_msg = caption if caption else (f"📷 Photo" if media_type == "image" else f"📄 Document: {filename or 'File'}")
    msg_id = db.save_message(
        phone_number=phone,
        sender_name="Growhaz Support",
        message=display_msg,
        direction="outbound",
        channel="manual_admin",
        status=status,
        raw_payload=meta_payload,
        media_type=media_type,
        media_url=saved_url,
        media_filename=filename
    )

    # Automatically pause bot since human agent sent media
    db.set_bot_enabled_for_contact(phone, False)

    return JSONResponse({
        "success": True,
        "message_id": msg_id,
        "phone": phone,
        "media_type": media_type,
        "media_url": saved_url,
        "media_filename": filename,
        "caption": caption,
        "status": status
    })

@app.post("/api/dashboard/simulate-inbound")
async def simulate_inbound(request: Request):
    data = await request.json()
    phone = (data.get("phone") or "+14155550199").strip()
    name = (data.get("name") or "Sarah Jenkins").strip()
    user_msg = (data.get("message") or "Hi! I need help with a website security scan.").strip()
    auto_reply = data.get("auto_reply", True)

    in_id = db.save_message(
        phone_number=phone,
        sender_name=name,
        message=user_msg,
        direction="inbound",
        channel="simulator",
        status="received"
    )
    if name and name.lower() not in {"customer", "user", "unknown"}:
        db.upsert_customer_profile(phone, overwrite_existing=False, contact_name=name, data_source="simulator")

    out_id = None
    ai_reply = ""
    latency_ms = 0.0
    engine_used = ""

    bot_active = db.is_bot_enabled_for_contact(phone)

    if auto_reply and bot_active:
        set_typing_state(phone, True)
        try:
            ai_reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, user_msg, phone)
        finally:
            set_typing_state(phone, False)

        out_id = db.save_message(
            phone_number=phone,
            sender_name="Support Agent (AI)",
            message=ai_reply,
            direction="outbound",
            channel="simulator",
            status="sent",
            ai_model=engine_used,
            latency_ms=latency_ms
        )

    return JSONResponse({
        "success": True,
        "inbound_id": in_id,
        "outbound_id": out_id,
        "phone": phone,
        "user_message": user_msg,
        "ai_reply": ai_reply,
        "engine": engine_used,
        "latency_ms": latency_ms
    })

@app.post("/api/dashboard/test-ai")
async def test_ai_endpoint(request: Request):
    """Test AI bot reply to any text prompt directly."""
    data = await request.json()
    prompt = data.get("prompt", "Hello, what services does Growhaz provide?")
    phone = (data.get("phone") or "").strip()
    reply, latency_ms, engine_used = await asyncio.to_thread(get_ai_reply, prompt, phone)
    groq_key = get_env_var("GROQ_API_KEY")
    deepseek_key = get_env_var("DEEPSEEK_API_KEY")
    return JSONResponse({
        "prompt": prompt,
        "reply": reply,
        "engine": engine_used,
        "latency_ms": latency_ms,
        "deepseek_configured": bool(deepseek_key and not deepseek_key.startswith("sk_your")),
        "groq_configured": bool(groq_key and not groq_key.startswith("gsk_your"))
    })

@app.get("/api/dashboard/settings")
async def get_settings():
    deepseek_key = get_env_var("DEEPSEEK_API_KEY")
    masked_deepseek = (deepseek_key[:4] + "..." + deepseek_key[-4:]) if len(deepseek_key) > 8 else ("Configured" if deepseek_key else "")
    groq_key = get_env_var("GROQ_API_KEY")
    masked_key = (groq_key[:4] + "..." + groq_key[-4:]) if len(groq_key) > 8 else ("Configured" if groq_key else "")
    meta_token = get_env_var("WHATSAPP_TOKEN")
    masked_token = (meta_token[:4] + "..." + meta_token[-4:]) if len(meta_token) > 8 else ("Configured" if meta_token else "")

    return JSONResponse({
        "deepseek_api_key_set": bool(deepseek_key and not deepseek_key.startswith("sk_your")),
        "deepseek_api_key_masked": masked_deepseek,
        "deepseek_model": get_env_var("DEEPSEEK_MODEL", "deepseek-chat"),
        "groq_api_key_set": bool(groq_key and not groq_key.startswith("gsk_your")),
        "groq_api_key_masked": masked_key,
        "groq_model": get_env_var("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "whatsapp_token_set": bool(meta_token and not meta_token.startswith("your_meta")),
        "whatsapp_token_masked": masked_token,
        "whatsapp_phone_number_id": get_env_var("WHATSAPP_PHONE_NUMBER_ID"),
        "whatsapp_verify_token": get_env_var("WHATSAPP_VERIFY_TOKEN", "whatsapp_groq_bot_secret_123")
    })

@app.post("/api/dashboard/settings")
async def save_settings(request: Request):
    data = await request.json()
    deepseek_key = data.get("deepseek_api_key", "").strip()
    deepseek_model = data.get("deepseek_model", "deepseek-chat").strip()
    groq_key = data.get("groq_api_key", "").strip()
    groq_model = data.get("groq_model", "llama-3.3-70b-versatile").strip()
    whatsapp_token = data.get("whatsapp_token", "").strip()
    whatsapp_phone_id = data.get("whatsapp_phone_number_id", "").strip()
    whatsapp_verify_token = data.get("whatsapp_verify_token", "whatsapp_groq_bot_secret_123").strip()

    if deepseek_key and not deepseek_key.startswith("..."):
        os.environ["DEEPSEEK_API_KEY"] = deepseek_key
        try: set_key(ENV_PATH, "DEEPSEEK_API_KEY", deepseek_key)
        except Exception: pass

    if deepseek_model:
        os.environ["DEEPSEEK_MODEL"] = deepseek_model
        try: set_key(ENV_PATH, "DEEPSEEK_MODEL", deepseek_model)
        except Exception: pass

    if groq_key and not groq_key.startswith("..."):
        os.environ["GROQ_API_KEY"] = groq_key
        try: set_key(ENV_PATH, "GROQ_API_KEY", groq_key)
        except Exception: pass
    
    if groq_model:
        os.environ["GROQ_MODEL"] = groq_model
        try: set_key(ENV_PATH, "GROQ_MODEL", groq_model)
        except Exception: pass

    if whatsapp_token and not whatsapp_token.startswith("..."):
        os.environ["WHATSAPP_TOKEN"] = whatsapp_token
        try: set_key(ENV_PATH, "WHATSAPP_TOKEN", whatsapp_token)
        except Exception: pass

    if whatsapp_phone_id:
        os.environ["WHATSAPP_PHONE_NUMBER_ID"] = whatsapp_phone_id
        try: set_key(ENV_PATH, "WHATSAPP_PHONE_NUMBER_ID", whatsapp_phone_id)
        except Exception: pass

    if whatsapp_verify_token:
        os.environ["WHATSAPP_VERIFY_TOKEN"] = whatsapp_verify_token
        try: set_key(ENV_PATH, "WHATSAPP_VERIFY_TOKEN", whatsapp_verify_token)
        except Exception: pass

    return JSONResponse({"success": True, "message": "Settings updated successfully!"})

@app.delete("/api/dashboard/messages")
async def delete_messages_endpoint(request: Request):
    """Delete one or multiple selected messages."""
    data = await request.json()
    ids = data.get("ids", [])
    if isinstance(ids, (int, str)):
        ids = [ids]
    success = db.delete_messages(ids)
    return JSONResponse({"success": success, "deleted_count": len(ids)})

@app.delete("/api/dashboard/conversation")
async def delete_conv(phone: str = Query(...)):
    success = db.delete_contact(phone)
    return JSONResponse({"success": success, "phone": phone})

@app.delete("/api/dashboard/clear")
async def clear_all():
    success = db.clear_data()
    return JSONResponse({"success": success})

@app.get("/api/dashboard/webhooks")
async def get_webhooks():
    return JSONResponse({"logs": db.get_webhook_logs(50)})

# Backward compatibility direct chat
@app.post("/api/chat")
async def direct_chat(request: Request):
    data = await request.json()
    msg = data.get("message", "")
    phone = data.get("phone", "+18005550199")
    if not msg:
        return JSONResponse({"error": "Empty message"}, status_code=400)
    
    db.save_message(phone, "Customer", msg, "inbound", "simulator")
    set_typing_state(phone, True)
    try:
        reply, latency, engine = await asyncio.to_thread(get_ai_reply, msg, phone)
    finally:
        set_typing_state(phone, False)
    db.save_message(phone, "Support Agent (AI)", reply, "outbound", "simulator", "sent", None, engine, latency)
    return JSONResponse({"reply": reply, "model": engine, "latency_ms": latency})

# ====================================================================


# ====================================================================
# BULK BROADCAST & LEADS CRM ENDPOINTS
# ====================================================================

@app.post("/api/dashboard/broadcast")
async def bulk_broadcast(request: Request):
    """
    Send WhatsApp messages to multiple leads/numbers with rate limiting and logging.
    Supports both:
    1. Static broadcast: { "phone_numbers": [...], "message": "...", "recipient_names": {phone: name} }
    2. Hyper-personalized AI campaign: { "personalized_messages": [ { "phone": "...", "message": "...", "name": "...", "category": "...", "area": "...", "website": "..." } ] }
    """
    data = await request.json()
    personalized_items = data.get("personalized_messages", [])
    numbers_raw = data.get("phone_numbers", [])
    default_message = (data.get("message") or "").strip()
    send_via_meta = data.get("send_via_meta", True)
    add_as_leads = data.get("add_as_leads", True)
    lead_source = (data.get("lead_source") or "Bulk Broadcast").strip()
    raw_recipient_names = data.get("recipient_names") or {}
    recipient_names = {}
    if isinstance(raw_recipient_names, dict):
        for k, v in raw_recipient_names.items():
            nk = db.normalize_phone_key(k) or re.sub(r"\D", "", str(k or ""))
            if nk and str(v or "").strip():
                recipient_names[nk] = str(v).strip()

    # -------------------------------------------------------------
    # Case 1: Hyper-Personalized Broadcast (Each business has custom message)
    # -------------------------------------------------------------
    if personalized_items and isinstance(personalized_items, list):
        results = []
        sent_count = 0
        failed_count = 0
        
        for item in personalized_items:
            raw_phone = item.get("phone") or item.get("contact_number") or ""
            digits = db.normalize_phone_key(raw_phone) or re.sub(r'[^0-9]', '', str(raw_phone))
                
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
                    "error": "Missing or invalid phone number (requires 10+ digits with country code)"
                })
                continue
                
            if not item_msg:
                failed_count += 1
                results.append({
                    "phone": digits,
                    "name": lead_name or digits,
                    "status": "failed",
                    "error": "Message content was empty for this lead"
                })
                continue

            # Persist structured CSV/campaign business info into customer_profiles first so AI remembers it
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
            stored_profile = db.upsert_customer_profile(digits, overwrite_existing=True, **profile_kwargs)

            # Resolve any {{name}} / {{business}} / {{area}} variables before sending
            resolved_msg = render_template_placeholders(
                item_msg,
                phone=digits,
                explicit_name=lead_name,
                profile=stored_profile
            )
            display_name = lead_name or stored_profile.get("business_name") or stored_profile.get("contact_name") or "Growhaz Support"

            status = "sent"
            err_msg = None
            meta_res = {}
            
            if send_via_meta:
                success, meta_res = await asyncio.to_thread(send_meta_whatsapp_message, digits, resolved_msg)
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
                
            # Record to message history under the contact's phone
            db.save_message(
                phone_number=digits,
                sender_name=display_name,
                message=resolved_msg,
                direction="outbound",
                channel="ai_campaign" if send_via_meta else "simulator",
                status=status,
                raw_payload={"campaign": True, "lead_name": display_name, "meta_response": meta_res}
            )
            
            # Save or update in leads CRM
            if add_as_leads:
                lead_notes = f"{item_category} • {item_area}".strip(" •")
                db.add_or_update_lead(
                    phone_number=digits,
                    name=display_name if display_name != "Growhaz Support" else "Lead",
                    source=lead_source,
                    notes=lead_notes,
                    status="Contacted" if status in ["sent", "simulated"] else "New"
                )
                db.record_lead_messaged(digits, status="Contacted" if status in ["sent", "simulated"] else "Failed")
                
            results.append({
                "phone": digits,
                "name": display_name,
                "status": status,
                "error": err_msg,
                "resolved_message": resolved_msg
            })
            
            if send_via_meta and len(personalized_items) > 1:
                await asyncio.sleep(0.2)
                
        return JSONResponse({
            "success": True,
            "mode": "personalized",
            "total": len(personalized_items),
            "sent": sent_count,
            "failed": failed_count,
            "results": results
        })

    # -------------------------------------------------------------
    # Case 2: Standard Single-Message Broadcast to Phone Numbers
    # -------------------------------------------------------------
    if not default_message:
        return JSONResponse({"error": "Message content cannot be empty"}, status_code=400)
    
    if isinstance(numbers_raw, str):
        numbers_raw = [n.strip() for n in re.split(r'[\n,;]+', numbers_raw) if n.strip()]
    
    clean_numbers = []
    seen = set()
    for raw in numbers_raw:
        digits = db.normalize_phone_key(raw) or re.sub(r'[^0-9]', '', str(raw))
        if len(digits) >= 10 and digits not in seen:
            clean_numbers.append(digits)
            seen.add(digits)
            
    if not clean_numbers:
        return JSONResponse({"error": "No valid phone numbers found. Please enter 10+ digit numbers with country code."}, status_code=400)
        
    results = []
    sent_count = 0
    failed_count = 0
    
    for phone in clean_numbers:
        explicit_n = recipient_names.get(phone, "")
        profile = db.get_customer_profile(phone)
        if explicit_n and db._is_meaningful_profile_val(explicit_n, "contact_name"):
            profile = db.upsert_customer_profile(phone, overwrite_existing=False, contact_name=explicit_n, data_source="broadcast")
        final_msg = render_template_placeholders(default_message, phone=phone, explicit_name=explicit_n, profile=profile)
        display_name = _pick_real_recipient_name(explicit_n, profile, phone) or "Lead"

        status = "sent"
        err_msg = None
        meta_res = {}
        
        if send_via_meta:
            success, meta_res = await asyncio.to_thread(send_meta_whatsapp_message, phone, final_msg)
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
            
        # Record resolved message to history so inbox reflects exactly what was sent
        db.save_message(
            phone_number=phone,
            sender_name=display_name if display_name != "Lead" else "Growhaz Support",
            message=final_msg,
            direction="outbound",
            channel="bulk_broadcast" if send_via_meta else "simulator",
            status=status,
            raw_payload={"broadcast": True, "meta_response": meta_res}
        )
        
        # Save or update in leads table
        if add_as_leads:
            db.add_or_update_lead(
                phone_number=phone,
                name=display_name,
                source=lead_source,
                status="Contacted" if status in ["sent", "simulated"] else "New"
            )
            db.record_lead_messaged(phone, status="Contacted" if status in ["sent", "simulated"] else "Failed")
            
        results.append({
            "phone": phone,
            "name": display_name,
            "status": status,
            "error": err_msg,
            "resolved_message": final_msg
        })
        
        if send_via_meta and len(clean_numbers) > 1:
            await asyncio.sleep(0.2)
            
    return JSONResponse({
        "success": True,
        "mode": "standard",
        "total": len(clean_numbers),
        "sent": sent_count,
        "failed": failed_count,
        "results": results
    })


@app.post("/api/dashboard/ai-personalize-campaign")
async def ai_personalize_campaign(request: Request):
    """
    Generate customized, ecosystem-focused AI outreach messages concurrently across a list of businesses.
    Enriches missing context from customer_profiles DB when available, and never hallucinates fake names or areas.
    """
    try:
        from api.bot_engine import generate_personalized_campaign_pitch
        
        data = await request.json()
        leads = data.get("leads", [])
        campaign_goal = (data.get("campaign_goal") or "Helping integrate practical technology (website, automation & WhatsApp workflows) into your existing business ecosystem").strip()
        tone = (data.get("tone") or "friendly_warm").strip()
        custom_notes = (data.get("custom_notes") or "").strip()
        
        if not leads or not isinstance(leads, list):
            return JSONResponse({"error": "A list of leads/businesses is required."}, status_code=400)
            
        deepseek_key = get_env_var("DEEPSEEK_API_KEY")
        deepseek_model = get_env_var("DEEPSEEK_MODEL", "deepseek-chat")
        groq_key = get_env_var("GROQ_API_KEY")
        groq_model = get_env_var("GROQ_MODEL", "llama-3.3-70b-versatile")
        
        sem = asyncio.Semaphore(5)

        async def _gen_one(idx: int, lead: dict) -> dict:
            b_name = (lead.get("business_name") or lead.get("name") or lead.get("Business_Name") or "").strip()
            b_cat = (lead.get("category") or lead.get("business_category") or lead.get("Business_Category") or "").strip()
            b_area = (lead.get("area") or lead.get("area_or_locality") or lead.get("Area_or_Locality") or "").strip()
            b_phone = (lead.get("phone") or lead.get("contact_number") or lead.get("Contact_Number") or "").strip()
            b_web = (lead.get("website") or lead.get("website_url") or lead.get("Website_or_Social_Link") or "").strip()
            b_eco = (lead.get("existing_ecosystem") or "").strip()

            if b_phone:
                stored = db.get_customer_profile(b_phone)
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
                        deepseek_api_key=deepseek_key,
                        deepseek_model=deepseek_model,
                        groq_api_key=groq_key,
                        groq_model=groq_model,
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
            "leads": personalized_leads
        })
    except Exception as e:
        logger.error(f"[Campaign AI] Error in personalize campaign: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/dashboard/leads")
async def get_all_leads():
    """Retrieve all leads in CRM."""
    leads = db.get_leads()
    return JSONResponse({"leads": leads, "total": len(leads)})

@app.post("/api/dashboard/leads")
async def add_leads_endpoint(request: Request):
    """Add one or more leads without sending messages immediately."""
    data = await request.json()
    numbers_raw = data.get("phone_numbers", [])
    name = (data.get("name") or "Lead").strip()
    source = (data.get("source") or "Manual Import").strip()
    notes = (data.get("notes") or "").strip()
    status = (data.get("status") or "New").strip()
    
    if isinstance(numbers_raw, str):
        numbers_raw = [n.strip() for n in re.split(r'[\n,;]+', numbers_raw) if n.strip()]
        
    added = 0
    for raw in numbers_raw:
        digits = re.sub(r'[^0-9]', '', str(raw))
        if len(digits) == 10:
            digits = "91" + digits
        if len(digits) >= 10:
            db.add_or_update_lead(digits, name=name, source=source, status=status, notes=notes)
            added += 1
            
    return JSONResponse({"success": True, "added_count": added})

@app.delete("/api/dashboard/leads/{lead_id}")
async def delete_lead_endpoint(lead_id: int):
    """Delete a lead by ID."""
    success = db.delete_lead(lead_id)
    return JSONResponse({"success": success, "lead_id": lead_id})

@app.put("/api/dashboard/leads/{lead_id}/status")
async def update_lead_status_endpoint(lead_id: int, request: Request):
    """Update lead pipeline status."""
    data = await request.json()
    status = data.get("status", "Contacted")
    success = db.update_lead_status(lead_id, status)
    return JSONResponse({"success": success, "lead_id": lead_id, "status": status})

# ====================================================================
# 3. DASHBOARD USER INTERFACE (MODULAR TEMPLATE & STATIC JS)
# ====================================================================

@app.api_route("/dashboard", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the modular responsive Growhaz CRM dashboard HTML."""
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
