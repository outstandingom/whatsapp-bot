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

def run_smart_customer_support_fallback(
    user_prompt: str,
    history: Optional[List[dict]] = None,
    customer_id: str = "",
    dna_analysis: Optional[dict] = None
) -> str:
    """
    Context-aware rule-based fallback when AI APIs (DeepSeek/Groq) are unavailable.
    Directly grounded in the DNA Modal's activated relationship graph and customer memories.
    Guarantees non-repetitive, contextually relevant replies.
    """
    p = user_prompt.lower().strip()
    dna = dna_analysis or {}
    prediction = dna.get("prediction", {})
    activated_nodes = [n.get("id", "") for n in dna.get("activated_nodes", [])]
    relationships = dna.get("relationships", [])

    p_clean = re.sub(r'[^\w\s]', ' ', p)
    words = set(p_clean.split())

    # Explicit link requests only - never trigger on "my website" or "my site"
    wants_link = any(phrase in p for phrase in ["link", "send link", "share link", "give link", "url", "portal link", "website link", "where to visit", "where can i visit", "online portal"])
    has_history = bool(history and len(history) > 1)
    has_dna_memory = bool(prediction and prediction.get("predicted_event") != "unknown")
    raw_target = prediction.get("predicted_target") or (activated_nodes[0] if activated_nodes else "")
    top_target = "" if (raw_target.isdigit() or raw_target.startswith("+") or raw_target.startswith("asmb_event")) else raw_target

    # Retrieve last bot message to prevent duplicate canned replies
    last_bot_reply = ""
    for h in reversed(history or []):
        if h.get("direction") == "outbound" or h.get("role") == "assistant":
            last_bot_reply = (h.get("message") or "").strip()
            break

    customer_facts = dna.get("customer_facts", {})
    newly_learned = dna.get("newly_learned_facts", {})
    customer_name = customer_facts.get("has_name") or ""

    direct_answers = dna.get("direct_answers", {})

    # 0a. User just stated profile facts in this dialogue turn (Immediate Learning Acknowledgment)
    if "has_name" in newly_learned:
        name = newly_learned["has_name"]
        return f"Nice to meet you, {name}! 😊 I've saved that in my long-term memory. How can I assist you with Growhaz services today?"
    if "has_company" in newly_learned:
        comp = newly_learned["has_company"]
        return f"Noted that you're with {comp}! 🏢 How can Growhaz help support your team and business today?"
    if "has_role" in newly_learned:
        role = newly_learned["has_role"]
        return f"Great to connect with a {role}! How can Growhaz assist your work today?"

    # 0b. Direct Relational DNA Knowledge Resolution (Pillars 1, 2, 3)
    if "user_name" in direct_answers:
        name = direct_answers["user_name"]
        first = name.split()[0]
        return f"Your name is {name}! 😊 I have it remembered in my long-term memory. How can I assist you today, {first}?"
    if "user_company" in direct_answers:
        comp = direct_answers["user_company"]
        return f"You're with {comp}! How can I assist with your company's technical requirements?"
    if "user_website" in direct_answers:
        site = direct_answers["user_website"]
        return f"Your website is {site}! Would you like us to run a security vulnerability scan on it?"
    if "founder" in direct_answers:
        founder = direct_answers["founder"]
        return (
            f"👤 *Leadership at Growhaz:*\n\n"
            f"Growhaz was founded by *{founder}*, who serves as the Founder and Lead AI Architect.\n\n"
            f"He leads our research in AI cognitive architectures, the proprietary DNA Memory System, and full-stack cybersecurity audit engines."
        )
    if "payment_methods" in direct_answers:
        return (
            f"💳 *Accepted Payment Methods at Growhaz:*\n\n"
            f"• *UPI:* Instant payment via Google Pay, PhonePe, Paytm, and BHIM UPI.\n"
            f"• *Cards:* All major Credit & Debit cards (Visa, MasterCard, RuPay, Amex).\n"
            f"• *NetBanking:* Supported across all major Indian banks.\n"
            f"• *Bank Transfer (NEFT/IMPS/RTGS):* Available for corporate and milestone contracts.\n"
            f"• *International:* Stripe & Wire Transfer for global clients (USD, EUR, GBP).\n\n"
            f"We issue official GST-compliant tax invoices for all transactions."
        )
    if "turnaround_times" in direct_answers:
        times = direct_answers["turnaround_times"]
        lines = [f"• *{s.replace('_', ' ').title()}:* {t.replace('_', ' ').title()}" for s, t in times.items()]
        return "⏱️ *Growhaz Service Turnaround Times:*\n\n" + "\n".join(lines) + "\n\nWhich project do you need estimated?"

    # 0c. General company info request
    if any(phrase in p for phrase in ["about growhaz", "what is growhaz", "where are you located", "contact details", "contact email", "headquarters"]):
        return (
            "🏢 *About Growhaz Technologies:*\n\n"
            "Growhaz is a technology and cybersecurity solutions firm based in India, founded by Om Uikey.\n\n"
            "• *Core Solutions:* AlphaG security scanning, Appify mobile app conversion, custom full-stack web platforms, and blockchain verification.\n"
            "• *Headquarters:* India\n"
            "• *Official Website:* https://www.growhaz.in\n"
            "• *Official Email:* info.growhaz@gmail.com\n"
            "• *WhatsApp Support:* Available directly here 24/7!"
        )

    # 1. Human Handover Request
    if any(w in words for w in ["human", "agent", "person", "representative", "specialist"]) or any(phrase in p for phrase in ["talk to someone", "call me"]):
        res = (
            "👤 *Connecting you with our team*\n\n"
            "I've flagged this conversation for our founder Om Uikey and our technical team. "
            "A human specialist will reply directly here on WhatsApp shortly!"
        )
        if wants_link:
            res += "\n\n🌐 You can also reach us via email at info.growhaz@gmail.com or visit https://www.growhaz.in/"
        return res

    # 2. Thank you / Closing
    if any(w in words for w in ["thank", "thanks", "thx", "dhanyawad", "shukriya", "great", "perfect", "bye"]):
        return (
            "You're very welcome! 😊 Glad I could help.\n\n"
            "Feel free to reply anytime if you have more questions or need technical support. Have a wonderful day!"
        )

    # 3. Detected Website URL in user message (e.g. example.com, https://...)
    has_url = bool(re.search(r'(https?://[^\s]+|[a-zA-Z0-9-]+\.(com|in|org|net|io|co|ai|app))', user_prompt))
    if has_url:
        if "appify" in top_target or any(w in words for w in ["app", "mobile", "apk", "ios"]):
            return (
                "Got your website URL for mobile conversion! 📱\n\n"
                "We can convert this directly into native Android & iOS mobile apps with push notifications, offline mode, and biometric auth.\n\n"
                "• *Starter Android APK:* ₹15,000 (Complete native bundle)\n"
                "• *Dual Platform (Android + iOS):* ₹25,000 (App Store & Play Store ready)\n\n"
                "Would you like us to generate a mobile preview package for your website?"
            )
        return (
            "Got your website URL! 🛡️\n\n"
            "We can initiate a security vulnerability scan or review right away. Would you prefer:\n"
            "• *AlphaG1 (Basic Audit):* ₹1,999 (Under 5-minute automated scan for SQLi & XSS)\n"
            "• *AlphaG5 (Advanced Audit):* ₹4,999 (In-depth API & IDOR vulnerability testing — Most Popular)\n"
            "• *AlphaG3 (Full Pentest):* ₹9,999 (Comprehensive manual penetration testing)\n\n"
            "Let me know which tier you'd like, and I'll confirm your scan!"
        )

    # 4. Pricing & Quotes (Prioritized over generic topic keywords)
    if any(w in words for w in ["price", "cost", "rate", "quote", "charges", "estimate", "pricing"]) or "how much" in p:
        if wants_link:
            return "Here is our complete online pricing breakdown: https://www.growhaz.in/pricing"
        if any(w in words for w in ["app", "appify", "apk", "mobile"]) or "appify" in top_target:
            return (
                "📱 *Appify Mobile App Conversion Pricing*\n\n"
                "• *Starter Android APK:* ₹15,000 (Native Android APK + push notifications + offline cache)\n"
                "• *Full Android & iOS Store Package:* ₹25,000 (Dual platform, Play Store & App Store ready, biometric login)\n\n"
                "Would you like us to build your mobile app? Just share your website URL!"
            )
        if any(w in words for w in ["security", "scan", "vulnerability", "alphag5", "alphag1", "alphag3", "audit"]) or "service_alphag5_audit" in top_target:
            return (
                "🛡️ *Growhaz Security Audit Pricing*\n\n"
                "• *AlphaG1 (Basic Audit):* ₹1,999 (Automated scan for SQLi & XSS in under 5 minutes)\n"
                "• *AlphaG5 (Advanced Audit):* ₹4,999 (Full API & IDOR testing + 24hr remediation PDF — Most Popular)\n"
                "• *AlphaG3 (Comprehensive Pentest):* ₹9,999 (Human hacker validation & zero-day checks)\n\n"
                "Send over your website URL to initiate your scan!"
            )
        if any(w in words for w in ["web", "website", "develop", "development"]):
            return (
                "💻 *Growhaz Web Development Pricing*\n\n"
                "• *Static SEO Website:* ₹20,000 (100% Google Lighthouse score, lightning fast)\n"
                "• *Dynamic Full-Stack Web App:* Starting at ₹60,000 (Custom CRM, payment gateway, user auth, dynamic database)\n\n"
                "Tell us about your project requirements, and we'll prepare a custom milestone quote!"
            )
        return (
            "💰 *Growhaz Pricing Overview*\n\n"
            "• *Security Scans:* AlphaG1 (₹1,999) | AlphaG5 (₹4,999) | AlphaG3 (₹9,999)\n"
            "• *Appify Mobile App:* Android APK (₹15,000) | Android + iOS (₹25,000)\n"
            "• *Web Development:* Static (₹20,000) | Dynamic (From ₹60,000)\n"
            "• *SEO & Speed:* ₹8,000 one-time | ₹10,000/mo ongoing\n"
            "• *Workflow Automation:* From ₹8,000\n\n"
            "Which service would you like a customized quote for?"
        )

    # 5. Process / "How does it work" / "How to start"
    if any(w in p for w in ["how does it work", "how it works", "process", "steps", "how to start", "timeline", "how long"]):
        if "appify" in top_target:
            return (
                "⚙️ *How Appify Works*\n\n"
                "1️⃣ *Submit URL:* Send us your website or web app URL.\n"
                "2️⃣ *App Engine Compilation:* We bundle native Android APK & iOS build with push notification SDK.\n"
                "3️⃣ *Delivery:* You receive testing APK in 3-5 days ready for Google Play & App Store upload.\n\n"
                "Ready to transform your site into an app?"
            )
        return (
            "⚙️ *How Growhaz Works*\n\n"
            "1️⃣ *Submit Details:* Send us your website or application URL.\n"
            "2️⃣ *Automated & Manual Scan:* Our security engine audits for SQLi, XSS, IDOR, and exposed API keys.\n"
            "3️⃣ *Executive Report:* You receive a full PDF vulnerability report with step-by-step remediation fixes within 24 hours.\n\n"
            "Would you like us to run a preliminary check on your website today?"
        )

    has_substantive_intent = any(w in words for w in [
        "scan", "security", "vulnerability", "audit", "alphag1", "alphag5", "alphag3",
        "app", "appify", "apk", "android", "ios",
        "website", "web", "develop", "development",
        "price", "cost", "rate", "quote", "charges", "pricing"
    ]) or has_url or any(phrase in p for phrase in ["how much", "how does it work", "how it works", "scanning options", "scanning"])

    # 6. Greetings (Only if pure greeting or no substantive intent)
    is_greeting = any(w in words for w in ["hi", "hello", "hey", "hola", "namaste"]) or any(phrase in p for phrase in ["good morning", "good evening", "good afternoon"])
    if is_greeting and not has_substantive_intent:
        if customer_name:
            first = customer_name.split()[0]
            if has_history:
                return f"Hey {first}! 👋 Happy to have you back. How can I assist you further today?"
            return f"Hey {first}! 👋 Welcome to Growhaz. How can I help you today?"
        if has_history:
            if has_dna_memory and top_target:
                target_name = top_target.replace("service_", "").replace("_", " ").title()
                return f"Hey again! 👋 Happy to continue where we left off regarding {target_name}. How can I assist you further?"
            return "Hey again! 👋 How can I assist you further with your project or security audit?"
        return (
            "Hey there! 👋 Welcome to Growhaz.\n\n"
            "How can I help you today? Feel free to ask about our website security scanning, mobile app conversion, web development, or pricing!"
        )

    # 7. Confirmation / Agreement / "Yes" / "Ok" / "Sure" / "Go ahead"
    if any(w in words for w in ["yes", "yeah", "yep", "sure", "ok", "okay", "interested", "proceed"]) or any(phrase in p for phrase in ["go ahead", "start now"]):
        if "appify" in top_target or any(w in words for w in ["app", "mobile"]):
            return (
                "Awesome! 🎉 To start your mobile app conversion, please share:\n"
                "1. Your website or store URL\n"
                "2. Your app name and preferred primary brand color\n\n"
                "Our team will prepare your native Android APK demo!"
            )
        return (
            "Awesome! 🎉 To get started, please share:\n"
            "1. Your website or app URL\n"
            "2. The best email address to send the detailed report/quote\n\n"
            "Our technical team will review it and initiate your service right away!"
        )

    # 8. Services / What do you offer
    if any(w in words for w in ["service", "services", "provide", "providing", "offer", "offering", "solution", "solutions"]) or any(phrase in p for phrase in ["what do you do", "what can you do", "list services"]):
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

    # 9. Security Scans specifically
    if any(w in words for w in ["security", "scan", "vulnerability", "hack", "penetration", "alphag1", "alphag5", "alphag3", "audit", "firewall", "sqli", "xss", "idor"]):
        if wants_link:
            return "You can launch a security vulnerability scan directly on our portal here: https://www.growhaz.in/security-tools"
        reply = (
            "🛡️ *Growhaz Website Security Scans*\n\n"
            "We offer automated vulnerability scanning that discovers SQLi, XSS, IDOR, and API flaws in under 5 minutes:\n\n"
            "• *AlphaG1 (Basic Audit):* ₹1,999 per scan\n"
            "• *AlphaG5 (Advanced Audit - Most Popular):* ₹4,999 per scan\n"
            "• *AlphaG3 (Full Pentest):* ₹9,999 per scan\n\n"
            "Would you like us to run a scan on your website? Just send me your website URL!"
        )
        if reply == last_bot_reply:
            return (
                "🛡️ We are ready to scan! Please provide your website or target IP address, "
                "and let us know if you want the AlphaG1 (₹1,999) or AlphaG5 (₹4,999) audit tier."
            )
        return reply

    # 10. Appify / Mobile App Conversion
    if any(w in words for w in ["app", "appify", "apk", "android", "ios"]) or any(phrase in p for phrase in ["convert to app", "mobile app"]):
        if wants_link:
            return "You can check out our Appify mobile conversion packages here: https://www.growhaz.in/development"
        reply = (
            "📱 *Appify by Growhaz*\n\n"
            "We convert any website or web application into fast native Android (APK) & iOS apps with push notifications, biometric login, and offline caching.\n\n"
            "Do you have an existing website URL you'd like to convert into a mobile app?"
        )
        if reply == last_bot_reply:
            return (
                "📱 For your mobile app conversion: We can start with your Android APK right away. "
                "Please share your website or store URL, and we'll review your compatibility and generate a demo preview!"
            )
        return reply

    # 11. Web Development
    if any(w in words for w in ["website", "develop", "development", "design", "redesign", "react", "ecommerce", "store"]):
        if wants_link:
            return "You can explore our web development services here: https://www.growhaz.in/development"
        return (
            "💻 *Growhaz Web Development*\n\n"
            "• *Static SEO-Certified Website:* ₹20,000 (100% Lighthouse SEO score)\n"
            "• *Dynamic Full-Stack Web App:* From ₹60,000 (CRUD, E-commerce, CRM, admin dashboard)\n\n"
            "Tell me a little about your project requirements, and we can prepare a tailored roadmap for you!"
        )

    # 12. Dynamic DNA Grounded Response (When DNA nodes are active)
    if "service_alphag5_audit" in activated_nodes or "service_alphag1_audit" in activated_nodes or "service_alphag3_audit" in activated_nodes:
        reply = (
            "🛡️ Regarding website security: We can audit your platform against SQL injection, XSS, and authorization flaws with our Alpha G5 engine in under 5 minutes.\n\n"
            "Would you like us to run a check? Send over your website or API endpoint URL to begin!"
        )
        if reply != last_bot_reply:
            return reply

    if "service_appify_mobile" in activated_nodes:
        reply = (
            "📱 Regarding mobile conversion: With Appify, we bundle your web application into high-performance native Android & iOS builds.\n\n"
            "Feel free to share your website link, and we'll review it for mobile app conversion."
        )
        if reply != last_bot_reply:
            return reply

    if "service_dynamic_webapp" in activated_nodes or "service_static_website" in activated_nodes:
        reply = (
            "💻 Regarding web development: Whether you need an ultra-fast static site or a custom dynamic full-stack portal with payments and CRM, we can build it.\n\n"
            "Could you share a brief summary of what your project needs?"
        )
        if reply != last_bot_reply:
            return reply
        return (
            "💻 Regarding web development: Whether you need an ultra-fast static site or a custom dynamic full-stack portal with payments and CRM, we can build it.\n\n"
            "Could you share a brief summary of what your project needs?"
        )

    # 13. Context-aware follow-up (when conversation is active)
    if has_history:
        return (
            "Got it! Could you tell me a bit more about what you're looking for, or share your website / project details? "
            "I'll help you pick the best solution right away."
        )

    # 14. Default first-contact message
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

    # -------------------------------------------------------------
    # STEP 1 & 2: First, the message goes directly to the DNA Modal.
    # The DNA Modal discovers related relationships and active memories.
    # -------------------------------------------------------------
    dna_analysis = {}
    graph_context = ""
    try:
        from api.dna_service import dynamic_dna
        dna_analysis = dynamic_dna.process_message_through_dna(
            customer_id=customer_id or "guest",
            message=user_prompt
        )
        graph_context = dna_analysis.get("graph_context", "")
    except Exception as e:
        logger.debug(f"DNA processing error: {e}")

    # STEP 3: Inject DNA Modal's activated relationships into AI System Prompt
    system_prompt = CUSTOMER_SUPPORT_SYSTEM_PROMPT
    if graph_context:
        system_prompt += "\n\n" + graph_context

    # Retrieve Multi-Turn Conversation History from Database
    conversation_history = []
    if customer_id:
        try:
            from api import db
            raw_history = db.get_messages(phone_number=customer_id, limit=8)
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
    reply = run_smart_customer_support_fallback(
        user_prompt,
        history=conversation_history,
        customer_id=customer_id,
        dna_analysis=dna_analysis
    )
    return reply, max(latency, 10.0), "Customer Support Agent"


def generate_personalized_campaign_pitch(
    business_name: str,
    category: str = "",
    area: str = "",
    campaign_goal: str = "",
    tone: str = "friendly_warm",
    custom_notes: str = "",
    deepseek_api_key: str = "",
    deepseek_model: str = "deepseek-chat",
    groq_api_key: str = "",
    groq_model: str = "llama-3.3-70b-versatile"
) -> tuple[str, str]:
    """
    Generate an authentic, highly personalized WhatsApp outreach message tailored specifically to a business lead.
    Tries DeepSeek AI, Groq AI, and falls back to our intelligent category template engine.
    """
    clean_name = (business_name or "Valued Business").strip().strip('"').strip("'")
    clean_category = (category or "Business").strip().strip('"').strip("'")
    clean_area = (area or "your area").strip().strip('"').strip("'")
    clean_goal = (campaign_goal or "Website security scan, web & app development, and automated WhatsApp customer booking").strip()

    prompt = (
        f"Write a concise, high-converting WhatsApp outreach message for this business:\n"
        f"- Business Name: {clean_name}\n"
        f"- Category / Industry: {clean_category}\n"
        f"- City / Locality: {clean_area}\n"
        f"- Outreach Offer / Value Proposition: {clean_goal}\n"
        f"- Tone: {tone}\n"
        f"- Custom Notes: {custom_notes}\n\n"
        f"Instructions:\n"
        f"1. Greet them warmly by business name.\n"
        f"2. Mention their category and locality naturally.\n"
        f"3. Explain the practical benefit to their specific business (e.g. 24/7 automated orders, appointments, or website security).\n"
        f"4. Include 2-3 relevant emojis.\n"
        f"5. End with a polite, non-pushy question asking if they would like a quick 2-minute demo on WhatsApp.\n"
        f"6. Return ONLY the message text. Do not wrap in quotes or add metadata."
    )

    llm_messages = [
        {"role": "system", "content": "You are an expert WhatsApp marketing copywriter who creates personalized, authentic, polite, and effective B2B outreach messages for local business owners."},
        {"role": "user", "content": prompt}
    ]

    # Try DeepSeek
    if deepseek_api_key and deepseek_api_key.strip() and not deepseek_api_key.startswith("sk_your"):
        try:
            m = deepseek_model.strip() if deepseek_model else "deepseek-chat"
            with httpx.Client(timeout=8.0) as client:
                res = client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {deepseek_api_key.strip()}", "Content-Type": "application/json"},
                    json={"model": m, "messages": llm_messages, "temperature": 0.7, "max_tokens": 500}
                )
                if res.status_code == 200:
                    ans = res.json()["choices"][0]["message"]["content"].strip()
                    if ans:
                        return ans, f"DeepSeek ({m})"
        except Exception as e:
            logger.warning(f"[Campaign AI] DeepSeek failed: {e}")

    # Try Groq
    if groq_api_key and groq_api_key.strip() and not groq_api_key.startswith("gsk_your"):
        try:
            m = groq_model.strip() if groq_model else "llama-3.3-70b-versatile"
            with httpx.Client(timeout=8.0) as client:
                res = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_api_key.strip()}", "Content-Type": "application/json"},
                    json={"model": m, "messages": llm_messages, "temperature": 0.7, "max_tokens": 500}
                )
                if res.status_code == 200:
                    ans = res.json()["choices"][0]["message"]["content"].strip()
                    if ans:
                        return ans, f"Groq ({m})"
        except Exception as e:
            logger.warning(f"[Campaign AI] Groq failed: {e}")

    # Smart Category-Driven Fallback Engine
    cat_lower = clean_category.lower()
    if any(k in cat_lower for k in ["bakery", "cake", "sweet", "pastry"]):
        msg = f"Namaste {clean_name} team! 🍰 Hope everything is sweet in {clean_area}. We know how popular your bakery delights are with local customers! Growhaz helps food & bakery businesses in {clean_area} receive cake orders and inquiries 24/7 directly on WhatsApp without manual typing. Would you like a quick 2-minute demo of how this can boost your festive orders? 😊"
    elif any(k in cat_lower for k in ["cafe", "restaurant", "dhaba", "pizza", "food", "dining", "fast food", "bites", "biryani"]):
        msg = f"Hi {clean_name} team! 🍽️✨ Hope business is flourishing in {clean_area}. As a favorite dining spot, managing table reservations and weekend customer rush can get overwhelming. Growhaz provides an automated WhatsApp assistant that shares menus, books tables, and gathers reviews 24/7. May I share a quick 1-minute preview with you?"
    elif any(k in cat_lower for k in ["salon", "beauty", "makeup", "parlour", "spa"]):
        msg = f"Hi {clean_name} team! 💇‍♀️ Greetings from Growhaz. As a premier salon & beauty hub in {clean_area}, weekend appointment requests can be hard to manage manually. Our WhatsApp booking assistant lets clients reserve slots 24/7 without waiting. Would you be open to seeing a quick 2-minute demo?"
    elif any(k in cat_lower for k in ["coaching", "classes", "academy", "library", "school", "education"]):
        msg = f"Namaste {clean_name} team! 📚 As a reputed coaching center in {clean_area}, answering student & parent inquiries about batches and fees takes hours. Our automated WhatsApp bot answers queries 24/7 and records admissions leads. Shall I share a quick sample with you?"
    elif any(k in cat_lower for k in ["doctor", "clinic", "hospital", "medical", "health", "dental"]):
        msg = f"Namaste {clean_name} team! 🩺 Greetings from Growhaz. For healthcare practices in {clean_area}, streamlining patient appointments and timings is essential. Our WhatsApp assistant manages schedules and updates patients automatically. Would you be open to a quick 2-minute walkthrough?"
    elif any(k in cat_lower for k in ["mobile", "electronics", "repair", "computer"]):
        msg = f"Hello {clean_name} team! 📱 Greetings from Growhaz. As a trusted electronics & mobile shop in {clean_area}, customers frequently ask for repair status and gadget prices. Our WhatsApp bot automatically responds to product inquiries and price lists 24/7. Would you like to see a quick sample?"
    elif any(k in cat_lower for k in ["mart", "supermarket", "grocery", "bazaar", "store", "hardware", "plywood", "clothing", "dairy"]):
        msg = f"Hello {clean_name} team! 🛒 Hope business is thriving in {clean_area}. Growhaz helps retail & store owners stay connected with customers via automated WhatsApp product catalogs and quick order updates. Would you be interested in a quick 2-minute demo?"
    else:
        msg = f"Hello {clean_name} team! 👋 Greetings from Growhaz. We admire your work as a leading {clean_category} in {clean_area}. We help local businesses automate customer inquiries, appointments, and marketing directly on WhatsApp. Would you be open to a quick 2-minute preview of how this can help grow your business? Cheers!"

    return msg, "AI Category Engine"
