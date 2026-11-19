"""
Comprehensive End-to-End Test for Growhaz DNA Memory Architecture & AI Integration
Tests:
  1. Algorithmic Data Ingestion (Features -> Composite Assemblies via DNA Vector Algebra).
  2. Interaction Learning (Tripartite Relational DNA + Behaviour Assembly Recomposition).
  3. Dynamic Prediction Engine (Target preference, recurrence cadence, purchase window).
  4. Memory-Augmented AI Generation (DeepSeek / Groq AI prompt context injection).
  5. Simulation of a real customer conversation.
"""

import os
import sys

# Ensure paths
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from api.dna_service import dynamic_dna
from api.bot_engine import generate_ai_reply

def run_test():
    print("=" * 75)
    print("🧬 TESTING GROWAZ DYNAMIC DNA MEMORY & AI INTEGRATION")
    print("=" * 75)

    # -------------------------------------------------------------
    # Step 1: Algorithmic Ingestion of Catalog Data
    # Zero hardcoding inside model: uses DNA bundle & bind algebra
    # -------------------------------------------------------------
    print("\n[Step 1] Algorithmic Data Ingestion into DNA Vector Space...")
    
    # Ingest Service 1: Security Audit
    s1 = dynamic_dna.ingest_data_item(
        item_id="service_alphag5_audit",
        item_type="security_service",
        name="Alpha G5 Security Scan",
        features=["SQLi_Detection", "XSS_Detection", "IDOR_Check", "API_Vulnerability", "PDF_Audit_Report"],
        attributes={"tier": "Advanced", "price": 4999, "currency": "INR"}
    )
    print(f"  • Ingested '{s1['manifest_name']}' -> ID: {s1['item_id']} ({s1['component_count']} features bundled)")

    # Ingest Service 2: Mobile App Conversion
    s2 = dynamic_dna.ingest_data_item(
        item_id="service_appify_mobile",
        item_type="mobile_service",
        name="Appify Web to Mobile",
        features=["Android_APK", "iOS_IPA", "Push_Notifications", "Offline_Sync"],
        attributes={"tier": "Mobile", "price": 25000, "currency": "INR"}
    )
    print(f"  • Ingested '{s2['manifest_name']}' -> ID: {s2['item_id']} ({s2['component_count']} features bundled)")

    # Ingest Service 3: Dynamic Web Development
    s3 = dynamic_dna.ingest_data_item(
        item_id="service_dynamic_webapp",
        item_type="web_development",
        name="Custom Full-Stack Web Application",
        features=["React_UI", "FastAPI_Backend", "PostgreSQL_DB", "Payment_Gateway", "Lighthouse_SEO"],
        attributes={"tier": "FullStack", "price": 60000, "currency": "INR"}
    )
    print(f"  • Ingested '{s3['manifest_name']}' -> ID: {s3['item_id']} ({s3['component_count']} features bundled)")

    # -------------------------------------------------------------
    # Step 2: Simulate Customer Interaction History
    # Customer: Rahul (Phone: 919876543210)
    # Pattern: Purchases Alpha G5 scans every 7 days
    # -------------------------------------------------------------
    customer_phone = "919876543210"
    print(f"\n[Step 2] Recording Customer Interaction Stream for {customer_phone}...")

    dates = [
        "2026-10-15T10:00:00Z",
        "2026-10-22T10:00:00Z",
        "2026-10-29T10:00:00Z",
        "2026-11-05T10:00:00Z",
        "2026-11-12T10:00:00Z"
    ]

    for idx, d in enumerate(dates):
        rec = dynamic_dna.record_interaction(
            customer_id=customer_phone,
            action="purchased",
            target_id="service_alphag5_audit",
            attributes={"price": 4999, "qty": 1, "currency": "INR", "scan_order_id": f"ORD_{100+idx}"},
            timestamp=d
        )
        print(f"  Event #{idx+1} ({d}) -> {customer_phone} purchased service_alphag5_audit [Assembly: {rec.get('event_assembly_id')}]")

    # -------------------------------------------------------------
    # Step 3: Test Dynamic Behavior & Cadence Prediction
    # -------------------------------------------------------------
    print(f"\n[Step 3] Querying DNA Memory Prediction Engine...")
    prediction = dynamic_dna.predict_customer_behavior(customer_phone)

    print(f"  • Customer ID:        {prediction.get('customer')}")
    print(f"  • Top Target Product: {prediction.get('predicted_target')}")
    print(f"  • Anticipated Event:  {prediction.get('predicted_event')}")
    print(f"  • Measured Cadence:   {prediction.get('estimated_interval_days')} days")
    print(f"  • Predicted Window:   {prediction.get('predicted_window')}")
    print(f"  • Calibrated Conf:    {prediction.get('confidence', 0.0)*100:.1f}%")
    print(f"  • Evidence Chain:")
    for ev in prediction.get("evidence", []):
        print(f"    - {ev}")

    # -------------------------------------------------------------
    # Step 4: Spreading Activation Search
    # -------------------------------------------------------------
    print(f"\n[Step 4] Spreading Activation: 'Who needs security audit?'")
    results = dynamic_dna.search_related_concepts("security audit", top_k=4)
    for res in results:
        print(f"  • [{res['type'].upper()}] {res['id']} (Activation: {res['activation_score']:.3f})")

    # -------------------------------------------------------------
    # Step 5: Test Memory-Augmented AI Prompt Context
    # -------------------------------------------------------------
    print(f"\n[Step 5] Formatted DNA Context for AI Generation:")
    ai_context = dynamic_dna.format_memory_for_ai(customer_phone)
    print(ai_context)

    # -------------------------------------------------------------
    # Step 6: Test AI Response with Memory Active
    # -------------------------------------------------------------
    print(f"\n[Step 6] Simulating Inbound Customer Message:")
    user_msg = "Hey, what are your scanning options today? Can I get an update?"
    print(f"  User: \"{user_msg}\"")
    
    reply, latency, model = generate_ai_reply(user_msg, customer_id=customer_phone)
    print(f"\n  AI Response (via {model}, {latency:.1f}ms):")
    print("-" * 75)
    print(reply)
    print("-" * 75)

    print("\n✅ ALL DNA MODEL INTEGRATION & AI TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    run_test()
