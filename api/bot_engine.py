import os
import time
import logging
import httpx
from groq import Groq

logger = logging.getLogger("bot_engine")

CUSTOMER_SUPPORT_SYSTEM_PROMPT = """You are the official Customer Support & Sales AI Representative chatting with clients on WhatsApp for Growhaz (Growhaz Secure Systems).

Website: https://www.growhaz.in/
Founder & CEO: Om Uikey
Contact Email: info.growhaz@gmail.com

ABOUT GROWHAZ:
Growhaz is a next-generation cybersecurity, trust infrastructure, and secure digital solutions company based in India, serving clients worldwide.

CORE SERVICES, PRICING & LINKS:
1. Website Security Vulnerability Scanning (Alpha G5 / Alpha G1 / Alpha G3):
   - Fast, automated security testing (SQLi, XSS, IDOR, API security, auth bypass) completed in under 5 minutes.
   - Pricing:
     • AlphaG1: ₹1,999 per scan (Basic security audit for small websites)
     • AlphaG5: ₹4,999 per scan (Advanced audit, API testing & IDOR checks — Most Popular)
     • AlphaG3: ₹9,999 per scan (Enterprise-grade full penetration testing & attack vectors)
   - Link: https://www.growhaz.in/security-tools

2. Appify Your Website (Mobile App Conversion):
   - Convert any website into a high-performance native Android & iOS mobile app.
   - Features: Firebase push notifications, offline cache fallback, native navigation, and app store deployment.
   - Link: https://www.growhaz.in/development

3. Secure Web & Full-Stack Development:
   - High-performance, SEO-optimized, and security-hardened web solutions.
   - Pricing:
     • Static Website: ₹20,000 (100% Lighthouse SEO score, security certified, responsive)
     • Dynamic Web App: Starting from ₹60,000 (Full CRUD, E-commerce, CRM, admin dashboard)
     • Custom Enterprise Systems: Tailored quotes
   - Link: https://www.growhaz.in/development

4. Blockchain Document Verification:
   - Tamper-proof on-chain document issuance and verification for certificates, degrees, and legal contracts.
   - Instant verification portal: https://www.growhaz.in/verify
   - Blockchain overview: https://www.growhaz.in/blockchain

5. SEO & Workflow Automation:
   - Basic SEO (Lighthouse 100%, Core Web Vitals): ₹8,000
   - Monthly On-Page SEO: ₹10,000/month
   - Custom Workflow Automation: ₹8,000+
   - Link: https://www.growhaz.in/seo

6. Cybersecurity Mentorship:
   - Practical 1-on-1 ethical hacking, web penetration testing, and secure coding mentorship.
   - Link: https://www.growhaz.in/mentorship

YOUR RESPONSE GUIDELINES:
1. Warm, polite, professional, and helpful tone.
2. Naturally include the exact website link (e.g. https://www.growhaz.in/...) when discussing services, pricing, or bookings so users can easily visit the site.
3. Use clean WhatsApp formatting (*bold*, • bullet points, emojis).
4. Keep messages mobile-friendly and concise.
5. If someone asks for human support, reassure them that our team lead Om Uikey / support specialist will connect shortly."""

def run_smart_customer_support_fallback(user_prompt: str) -> str:
    """
    Dedicated Customer Support Agent fallback logic for Growhaz.
    Provides rich, accurate information and website links when AI APIs are unreachable.
    """
    p = user_prompt.lower().strip()
    
    # Human Agent Handover Request
    if any(w in p for w in ["human", "agent", "person", "representative", "specialist", "talk to someone", "call me"]):
        return (
            "👤 *Connecting to Growhaz Support Team*\n\n"
            "I've flagged this chat for our specialist team and founder Om Uikey. A human representative will review your query and reply here shortly.\n\n"
            "🌐 *Explore Growhaz:* https://www.growhaz.in/\n"
            "📧 *Direct Email:* info.growhaz@gmail.com"
        )

    # Security Scans (Alpha G1, G5, Penetration Testing)
    if any(w in p for w in ["security", "scan", "vulnerability", "hack", "penetration", "alphag1", "alphag5", "audit", "firewall"]):
        return (
            "🛡️ *Growhaz Website Security Scans*\n\n"
            "We offer automated vulnerability scanning that discovers SQLi, XSS, IDOR, and API flaws in under 5 minutes:\n\n"
            "• *AlphaG1 (Basic Scan):* ₹1,999 / scan\n"
            "• *AlphaG5 (Advanced Audit):* ₹4,999 / scan (Most Popular)\n"
            "• *AlphaG3 (Full Pentest):* ₹9,999 / scan\n\n"
            "🔗 *Start a scan on our portal:* https://www.growhaz.in/security-tools\n"
            "Reply with your website URL to get started!"
        )

    # Bookings & Appointments / Consultations
    if any(w in p for w in ["book", "appointment", "schedule", "reserve", "slot", "meeting", "consultation"]):
        return (
            "📅 *Growhaz Consultation & Service Booking*\n\n"
            "Thank you for reaching out to Growhaz! I've logged your consultation request.\n\n"
            "📌 *Quick Details to Share:*\n"
            "• Your project or website URL\n"
            "• Preferred date & time\n"
            "• Service needed (Security Scan, App Development, or Blockchain)\n\n"
            "🔗 *Book directly online:* https://www.growhaz.in/contact"
        )

    # Appify / Mobile App Conversion / Web Development
    if any(w in p for w in ["app", "appify", "apk", "android", "ios", "website", "develop", "web development", "design"]):
        return (
            "🚀 *Growhaz Development & Appify Services*\n\n"
            "We build secure, high-speed digital products:\n\n"
            "• *Appify Your Website:* Turn any site into native Android/iOS apps with push notifications & offline support.\n"
            "• *Static Website (100% SEO):* ₹20,000\n"
            "• *Dynamic Web Application:* From ₹60,000\n"
            "• *Custom Enterprise Tools:* Tailored quotes\n\n"
            "🔗 *View portfolio & packages:* https://www.growhaz.in/development"
        )

    # Blockchain Document Verification
    if any(w in p for w in ["blockchain", "verify", "certificate", "document", "degree", "authenticity"]):
        return (
            "🔗 *Growhaz Blockchain Document Verification*\n\n"
            "Tamper-proof on-chain verification for certificates, legal contracts, and academic degrees.\n\n"
            "• Instant verification portal\n"
            "• Cryptographic authenticity proof\n\n"
            "🔍 *Verify a document now:* https://www.growhaz.in/verify\n"
            "🌐 *Learn more:* https://www.growhaz.in/blockchain"
        )

    # Pricing & Quotes
    if any(w in p for w in ["price", "cost", "rate", "quote", "how much", "charges", "estimate"]):
        return (
            "💰 *Growhaz Transparent Pricing*\n\n"
            "• *Security Scans:* AlphaG1 (₹1,999) | AlphaG5 (₹4,999) | AlphaG3 (₹9,999)\n"
            "• *Web Development:* Static (₹20,000) | Dynamic (From ₹60,000)\n"
            "• *SEO Services:* ₹8,000 (One-time) | ₹10,000/mo (On-page)\n"
            "• *Workflow Automation:* From ₹8,000\n\n"
            "🔗 *See full pricing breakdown:* https://www.growhaz.in/pricing"
        )

    # Order / Project Status Tracking
    if any(w in p for w in ["status", "track", "order", "where is", "progress"]):
        return (
            "📦 *Growhaz Project & Scan Status*\n\n"
            "Please share your registered email or Project/Scan ID. Our team will look up the status and update you immediately!\n\n"
            "🌐 *Check live dashboard:* https://www.growhaz.in/"
        )

    # Greetings
    if any(w in p for w in ["hi", "hello", "hey", "hola", "good morning", "good evening", "namaste", "start"]):
        return (
            "👋 *Welcome to Growhaz!* (https://www.growhaz.in/)\n\n"
            "Hello! I am your Growhaz AI Assistant. How can we help you today?\n\n"
            "1️⃣ 🛡️ *Website Security Audit & Scans* (https://www.growhaz.in/security-tools)\n"
            "2️⃣ 📱 *Appify Website to Mobile App* (https://www.growhaz.in/development)\n"
            "3️⃣ 💻 *Secure Web & Full-Stack Development*\n"
            "4️⃣ 🔗 *Blockchain Document Verification* (https://www.growhaz.in/verify)\n"
            "5️⃣ 💰 *View Pricing Plans* (https://www.growhaz.in/pricing)\n"
            "6️⃣ 👤 *Speak with Our Human Team*\n\n"
            "Simply reply with your question or option number!"
        )

    # General Helpful Support Response
    return (
        f"Thank you for contacting Growhaz! 😊\n\n"
        f"I received your message: \"{user_prompt}\"\n\n"
        f"You can explore all our cybersecurity and development solutions at our official website:\n"
        f"👉 https://www.growhaz.in/\n\n"
        f"How else may I assist you today?"
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
            with httpx.Client(timeout=30.0) as client:
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

    # 2. Try Groq AI Fallback
    if groq_api_key and groq_api_key.strip() and not groq_api_key.startswith("gsk_your"):
        try:
            client = Groq(api_key=groq_api_key.strip())
            model_to_use = groq_model if groq_model else "llama-3.3-70b-versatile"
            
            completion = client.chat.completions.create(
                model=model_to_use,
                messages=[
                    {"role": "system", "content": CUSTOMER_SUPPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_completion_tokens=1024
            )
            latency = round((time.time() - start) * 1000, 2)
            reply = completion.choices[0].message.content or "No response generated."
            return reply, latency, f"Groq ({model_to_use})"
        except Exception as e:
            logger.warning(f"Groq API error ({e}), using support agent fallback.")

    # 3. Smart rule-based fallback
    latency = round((time.time() - start) * 1000, 2)
    reply = run_smart_customer_support_fallback(user_prompt)
    return reply, max(latency, 10.0), "Customer Support Agent"
