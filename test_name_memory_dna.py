"""
Test verification for User Identity & Long-Term Memory Extraction via DNA Knowledge Graph.
Scenario:
Turn 1: "Hi, my name is Om Uikey"
Turn 2: "Can you scan my website?"
Turn 3: "What is my name?" -> Should correctly return "Your name is Om Uikey!"
Turn 4: "My company is Growhaz Technologies"
Turn 5: "Where do I work?" -> Should correctly return "Growhaz Technologies"
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.bot_engine import generate_ai_reply
from api.dna_service import dynamic_dna
from api import db

def test_user_memory():
    test_phone = "919876543210"
    db.init_db()

    # Clear previous messages for this phone to simulate a clean test
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE phone_number LIKE ?", (f"%{test_phone}%",))
    conn.commit()
    conn.close()

    print("===========================================================================")
    print("🧬 TESTING USER IDENTITY & LONG-TERM MEMORY (DNA KNOWLEDGE GRAPH)")
    print(f"Customer Phone: {test_phone}")
    print("===========================================================================\n")

    test_conversations = [
        ("Hi, my name is Om Uikey", "Introduction & Name Stated"),
        ("Can you run a vulnerability scan on my website?", "Security Service Query"),
        ("What is my name?", "Long-Term Memory Recall: Name"),
        ("My company is Growhaz Technologies", "Company Stated"),
        ("Where do I work?", "Long-Term Memory Recall: Company")
    ]

    for i, (user_msg, scenario) in enumerate(test_conversations, 1):
        print(f"--- Turn {i}: {scenario} ---")
        print(f"User: \"{user_msg}\"")

        db.save_message(
            phone_number=test_phone,
            sender_name="Customer",
            message=user_msg,
            direction="inbound",
            channel="meta_whatsapp"
        )

        reply, latency, model = generate_ai_reply(user_msg, customer_id=test_phone)

        db.save_message(
            phone_number=test_phone,
            sender_name="Support Agent",
            message=reply,
            direction="outbound",
            channel="meta_whatsapp"
        )

        print(f"Agent ({model}, {latency:.1f}ms):")
        print(reply)
        print()

        if i == 3:
            assert "Om Uikey" in reply, f"FAILURE: Agent failed to recall customer name! Got: {reply}"
            print("  >>> Verified: Name 'Om Uikey' recalled from DNA Memory! ✅")

        if i == 5:
            assert "Growhaz Technologies" in reply, f"FAILURE: Agent failed to recall company! Got: {reply}"
            print("  >>> Verified: Company 'Growhaz Technologies' recalled from DNA Memory! ✅")

    # Verify DNA Decoded Profile
    decoded = dynamic_dna.decode_customer_facts(test_phone)
    print("\n[Decoded DNA Long-Term Memory Profile for Customer]:")
    for k, v in decoded.items():
        print(f"  • {k}: {v}")

    assert decoded.get("has_name") == "Om Uikey"
    assert decoded.get("has_company") == "Growhaz Technologies"

    print("\n✅ ALL DNA MEMORY & IDENTITY TESTS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_user_memory()
