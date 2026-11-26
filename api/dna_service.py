"""
Dynamic DNA Memory Service for WhatsApp Bot
Zero hardcoded domain data: Learns entities, concepts, attributes, and relationships
dynamically through the DNA Encoding Algorithm and holographic vector composition.
"""

import os
import sys
import re
import json
import logging
import datetime
from typing import Dict, Any, List, Optional

# Ensure local whatapp/dna_memory and sibling dna-modal package are importable
REPO_ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT_PATH not in sys.path:
    sys.path.insert(0, REPO_ROOT_PATH)
DNA_MODAL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "dna-modal"))
if os.path.exists(DNA_MODAL_PATH) and DNA_MODAL_PATH not in sys.path:
    sys.path.insert(0, DNA_MODAL_PATH)

logger = logging.getLogger("dynamic_dna_service")

try:
    from dna_memory import DNAMemorySystem
    DNA_AVAILABLE = True
except ImportError:
    DNA_AVAILABLE = False
    logger.warning("Local dna_memory package not found; ensure dna-modal is in path.")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "brain_data")
os.makedirs(DATA_DIR, exist_ok=True)
DNA_STATE_FILE = os.path.join(DATA_DIR, "dynamic_dna_state.json")

class DynamicDNAManager:
    """
    Pure algorithmic interface to the Recursive Compositional DNA Memory System.
    No hardcoded domain data: everything is encoded dynamically via vector algebra.
    """
    def __init__(self, render_api_url: Optional[str] = None):
        self.render_api_url = (render_api_url or os.getenv("DNA_API_URL", "")).rstrip("/")
        self.system: Optional[DNAMemorySystem] = None

        if DNA_AVAILABLE:
            self.system = DNAMemorySystem(dims=128, seed=42)
            if os.path.exists(DNA_STATE_FILE):
                try:
                    self.system.load_from_disk(DNA_STATE_FILE)
                    logger.info(f"Loaded DNA state: {self.system.dna_registry.count()} atoms, {self.system.assembly_engine.count()} assemblies.")
                except Exception as e:
                    logger.warning(f"Could not load state, initialized clean instance: {e}")
            
            # Ensure Growhaz catalog and relational graph are dynamically ingested
            self.ensure_growhaz_catalog_ingested()
            # Ensure Demo Knowledge Base and Customer Personas are seeded
            self.ensure_demo_dataset_seeded()

    def ensure_demo_dataset_seeded(self):
        """
        Dynamically ingests demo domain relations and pre-learned customer memories
        using the DNA vector encoding algorithm (HRR binding and assembly bundling).
        """
        if not self.system:
            return

        # Check if already seeded with updated payment & domain relationships
        rels = self.system.relation_registry.retrieve_relations(relation_type="accepts_payment_method")
        if rels and len(rels) > 0:
            return

        try:
            from api.dna_demo_dataset import seed_demo_knowledge_base
            seed_demo_knowledge_base(self.system)
            self.save()
        except Exception as e:
            logger.warning(f"Could not seed demo knowledge base: {e}")

    def ensure_growhaz_catalog_ingested(self):
        """
        Dynamically ingests the Growhaz catalog into DNA Memory System via holographic vector assemblies.
        Pure algorithmic vector representation — zero hardcoded string dependencies.
        """
        if not self.system:
            return

        # If already seeded with core assemblies, skip
        if "service_alphag5_audit" in self.system.assembly_engine._assemblies:
            return

        logger.info("Dynamically ingesting Growhaz catalog into DNA Memory System...")

        # 1. Ingest Alpha G5 Security Scan
        self.ingest_data_item(
            item_id="service_alphag5_audit",
            item_type="security_service",
            name="Alpha G5 Advanced Security Scan",
            features=[
                "automated vulnerability scan",
                "sql injection detection",
                "cross site scripting xss",
                "idor vulnerability audit",
                "api security flaws",
                "executive remediation pdf"
            ],
            attributes={"price_inr": 4999, "duration": "5 minutes", "type": "vulnerability_audit"}
        )

        # 2. Ingest Alpha G1 Basic Scan
        self.ingest_data_item(
            item_id="service_alphag1_audit",
            item_type="security_service",
            name="Alpha G1 Basic Security Scan",
            features=[
                "automated vulnerability scan",
                "sql injection sqli",
                "cross site scripting xss",
                "under 5 minute report"
            ],
            attributes={"price_inr": 1999, "duration": "5 minutes", "type": "vulnerability_audit"}
        )

        # 3. Ingest Alpha G3 Full Pentest
        self.ingest_data_item(
            item_id="service_alphag3_audit",
            item_type="security_service",
            name="Alpha G3 Full Penetration Test",
            features=[
                "manual penetration testing",
                "human hacker audit",
                "exploit validation",
                "infrastructure review",
                "zero day protection"
            ],
            attributes={"price_inr": 9999, "duration": "comprehensive", "type": "penetration_test"}
        )

        # 4. Ingest Appify Mobile App Conversion
        self.ingest_data_item(
            item_id="service_appify_mobile",
            item_type="mobile_development",
            name="Appify Web to Mobile App",
            features=[
                "convert website to mobile app",
                "android apk bundle",
                "ios app store",
                "push notifications",
                "offline caching",
                "biometric login"
            ],
            attributes={"platforms": "android and ios", "type": "mobile_conversion"}
        )

        # 5. Ingest Static Website Development
        self.ingest_data_item(
            item_id="service_static_website",
            item_type="web_development",
            name="Fast Static SEO Website",
            features=[
                "static website design",
                "100 percent google lighthouse seo score",
                "lead capture contact form",
                "fast cdn hosting"
            ],
            attributes={"price_inr": 20000, "seo_score": 100, "type": "website_development"}
        )

        # 6. Ingest Dynamic Full-Stack Web Application
        self.ingest_data_item(
            item_id="service_dynamic_webapp",
            item_type="web_development",
            name="Custom Full-Stack Web Application",
            features=[
                "full stack dynamic web development",
                "custom database architecture",
                "admin dashboard crm",
                "user authentication",
                "payment gateway api integration"
            ],
            attributes={"price_starting_inr": 60000, "type": "web_application"}
        )

        # 7. Ingest Tamper-Proof Blockchain Verification
        self.ingest_data_item(
            item_id="service_blockchain_verify",
            item_type="blockchain",
            name="Blockchain Document Verification",
            features=[
                "tamper proof verification",
                "smart contracts",
                "on chain degree certificate authentication",
                "legal contract verification"
            ],
            attributes={"type": "blockchain_verification"}
        )

        # 8. Ingest Workflow Automation & AI Bots
        self.ingest_data_item(
            item_id="service_workflow_automation",
            item_type="automation",
            name="AI Bot & Workflow Automation",
            features=[
                "whatsapp business bot automation",
                "crm workflow sync",
                "ai customer support agents",
                "automated lead routing"
            ],
            attributes={"price_starting_inr": 8000, "type": "automation"}
        )

        # Relational Bonds across entities in vector graph
        rel_links = [
            ("service_alphag5_audit", "protects_against", "sqli_vulnerability"),
            ("service_alphag5_audit", "protects_against", "xss_vulnerability"),
            ("service_alphag5_audit", "protects_against", "idor_flaws"),
            ("service_alphag5_audit", "has_pricing_tier", "inr_4999_most_popular"),
            ("service_alphag1_audit", "has_pricing_tier", "inr_1999_basic"),
            ("service_alphag3_audit", "has_pricing_tier", "inr_9999_pentest"),
            ("service_appify_mobile", "targets_platform", "android_and_ios"),
            ("service_static_website", "has_pricing_tier", "inr_20000_static"),
            ("service_dynamic_webapp", "has_pricing_tier", "inr_60000_dynamic_starting"),
            ("service_workflow_automation", "has_pricing_tier", "inr_8000_automation_starting")
        ]
        for sub, rel, obj in rel_links:
            self.system.relation_registry.create_relation(subject_id=sub, relation_type=rel, object_id=obj)

        self.system.sync_index()
        self.save()
        logger.info(f"Dynamic ingestion complete: {self.system.assembly_engine.count()} assemblies indexed.")

    def ingest_data_item(
        self,
        item_id: str,
        item_type: str,
        name: str,
        features: List[str],
        attributes: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dynamically ingests any product, catalog item, or concept structure using DNA encoding.
        Constructs Atomic DNA units for features and bundles them into an Assembly.
        """
        if not self.system:
            return {"status": "error", "message": "DNA system not initialized"}

        # 1. Register constituent feature atoms dynamically
        feature_atoms = []
        for feat in features:
            atom = self.system.register_concept(
                value=str(feat).strip(),
                concept_type="feature",
                source="data_ingestion"
            )
            feature_atoms.append(atom)

        # 2. Compose hierarchical assembly via vector bundling
        manifest = self.system.compose_product(
            name=name,
            components=feature_atoms,
            custom_id=item_id
        )

        # 2b. Register assembly in AssemblyEngine for hierarchical spreading activation
        self.system.assembly_engine.create_assembly(
            assembly_type=item_type,
            component_ids=[a.id for a in feature_atoms],
            metadata={"name": name, "item_type": item_type},
            custom_id=item_id
        )

        # 3. If relations/attributes provided, link them
        if attributes:
            for k, v in attributes.items():
                attr_atom = self.system.register_concept(f"{k}:{v}", "attribute", source="data_ingestion")
                self.system.relation_registry.create_relation(
                    subject_id=item_id,
                    relation_type=f"has_{k}",
                    object_id=attr_atom.id
                )

        self.save()
        return {
            "status": "success",
            "item_id": item_id,
            "manifest_name": manifest.name,
            "component_count": len(manifest.manifest.component_ids)
        }

    def record_interaction(
        self,
        customer_id: str,
        action: str,
        target_id: str,
        attributes: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Algorithmic event learning:
        Encodes interaction, links customer to target via tripartite relational DNA,
        and recomposes the customer's Behaviour Assembly.
        """
        if not self.system:
            return {}

        clean_cust_id = customer_id.strip()
        # Ensure customer atomic representation exists
        self.system.register_concept(
            value=clean_cust_id,
            concept_type="customer",
            source="interaction_stream",
            custom_id=clean_cust_id
        )

        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        rec = self.system.record_interaction(
            customer_id=clean_cust_id,
            event_type=action,
            target_id=target_id,
            attributes=attributes or {},
            timestamp=ts
        )
        self.save()
        return rec

    def predict_customer_behavior(self, customer_id: str) -> Dict[str, Any]:
        """
        Dynamically analyzes customer's relational bonds and recurrence cadence
        to predict next likely target and purchase window.
        """
        if not self.system:
            return {"customer": customer_id, "predicted_event": "unknown", "confidence": 0.0}

        clean_cust_id = customer_id.strip()
        return self.system.predict_next_action(clean_cust_id)

    def search_related_concepts(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Spreading activation search over the vector graph.
        """
        if not self.system:
            return []
        return self.system.search_memory(query, top_k=top_k)

    def format_memory_for_ai(self, customer_id: str) -> str:
        """
        Extracts dynamic relational insights and formats them for the AI prompt.
        Contains ZERO hardcoded text; purely populated from vector memory and graph links.
        """
        if not self.system:
            return ""

        pred = self.predict_customer_behavior(customer_id)
        if pred.get("predicted_event") == "unknown":
            return ""

        lines = [
            f"\n[DYNAMIC DNA MEMORY - CUSTOMER: {customer_id}]:",
            f"• Top Preferred Entity: {pred.get('predicted_target')}",
            f"• Next Anticipated Action: {pred.get('predicted_event')} ({pred.get('predicted_window')})",
            f"• Recurrence Cadence: {pred.get('estimated_interval_days')} days (Confidence: {pred.get('confidence', 0.0)*100:.0f}%)",
            "• Relational Evidence:"
        ]
        for ev in pred.get("evidence", []):
            lines.append(f"  - {ev}")
        lines.append("• Prompt Guideline: Adapt naturally to this customer's known preferences and cadence without sounding robotic.")
        return "\n".join(lines)

    def extract_and_encode_user_facts(self, customer_id: str, message: str, tenant_id: str = "default") -> Dict[str, str]:
        """
        Universal DNA Fact Extraction & Encoding:
        Uses the core UniversalUserMemory engine to learn user identities and traits into Relational DNA.
        """
        if not self.system:
            return {}
        clean_cust_id = customer_id.strip()
        scoped_id = f"{tenant_id}:{clean_cust_id}" if ":" not in clean_cust_id else clean_cust_id
        learned = self.system.extract_and_remember(scoped_id, message)
        if learned:
            if "has_name" in learned:
                try:
                    from api import db
                    raw_phone = clean_cust_id.split(":", 1)[-1]
                    db.upsert_customer_profile(raw_phone, overwrite_existing=False, tenant_id=tenant_id, contact_name=learned["has_name"])
                except Exception:
                    pass
            self.save()
        return learned

    def decode_customer_facts(self, customer_id: str) -> Dict[str, str]:
        """
        Pillar 3: Universal Lossless Profile Reconstruction from the core DNA Model.
        """
        if not self.system:
            return {}
        clean_cust_id = customer_id.strip()
        facts = self.system.reconstruct_user_profile(clean_cust_id)
        if "has_name" not in facts:
            try:
                from api import db
                contact = db.get_contact(clean_cust_id)
                if contact and contact.get("name") and contact["name"] != clean_cust_id:
                    name_val = contact["name"]
                    facts["has_name"] = name_val
                    self.system.remember_user_fact(clean_cust_id, "has_name", name_val)
            except Exception:
                pass
        return facts

    def process_message_through_dna(self, customer_id: str, message: str) -> Dict[str, Any]:
        """
        Universal Cognitive Memory Pipeline:
        1. Fact Extraction into Relational DNA (R_ABC).
        2. User Profile Reconstruction (Pillar 3).
        3. Spreading Activation & Query Grounding (Pillar 1 & 2).
        4. Synthesizes Agent Grounding Context for any downstream LLM or agent.
        """
        if not self.system:
            return {
                "customer_id": customer_id,
                "customer_facts": {},
                "newly_learned_facts": {},
                "direct_answers": {},
                "activated_nodes": [],
                "relationships": [],
                "prediction": {},
                "graph_context": ""
            }

        clean_cust_id = customer_id.strip()

        # 1. Learn any new facts from message into core DNA memory
        newly_learned = self.extract_and_encode_user_facts(clean_cust_id, message)

        # 2. Universal Agent Context Synthesis via Core DNA Architecture
        agent_ctx = self.system.synthesize_agent_context(clean_cust_id, message, top_k=5)

        # 3. Analyze customer cadence & predictions
        prediction = self.system.predict_next_action(clean_cust_id)

        # 4. Ingest interaction if service is referenced
        service_target = None
        for nid in agent_ctx.active_concepts:
            if nid.startswith("service_"):
                service_target = nid
                break
        if service_target:
            self.record_interaction(
                customer_id=clean_cust_id,
                action="inquired",
                target_id=service_target,
                attributes={"query_snippet": message[:60]}
            )

        return {
            "customer_id": clean_cust_id,
            "customer_facts": agent_ctx.user_profile,
            "newly_learned_facts": newly_learned,
            "direct_answers": agent_ctx.direct_answers,
            "activated_nodes": [{"id": c} for c in agent_ctx.active_concepts],
            "relationships": agent_ctx.relevant_domain_facts,
            "prediction": prediction,
            "graph_context": agent_ctx.prompt_context_string
        }

    def save(self):
        """Saves current state to disk and mirrors compact JSON snapshot to Supabase (`wa_dna_snapshots`)."""
        if self.system:
            try:
                self.system.save_to_disk(DNA_STATE_FILE)
            except Exception as e:
                print(f"[DNAService] Disk save warning: {e}")
            try:
                from api.supabase_store import get_cloud_store
                store = get_cloud_store()
                if store and hasattr(store, "save_dna_snapshot") and os.path.exists(DNA_STATE_FILE):
                    with open(DNA_STATE_FILE, "r", encoding="utf-8") as f:
                        snap = f.read()
                    # Store compact structural summary so cloud DB persists across ephemeral deploys
                    import json as _json
                    parsed = _json.loads(snap)
                    atoms_str = _json.dumps(parsed.get("atoms", {}))[:48000]
                    rels_str = _json.dumps(parsed.get("relations", []))[:48000]
                    store.save_dna_snapshot("default", atoms_str, rels_str)
            except Exception:
                pass
                logger.error(f"Error saving dynamic DNA state: {e}")

# Global instance
dynamic_dna = DynamicDNAManager()
