import os
import time
import logging
from groq import Groq

logger = logging.getLogger("bot_engine")

CUSTOMER_SUPPORT_SYSTEM_PROMPT = """You are a professional, helpful, polite, and efficient Customer Support Representative chatting with a client on WhatsApp for printingtask (a professional printing, document, and custom printing services company).
Your goals:
1. Greet customers warmly as the printingtask support agent and answer their questions clearly and concisely.
2. Assist with booking appointments, consultations, service orders, and printing tasks (color/BW documents, posters, flyers, banners, business cards, binding, lamination, and custom design).
3. Provide accurate pricing guidance, turnaround times, and order status help for printingtask.
4. If the customer asks for a human agent or has an unresolved complex issue, assure them that a printingtask specialist is notified.
5. Format your responses with clean, readable WhatsApp markdown (e.g. *bold*, • bullet points, and friendly emojis).
6. Keep replies concise, conversational, and easy to read on mobile devices."""

def run_smart_customer_support_fallback(user_prompt: str) -> str:
    """
    Dedicated Customer Support Agent fallback logic for printingtask.
    Handles common customer service inquiries when offline or without API key.
    """
    p = user_prompt.lower().strip()
    
    # Human Agent Handover Request
    if any(w in p for w in ["human", "agent", "person", "representative", "specialist", "talk to someone", "call me"]):
        return (
            "👤 *Connecting to printingtask Support Team*\n\n"
            "I've flagged this conversation for our printingtask team. A human specialist is reviewing your message and will respond here shortly.\n\n"
            "Feel free to share any files or order details in the meantime!"
        )

    # Bookings & Appointments
    if any(w in p for w in ["book", "appointment", "schedule", "reserve", "slot", "meeting", "consultation"]):
        return (
            "📅 *printingtask Booking Request*\n\n"
            "Thank you for contacting printingtask! I've logged your booking request in our system.\n\n"
            "📌 *Next Steps:*\n"
            "• Please reply with your preferred date and time\n"
            "• Specify if you need printing, consultation, or a custom task\n\n"
            "Our printingtask team will confirm your slot right away!"
        )

    # Printing & Task Services
    if any(w in p for w in ["print", "task", "service", "document", "paper", "poster", "banner", "flyer", "card", "binding"]):
        return (
            "🖨️ *printingtask Document & Print Services*\n\n"
            "We handle all custom printing and document tasks at printingtask:\n"
            "• High-resolution Color & B/W Documents\n"
            "• Business Cards, Flyers, Menus & Brochures\n"
            "• Large Format Banners & Posters\n"
            "• Spiral Binding, Lamination & Custom Finishing\n\n"
            "👉 *How to proceed:* Send us your PDF/image file or dimensions for an instant quote!"
        )

    # Pricing & Quotes
    if any(w in p for w in ["price", "cost", "rate", "quote", "how much", "charges", "estimate"]):
        return (
            "💰 *printingtask Pricing Guide*\n\n"
            "Here is our standard rate breakdown:\n"
            "• *B/W Printing:* $0.05 / page\n"
            "• *High Quality Color:* $0.25 / page\n"
            "• *Business Cards (Set of 100):* from $15\n"
            "• *Custom Task / Design:* Based on project specifications\n\n"
            "Reply with your quantity or task details to get an exact quote!"
        )

    # Order Status Tracking
    if any(w in p for w in ["status", "track", "order", "where is", "progress"]):
        return (
            "📦 *printingtask Order Status Help*\n\n"
            "Please share your **Order ID** or phone number associated with the order. Our printingtask support team will check the production status and update you immediately!"
        )

    # Payment & Invoices
    if any(w in p for w in ["pay", "payment", "invoice", "bill", "upi", "card", "link"]):
        return (
            "💳 *printingtask Billing & Payments*\n\n"
            "We accept credit/debit cards, UPI, and online transfers. Once your quote is finalized, we will share a secure payment link directly in this chat!"
        )

    # Greetings
    if any(w in p for w in ["hi", "hello", "hey", "hola", "good morning", "good evening", "namaste", "start"]):
        return (
            "👋 *Welcome to printingtask!*\n\n"
            "Hello! I am your printingtask AI Assistant. How can I assist you today?\n\n"
            "1️⃣ *Book an Appointment or Service*\n"
            "2️⃣ *Inquire about Printing & Custom Tasks*\n"
            "3️⃣ *Request a Price Quote*\n"
            "4️⃣ *Track an Existing Order*\n"
            "5️⃣ *Speak with a Human Representative*\n\n"
            "Simply reply with your query!"
        )

    # General Helpful Support Response
    return (
        f"Thank you for contacting printingtask! 😊\n\n"
        f"I have received your message: \"{user_prompt}\"\n\n"
        f"Our support desk is on standby. How else may I assist you with your booking or project today?"
    )

def generate_ai_reply(user_prompt: str, groq_api_key: str = "", groq_model: str = "llama-3.3-70b-versatile") -> tuple[str, float, str]:
    """
    Generate Customer Support response with Groq Cloud AI or smart fallback.
    """
    start = time.time()
    
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

    # Smart fallback
    latency = round((time.time() - start) * 1000, 2)
    reply = run_smart_customer_support_fallback(user_prompt)
    return reply, max(latency, 10.0), "Customer Support Agent"
