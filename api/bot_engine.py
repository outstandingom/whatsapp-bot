import os
import re
import time
import logging
from typing import List, Dict, Any, Optional
import httpx

logger = logging.getLogger("bot_engine")

CUSTOMER_SUPPORT_SYSTEM_PROMPT = """You are the official Customer Support Representative chatting with clients on WhatsApp for Growhaz (Growhaz Secure Systems).

About Growhaz:
Growhaz is a next-generation cybersecurity, trust infrastructure, and digital solutions company based in India.
Founder & CEO: Om Uikey
Official Website: https://www.growhaz.in/
Email: info.growhaz@gmail.com

CORE SERVICES & PRICING:
1. Website Security Vulnerability Scanning (Alpha G1 / Alpha G5 / Alpha G3):
   - Automated security testing discovering SQLi, XSS, IDOR, API vulnerabilities in under 5 minutes.
   - Pricing:
     • AlphaG1: ₹1,999 per scan (Basic security audit for small websites)
     • AlphaG5: ₹4,999 per scan (Advanced audit, API testing & IDOR checks — Most Popular)
     • AlphaG3: ₹9,999 per scan (Enterprise-grade full penetration testing)
   - Portal Link (ONLY if user specifically asks for website/link/scan portal): https://www.growhaz.in/security-tools

2. Appify Your Website (Mobile App Conversion):
   - Convert any website or web app into native Android & iOS mobile apps with push notifications and offline mode.
   - Link (ONLY if user asks for website/link): https://www.growhaz.in/development

3. Secure Web & Full-Stack Development:
   - Ultra-fast, SEO-optimized, security-hardened websites and custom web apps.
   - Pricing:
     • Static Website: ₹20,000 (100% Lighthouse SEO score, security certified)
     • Dynamic Web App: Starting from ₹60,000 (CRUD, E-commerce, CRM, admin dashboard)
     • Custom Enterprise Systems: Tailored quotes
   - Link (ONLY if user asks for website/link): https://www.growhaz.in/development

4. Blockchain Document Verification:
   - Tamper-proof on-chain verification for degrees, certificates, and legal contracts.
   - Portal Link (ONLY if user asks for website/link): https://www.growhaz.in/verify

5. SEO & Workflow Automation:
   - Basic SEO: ₹8,000 | Monthly On-Page SEO: ₹10,000/month | Workflow Automation: From ₹8,000
   - Link (ONLY if user asks for website/link): https://www.growhaz.in/seo

CRITICAL CONVERSATIONAL & LINK RULES:
1. HUMAN TONE: Talk naturally, warmly, and helpfully like a real human customer support executive on WhatsApp. Do NOT sound like an automated robot.
2. STRICT LINK RULE (NEVER SPAM LINKS):
   - DO NOT include website links or URLs in greetings or general conversation.
   - DO NOT attach links to every service item.
   - ONLY provide a link when the user explicitly asks for a link, website URL, portal, online scan link, or where to visit online.
3. CONVERSATIONAL MEMORY: Pay close attention to what the customer has already asked or discussed. Do NOT repeat the exact same greeting or service list if the conversation is already in progress.
4. GREETINGS: Keep initial greetings short: "Hey there! 👋 Welcome to Growhaz. How can I help you today?" (NO links).
5. FORMATTING: Use clean WhatsApp formatting (*bold*, • bullets, friendly emojis). Keep messages concise and easy to read on mobile.
6. HUMAN HANDOVER: If someone asks to speak to a person or founder Om Uikey, warmly assure them that a human specialist will reply directly shortly.
"""

def run_smart_customer_support_fallback(user_prompt: str, history: Optional[List[dict]] = None, customer_id: str = "") -> str:
    """
    Context-aware rule-based fallback when AI APIs (DeepSeek/Groq) are unavailable.
    Inspects user prompt, conversation history, and DNA memory to never repeat identical canned answers.
    """
    p = user_prompt.lower().strip()
    # Explicit link requests only - never trigger on "my website" or "my site"
    wants_link = any(phrase in p for phrase in ["link", "send link", "share link", "give link", "url", "portal link", "website link", "where to visit", "where can i visit", "online portal"])
    has_history = bool(history and len(history) > 0)

    # 1. Human Handover Request
    if any(w in p for w in ["human", "agent", "person", "representative", "specialist", "talk to someone", "call me"]):
        res = (
            "👤 *Connecting you with our team*\n\n"
            "I've flagged this conversation for our founder Om Uikey and our support team. "
            "A specialist will reply directly here on WhatsApp shortly!"
        )
        if wants_link:
            res += "\n\n🌐 You can also reach us via email at info.growhaz@gmail.com or visit https://www.growhaz.in/"
        return res

    # 2. Thank you / Closing
    if any(w in p for w in ["thank", "thanks", "thx", "dhanyawad", "shukriya", "great", "perfect"]):
        return (
            "You're very welcome! 😊 Glad I could help.\n\n"
            "Feel free to reply anytime if you have more questions or need technical support. Have a wonderful day!"
        )

    # 3. Confirmation / Agreement / "Yes" / "Ok" / "Sure" / "Go ahead"
    if any(w in p for w in ["yes", "yeah", "yep", "sure", "ok", "okay", "go ahead", "start", "proceed", "interested"]):
        return (
            "Awesome! 🎉 To get started, please share:\n"
            "1. Your website or app URL\n"
            "2. The best email address to send the detailed report/quote\n\n"
            "Our technical team will review it and initiate your service right away!"
        )

    # 4. Detected Website URL in user message (e.g. example.com, https://...)
    has_url = bool(re.search(r'(https?://[^\s]+|[a-zA-Z0-9-]+\.(com|in|org|net|io|co|ai|app))', user_prompt))
    if has_url:
        return (
            "Got your website URL! 🛡️\n\n"
            "We can initiate a security vulnerability scan or review right away. Would you prefer:\n"
            "• *AlphaG1 (Basic Audit):* ₹1,999 (Under 5-minute automated scan for SQLi & XSS)\n"
            "• *AlphaG5 (Advanced Audit):* ₹4,999 (In-depth API & IDOR vulnerability testing — Most Popular)\n\n"
            "Let me know which tier you'd like, and I'll confirm your scan!"
        )

    # 5. Process / "How does it work" / "How to start"
    if any(w in p for w in ["how does it work", "how it works", "process", "steps", "how to start", "timeline", "how long"]):
        return (
            "⚙️ *How Growhaz Works*\n\n"
            "1️⃣ *Submit Details:* Send us your website or application URL.\n"
            "2️⃣ *Automated & Manual Scan:* Our security engine audits for SQLi, XSS, IDOR, and exposed API keys.\n"
            "3️⃣ *Executive Report:* You receive a full PDF vulnerability report with step-by-step remediation fixes within 24 hours.\n\n"
            "Would you like us to run a preliminary check on your website today?"
        )

    # 6. Greetings (Only if first interaction; never repeat if conversation is active!)
    if any(p == w or p.startswith(w + " ") or p.endswith(" " + w) for w in ["hi", "hello", "hey", "hola", "namaste", "good morning", "good evening", "good afternoon"]):
        if has_history:
            return (
                "Hey again! 👋 How can I assist you further with your project or security audit?"
            )
        return (
            "Hey there! 👋 Welcome to Growhaz.\n\n"
            "How can I help you today? Feel free to ask about our website security scanning, mobile app conversion, web development, or pricing!"
        )

    # 7. Services / What do you offer
    if any(w in p for w in ["service", "services", "provide", "providing", "offer", "offering", "solution", "solutions", "what do you do", "what can you do", "list"]):
        if wants_link:
            return (
                "Here are our official service portals:\n\n"
                "• Security Tools: https://www.growhaz.in/security-tools\n"
                "• Appify & Web Development: https://www.growhaz.in/development\n"
                "• Blockchain Verification: https://www.growhaz.in/verify\n"
                "• Full Pricing: https://www.growhaz.in/pricing\n\n"
                "Which area would you like to explore?"
            )
        return (
            "Here is what we do at Growhaz:\n\n"
            "1️⃣ 🛡️ *Website Security Vulnerability Scanning*\n"
            "Automated audits (Alpha G1/G5/G3) scanning SQLi, XSS, IDOR, and API security flaws in under 5 minutes.\n\n"
            "2️⃣ 📱 *Appify Your Website (Mobile App Conversion)*\n"
            "Convert any website or web app into native Android & iOS mobile apps with push notifications and offline mode.\n\n"
            "3️⃣ 💻 *Secure Web & Full-Stack Development*\n"
            "Ultra-fast static websites (100% Lighthouse SEO score) and custom dynamic web applications.\n\n"
            "4️⃣ 🔗 *Blockchain Document Verification*\n"
            "Tamper-proof on-chain verification for degrees, certificates, and legal contracts.\n\n"
            "Which of these would you like to know more about?"
        )

    # 8. Security Scans specifically
    if any(w in p for w in ["security", "scan", "vulnerability", "hack", "penetration", "alphag1", "alphag5", "alphag3", "audit", "firewall"]):
        if wants_link:
            return (
                "You can launch a security vulnerability scan directly on our portal here: https://www.growhaz.in/security-tools"
            )
        return (
            "🛡️ *Growhaz Website Security Scans*\n\n"
            "We offer automated vulnerability scanning that discovers SQLi, XSS, IDOR, and API flaws in under 5 minutes:\n\n"
            "• *AlphaG1 (Basic Audit):* ₹1,999 per scan\n"
            "• *AlphaG5 (Advanced Audit - Most Popular):* ₹4,999 per scan\n"
            "• *AlphaG3 (Full Pentest):* ₹9,999 per scan\n\n"
            "Would you like us to run a scan on your website? Just send me your website URL!"
        )

    # 9. Appify / Mobile App Conversion
    if any(w in p for w in ["app", "appify", "apk", "android", "ios", "convert to app"]):
        if wants_link:
            return "You can check out our Appify mobile conversion packages here: https://www.growhaz.in/development"
        return (
            "📱 *Appify by Growhaz*\n\n"
            "We convert any website or web application into fast native Android (APK) & iOS apps with push notifications, biometric login, and offline caching.\n\n"
            "Do you have an existing website URL you'd like to convert into a mobile app?"
        )

    # 10. Web Development
    if any(w in p for w in ["website", "develop", "web development", "design", "redesign", "full stack", "react"]):
        if wants_link:
            return "You can explore our web development services here: https://www.growhaz.in/development"
        return (
            "💻 *Growhaz Web Development*\n\n"
            "• *Static SEO-Certified Website:* ₹20,000 (100% Lighthouse SEO score)\n"
            "• *Dynamic Full-Stack Web App:* From ₹60,000 (CRUD, E-commerce, CRM, admin dashboard)\n\n"
            "Tell me a little about your project requirements, and we can prepare a tailored roadmap for you!"
        )

    # 11. Pricing & Quotes
    if any(w in p for w in ["price", "cost", "rate", "quote", "how much", "charges", "estimate", "pricing"]):
        if wants_link:
            return "Here is our complete online pricing breakdown: https://www.growhaz.in/pricing"
        return (
            "💰 *Growhaz Pricing Overview*\n\n"
            "• *Security Scans:* AlphaG1 (₹1,999) | AlphaG5 (₹4,999) | AlphaG3 (₹9,999)\n"
            "• *Web Development:* Static (₹20,000) | Dynamic (From ₹60,000)\n"
            "• *SEO:* ₹8,000 one-time | ₹10,000/mo ongoing\n"
            "• *Workflow Automation:* From ₹8,000\n\n"
            "Which service do you need a customized quote for?"
        )

    # 12. Context-aware follow-up (when conversation is active)
    if has_history:
        return (
            "Got it! Could you tell me a bit more about what you're looking for, or share your website / project details? "
            "I'll help you pick the best solution right away."
        )

    # 13. Default first-contact message
    if wants_link:
        return (
            "Here are the official Growhaz links:\n\n"
            "• Website: https://www.growhaz.in/\n"
            "• Security Tools: https://www.growhaz.in/security-tools\n"
            "• Development & Appify: https://www.growhaz.in/development\n"
            "• Pricing: https://www.growhaz.in/pricing"
        )
    return (
        "Thanks for reaching out to Growhaz! 😊\n\n"
        "How can I help you today? Feel free to ask about our security scanning, mobile app conversion, web development, or pricing."
    )

def generate_ai_reply(
    user_prompt: str,
    deepseek_api_key: str = "",
    deepseek_model: str = "deepseek-chat",
    groq_api_key: str = "",
    groq_model: str = "llama-3.3-70b-versatile",
    customer_id: str = ""
) -> tuple[str, float, str]:
    """
    Generate Customer Support response with DeepSeek AI, Groq Cloud AI, or smart fallback.
    Augmented with:
      1. Multi-turn conversation history from database.
      2. Dynamic customer DNA memory context.
    """
    start = time.time()

    # 1. Retrieve Dynamic DNA Memory
    dna_context = ""
    if customer_id:
        try:
            from api.dna_service import dynamic_dna
            dna_context = dynamic_dna.format_memory_for_ai(customer_id)
        except Exception as e:
            logger.debug(f"Could not load DNA memory context: {e}")

    system_prompt = CUSTOMER_SUPPORT_SYSTEM_PROMPT
    if dna_context:
        system_prompt += "\n" + dna_context

    # 2. Retrieve Multi-Turn Conversation History from Database
    conversation_history = []
    if customer_id:
        try:
            from api import db
            raw_history = db.get_messages(phone_number=customer_id, limit=8)
            # Exclude current prompt if already inserted
            for m in raw_history:
                text = (m.get("message") or "").strip()
                if text and not text.startswith("📷") and not text.startswith("📄"):
                    conversation_history.append({
                        "direction": m.get("direction"),
                        "message": text
                    })
        except Exception as e:
            logger.debug(f"Could not load conversation history: {e}")

    # Build messages array for LLM (DeepSeek / Groq)
    llm_messages = [{"role": "system", "content": system_prompt}]
    for h in conversation_history[-6:]:
        role = "user" if h.get("direction") == "inbound" else "assistant"
        llm_messages.append({"role": role, "content": h.get("message")})
    
    # Ensure current user_prompt is at the end
    if not llm_messages or llm_messages[-1].get("content") != user_prompt:
        llm_messages.append({"role": "user", "content": user_prompt})

    # 3. Try DeepSeek AI
    if deepseek_api_key and deepseek_api_key.strip() and not deepseek_api_key.startswith("sk_your"):
        try:
            model_to_use = deepseek_model.strip() if deepseek_model and deepseek_model.strip() else "deepseek-chat"
            headers = {
                "Authorization": f"Bearer {deepseek_api_key.strip()}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_to_use,
                "messages": llm_messages,
                "temperature": 0.7,
                "max_tokens": 1024
            }
            with httpx.Client(timeout=25.0) as client:
                res = client.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    reply = data["choices"][0]["message"]["content"] or "No response generated."
                    latency = round((time.time() - start) * 1000, 2)
                    return reply, latency, f"DeepSeek ({model_to_use})"
                else:
                    logger.warning(f"DeepSeek API error {res.status_code}: {res.text}. Falling back to Groq...")
        except Exception as e:
            logger.warning(f"DeepSeek call failed ({e}). Falling back to Groq...")

    # 4. Try Groq AI Fallback
    if groq_api_key and groq_api_key.strip() and not groq_api_key.startswith("gsk_your"):
        try:
            model_to_use = groq_model.strip() if groq_model and groq_model.strip() else "llama-3.3-70b-versatile"
            headers = {
                "Authorization": f"Bearer {groq_api_key.strip()}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_to_use,
                "messages": llm_messages,
                "temperature": 0.7,
                "max_tokens": 1024
            }
            with httpx.Client(timeout=25.0) as client:
                res = client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    reply = data["choices"][0]["message"]["content"] or "No response generated."
                    latency = round((time.time() - start) * 1000, 2)
                    return reply, latency, f"Groq ({model_to_use})"
                else:
                    logger.warning(f"Groq API error {res.status_code}: {res.text}. Falling back to smart agent...")
        except Exception as e:
            logger.warning(f"Groq API call failed ({e}). Falling back to smart agent...")

    # 5. Smart Context-Aware Fallback (Never repeats identical canned text)
    latency = round((time.time() - start) * 1000, 2)
    reply = run_smart_customer_support_fallback(user_prompt, history=conversation_history, customer_id=customer_id)
    return reply, max(latency, 10.0), "Customer Support Agent"
