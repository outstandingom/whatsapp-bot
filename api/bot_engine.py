import os
import time
import logging
import httpx
from groq import Groq

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
3. WHEN ASKED FOR SERVICES (e.g. "what are your services", "what do you do", "list services"):
   - List the 5 core areas cleanly with bullet points or numbers in a friendly human tone.
   - Do NOT dump URLs under each service.
   - Ask them warmly which one they'd like more details on.
4. GREETINGS (e.g. "hi", "hello", "hey"):
   - Keep it short, warm, and natural: "Hey there! 👋 Welcome to Growhaz. How can I help you today?" (NO links).
5. FORMATTING: Use clean WhatsApp formatting (*bold*, • bullets, friendly emojis). Keep messages concise and easy to read on mobile.
6. HUMAN HANDOVER: If someone asks to speak to a person or founder Om Uikey, warmly assure them that a human specialist will reply directly shortly.
"""

def run_smart_customer_support_fallback(user_prompt: str) -> str:
    """
    Dedicated Human-like Customer Support Agent fallback for Growhaz.
    Provides warm, conversational answers and only provides links when explicitly requested.
    """
    p = user_prompt.lower().strip()
    wants_link = any(w in p for w in ["link", "url", "website", "portal", "site", "webpage", "online", "where can i", "send link", "visit"])

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

    # 2. Greetings
    if any(p == w or p.startswith(w + " ") or p.endswith(" " + w) for w in ["hi", "hello", "hey", "hola", "namaste", "good morning", "good evening", "good afternoon", "start"]):
        return (
            "Hey there! 👋 Welcome to Growhaz.\n\n"
            "How can I help you today? Feel free to ask about our website security scanning, mobile app conversion, web development, or blockchain services!"
        )

    # 3. Services / What do you offer / List of solutions
    if any(w in p for w in ["service", "services", "provide", "providing", "offer", "offering", "solution", "solutions", "what do you do", "what can you do", "list"]):
        if wants_link:
            return (
                "Here are our official service portals:\n\n"
                "• Security Tools & Scans: https://www.growhaz.in/security-tools\n"
                "• Appify & Web Development: https://www.growhaz.in/development\n"
                "• Blockchain Verification: https://www.growhaz.in/verify\n"
                "• SEO & Automation: https://www.growhaz.in/seo\n"
                "• Full Pricing: https://www.growhaz.in/pricing\n\n"
                "Let me know if you need help with any specific one!"
            )
        return (
            "Here is what we do at Growhaz:\n\n"
            "1️⃣ 🛡️ *Website Security Vulnerability Scanning*\n"
            "Fast, automated audits (Alpha G1/G5/G3) that scan your website for SQLi, XSS, IDOR, and API security flaws in under 5 minutes.\n\n"
            "2️⃣ 📱 *Appify Your Website (Mobile App Conversion)*\n"
            "We convert any website or web app into high-performance native Android & iOS mobile apps with push notifications and offline mode.\n\n"
            "3️⃣ 💻 *Secure Web & Full-Stack Development*\n"
            "Fast, SEO-optimized static websites (100% Lighthouse score) and custom full-stack dynamic web applications.\n\n"
            "4️⃣ 🔗 *Blockchain Document Verification*\n"
            "Tamper-proof on-chain verification for degrees, certificates, and legal contracts.\n\n"
            "5️⃣ 📈 *SEO & Workflow Automation*\n"
            "Core Web Vitals optimization and tailored business automation.\n\n"
            "Which of these would you like to know more about? Just let me know!"
        )

    # 4. Security Scans (Alpha G1, G5, Pentest)
    if any(w in p for w in ["security", "scan", "vulnerability", "hack", "penetration", "alphag1", "alphag5", "audit", "firewall"]):
        if wants_link:
            return (
                "You can launch a security vulnerability scan directly on our portal here: https://www.growhaz.in/security-tools\n\n"
                "Let me know if you need any assistance choosing the right scan tier!"
            )
        return (
            "🛡️ *Growhaz Website Security Scans*\n\n"
            "We offer automated vulnerability scanning that discovers SQLi, XSS, IDOR, and API flaws in under 5 minutes:\n\n"
            "• *AlphaG1 (Basic Audit):* ₹1,999 per scan\n"
            "• *AlphaG5 (Advanced Audit - Most Popular):* ₹4,999 per scan\n"
            "• *AlphaG3 (Full Pentest):* ₹9,999 per scan\n\n"
            "Would you like us to run a scan on your website? Just send me your website URL!"
        )

    # 5. Appify / Mobile App Conversion / Web Development
    if any(w in p for w in ["app", "appify", "apk", "android", "ios", "website", "develop", "web development", "design"]):
        if wants_link:
            return (
                "You can explore our development packages and mobile app conversion here: https://www.growhaz.in/development"
            )
        return (
            "🚀 *Growhaz Development & Appify Services*\n\n"
            "Here's what we offer:\n"
            "• *Appify:* Convert any website into native Android & iOS mobile apps with push notifications and offline cache.\n"
            "• *Static Website (100% SEO):* ₹20,000\n"
            "• *Dynamic Web Application:* Starting from ₹60,000\n\n"
            "Tell me a little about your project or share your website URL, and we can discuss the best approach!"
        )

    # 6. Blockchain Document Verification
    if any(w in p for w in ["blockchain", "verify", "certificate", "document", "degree", "authenticity"]):
        if wants_link:
            return (
                "You can verify documents on our blockchain portal here: https://www.growhaz.in/verify"
            )
        return (
            "🔗 *Growhaz Blockchain Document Verification*\n\n"
            "We provide tamper-proof on-chain verification for certificates, legal contracts, and academic degrees with cryptographic proof.\n\n"
            "Would you like to verify a document or integrate on-chain verification for your organization?"
        )

    # 7. Pricing & Quotes
    if any(w in p for w in ["price", "cost", "rate", "quote", "how much", "charges", "estimate", "pricing"]):
        if wants_link:
            return (
                "Here is our complete online pricing breakdown: https://www.growhaz.in/pricing"
            )
        return (
            "💰 *Growhaz Pricing Overview*\n\n"
            "• *Security Scans:* AlphaG1 (₹1,999) | AlphaG5 (₹4,999) | AlphaG3 (₹9,999)\n"
            "• *Web Development:* Static (₹20,000) | Dynamic (From ₹60,000)\n"
            "• *SEO:* ₹8,000 one-time | ₹10,000/mo ongoing\n"
            "• *Workflow Automation:* From ₹8,000\n\n"
            "Would you like a custom quote for your specific needs? Just let me know what you're looking for!"
        )

    # 8. Bookings & Appointments / Consultations
    if any(w in p for w in ["book", "appointment", "schedule", "reserve", "slot", "meeting", "consultation"]):
        if wants_link:
            return (
                "You can book a consultation directly through our online form: https://www.growhaz.in/contact"
            )
        return (
            "📅 *Book a Consultation with Growhaz*\n\n"
            "I'd be happy to schedule that for you! Please let me know:\n"
            "1. Your website or project details\n"
            "2. Preferred date and time\n"
            "3. The service you are interested in\n\n"
            "Our team will confirm your slot right away!"
        )

    # 9. Order / Project Status Tracking
    if any(w in p for w in ["status", "track", "order", "where is", "progress"]):
        return (
            "📦 *Growhaz Project & Scan Status*\n\n"
            "Please share your registered email or Scan/Project ID, and our team will check the status and update you right here!"
        )

    # 10. Default Natural Human Response (Never spam links)
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
    groq_model: str = "llama-3.3-70b-versatile"
) -> tuple[str, float, str]:
    """
    Generate Customer Support response with DeepSeek AI, Groq Cloud AI, or smart fallback.
    Priority order:
    1. DeepSeek API (deepseek-chat / deepseek-reasoner)
    2. Groq Cloud API (llama-3.3-70b-versatile / gpt-oss-120b)
    3. Rule-based Smart Customer Support Agent (Offline)
    """
    start = time.time()

    # 1. Try DeepSeek AI
    if deepseek_api_key and deepseek_api_key.strip() and not deepseek_api_key.startswith("sk_your"):
        try:
            model_to_use = deepseek_model.strip() if deepseek_model and deepseek_model.strip() else "deepseek-chat"
            headers = {
                "Authorization": f"Bearer {deepseek_api_key.strip()}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_to_use,
                "messages": [
                    {"role": "system", "content": CUSTOMER_SUPPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
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
                    logger.warning(f"DeepSeek API error {res.status_code}: {res.text}. Falling back...")
        except Exception as e:
            logger.warning(f"DeepSeek call failed ({e}). Falling back...")

    # 2. Try Groq AI Fallback (using direct HTTP call for maximum reliability)
    if groq_api_key and groq_api_key.strip() and not groq_api_key.startswith("gsk_your"):
        try:
            model_to_use = groq_model.strip() if groq_model and groq_model.strip() else "llama-3.3-70b-versatile"
            headers = {
                "Authorization": f"Bearer {groq_api_key.strip()}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_to_use,
                "messages": [
                    {"role": "system", "content": CUSTOMER_SUPPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
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
                    logger.warning(f"Groq API error {res.status_code}: {res.text}. Falling back...")
        except Exception as e:
            logger.warning(f"Groq API call failed ({e}). Falling back...")

    # 3. Smart rule-based fallback
    latency = round((time.time() - start) * 1000, 2)
    reply = run_smart_customer_support_fallback(user_prompt)
    return reply, max(latency, 10.0), "Customer Support Agent"
