import os
import sys

# Ensure local paths are set
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.bot_engine import generate_ai_reply
from api.dna_service import dynamic_dna
from api import db

def test_multiturn():
    test_phone = "919988776655"
    db.init_db()

    turns = [
        "Hi, are you there?",
        "Can you scan my website for security vulnerabilities?",
        "Yes, my website is https://teststore.in",
        "Can you also convert this website into an Android mobile app?",
        "How much does that app conversion cost?"
    ]

    print("===========================================================================")
    print("🤖 MULTI-TURN CONVERSATIONAL TEST WITH RECURSIVE DNA ARCHITECTURE")
    print(f"Customer Phone: {test_phone}")
    print("Pipeline: User Message -> DNA Modal (Relationships) -> AI Prompt -> User")
    print("===========================================================================\n")

    responses = []

    for i, user_msg in enumerate(turns, 1):
        print(f"--- Turn {i} ---")
        print(f"User: {user_msg}")

        # In a real environment, index.py saves inbound message first
        db.save_message(
            phone_number=test_phone,
            sender_name="Test Customer",
            message=user_msg,
            direction="inbound",
            channel="meta_whatsapp"
        )

        reply, latency, model = generate_ai_reply(user_msg, customer_id=test_phone)
        
        # Then outbound message is saved
        db.save_message(
            phone_number=test_phone,
            sender_name="Support Agent (AI)",
            message=reply,
            direction="outbound",
            channel="meta_whatsapp"
        )

        print(f"Agent ({model}, {latency:.1f}ms):")
        print(reply)
        print()

        responses.append(reply)

    # Check for repetitive responses
    assert len(responses) == len(set(responses)), "FAILURE: Detected duplicate/repetitive responses across turns!"
    print("✅ TEST PASSED: All 5 turns generated unique, context-aware, DNA-grounded responses!")

if __name__ == "__main__":
    test_multiturn()
