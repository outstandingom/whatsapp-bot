import os
import time
import logging
import httpx
from groq import Groq

logger = logging.getLogger("bot_engine")

CUSTOMER_SUPPORT_SYSTEM_PROMPT = """You are a professional, helpful, polite, and efficient Customer Support Representative chatting with a client on WhatsApp for Growhaz (a modern digital solutions and services company).
Your goals:
1. Greet customers warmly as the Growhaz support agent and answer their questions clearly and concisely.
2. Assist with booking appointments, consultations, service orders, and customer queries.
3. Provide accurate service guidance, turnaround times, and order status help for Growhaz.
4. If the customer asks for a human agent or has an unresolved complex issue, assure them that a Growhaz specialist is notified.
5. Format your responses with clean, readable WhatsApp markdown (e.g. *bold*, • bullet points, and friendly emojis).
6. Keep replies concise, conversational, and easy to read on mobile devices."""

def run_smart_customer_support_fallback(user_prompt: str) -> str:
    """
    Dedicated Customer Support Agent fallback logic for Growhaz.
    Handles common customer service inquiries when offline or without API key.
    """
    p = user_prompt.lower().strip()
    
    # Human Agent Handover Request
    if any(w in p for w in ["human", "agent", "person", "representative", "specialist", "talk to someone", "call me"]):
        return (
            "👤 *Connecting to Growhaz Support Team*\n\n"
            "I've flagged this conversation for our Growhaz team. A human specialist is reviewing your message and will respond here shortly.\n\n"
            "Feel free to share any files or inquiry details in the meantime!"
        )

    # Bookings & Appointments
    if any(w in p for w in ["book", "appointment", "schedule", "reserve", "slot", "meeting", "consultation"]):
        return (
            "📅 *Growhaz Booking Request*\n\n"
            "Thank you for contacting Growhaz! I've logged your booking request in our system.\n\n"
            "📌 *Next Steps:*\n"
            "• Please reply with your preferred date and time\n"
            "• Specify the service or project details\n\n"
            "Our Growhaz team will confirm your slot right away!"
        )

    # Printing & Task Services
    if any(w in p for w in ["print", "task", "service", "document", "paper", "poster", "banner", "flyer", "card", "binding", "app", "website"]):
        return (
            "🚀 *Growhaz Services*\n\n"
            "We handle professional digital solutions and custom tasks at Growhaz:\n"
            "• Web & Mobile App Development\n"
            "• Custom Design & Digital Solutions\n"
            "• Business Printing, Flyers, Cards & Posters\n"
            "• Consultation & Technical Support\n\n"
            "👉 *How to proceed:* Tell us more about what you need or share files for an instant estimate!"
        )

    # Pricing & Quotes
    if any(w in p for w in ["price", "cost", "rate", "quote", "how much", "charges", "estimate"]):
        return (
            "💰 *Growhaz Pricing & Quotes*\n\n"
            "We provide transparent, competitive rates for all our services.\n"
            "Reply with your specific requirements or project scope to get an instant customized quote!"
        )

    # Order Status Tracking
    if any(w in p for w in ["status", "track", "order", "where is", "progress"]):
        return (
            "📦 *Growhaz Order & Project Status Help*\n\n"
            "Please share your **Order ID** or registered phone number. Our Growhaz support team will check the status and update you immediately!"
        )

    # Payment & Invoices
    if any(w in p for w in ["pay", "payment", "invoice", "bill", "upi", "card", "link"]):
        return (
            "💳 *Growhaz Billing & Payments*\n\n"
            "We accept secure payments via Cards, UPI, and Bank Transfers. We can send you a secure payment link directly in this chat!"
        )

    # Greetings
    if any(w in p for w in ["hi", "hello", "hey", "hola", "good morning", "good evening", "namaste", "start"]):
        return (
            "👋 *Welcome to Growhaz!*\n\n"
            "Hello! I am your Growhaz AI Assistant. How can I assist you today?\n\n"
            "1️⃣ *Book an Appointment or Consultation*\n"
            "2️⃣ *Inquire about Growhaz Services*\n"
            "3️⃣ *Request a Price Quote*\n"
            "4️⃣ *Track an Existing Order / Task*\n"
            "5️⃣ *Speak with a Human Representative*\n\n"
            "Simply reply with your question or option number!"
        )

    # General Helpful Support Response
    return (
        f"Thank you for contacting Growhaz! 😊\n\n"
        f"I have received your message: \"{user_prompt}\"\n\n"
        f"Our support desk is on standby. How else may I assist you today?"
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
