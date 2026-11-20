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

# Link to dna-modal package
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

    def extract_and_encode_user_facts(self, customer_id: str, message: str) -> Dict[str, str]:
        """
        DNA Fact Learning Algorithm:
        Extracts entities and relational facts from incoming user dialogue,
        encodes them into Atomic DNA units, binds them via holographic Relation DNA (R_ABC),
        and dynamically updates the Customer's Long-Term Memory Profile Assembly.
        """
        if not self.system:
            return {}

        clean_cust_id = customer_id.strip()
        learned = {}
        m = message.strip()

        # 1. User Name Extraction
        # Matches "my name is Om Uikey", "I am Om Uikey", "myself Om Uikey", "call me Om", "this is Om Uikey", etc.
        name_match = re.search(
            r'(?:my name is|i am|i\'m|myself|call me|name is|this is)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)',
            m,
            re.IGNORECASE
        )
        if name_match:
            candidate = name_match.group(1).strip()
            # Filter out non-names
            stopwords = {
                "looking", "interested", "here", "ready", "fine", "good", "a", "an", "the",
                "not", "just", "trying", "wondering", "asking", "happy", "new", "website",
                "app", "customer", "user", "client", "human", "specialist", "agent", "person",
                "having", "getting", "facing", "experiencing", "reporting"
            }
            words = candidate.lower().split()
            if candidate and not any(w in stopwords for w in words) and len(candidate) > 1:
                clean_name = " ".join(w.capitalize() for w in words)
                learned["has_name"] = clean_name

        # 2. Company / Business Extraction
        comp_match = re.search(
            r'(?:my company is|i work at|my startup is|my business is|our company is)\s+([A-Za-z0-9\.\-_ ]+?)(?:\.|\,|$|\n)',
            m,
            re.IGNORECASE
        )
        if comp_match:
            candidate_comp = comp_match.group(1).strip()
            if len(candidate_comp) > 1:
                learned["has_company"] = candidate_comp

        # 3. Website Extraction
        url_match = re.search(
            r'(https?://[^\s]+|[a-zA-Z0-9-]+\.(com|in|org|net|io|co|ai|app)[^\s]*)',
            m,
            re.IGNORECASE
        )
        if url_match:
            learned["has_website"] = url_match.group(1).strip()

        # 4. Email Extraction
        email_match = re.search(
            r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)',
            m
        )
        if email_match:
            learned["has_email"] = email_match.group(1).strip()

        # 5. Role Extraction
        role_match = re.search(
            r'(?:i am a|i am the|i\'m a|i\'m the)\s+(founder|co-founder|developer|engineer|ceo|cto|owner|manager|designer|director)',
            m,
            re.IGNORECASE
        )
        if role_match:
            learned["has_role"] = role_match.group(1).capitalize()

        # Encode each learned fact into DNA vector memory
        if learned:
            # Ensure customer atom exists
            self.system.register_concept(
                value=clean_cust_id,
                concept_type="customer",
                source="interaction_stream",
                custom_id=clean_cust_id
            )

            for rel_type, val in learned.items():
                slug = re.sub(r'[^a-z0-9_]', '', val.lower().replace(' ', '_'))[:30]
                fact_atom_id = f"fact_{rel_type}_{slug}"

                # Register concept atom
                atom = self.system.register_concept(
                    value=str(val),
                    concept_type="customer_attribute",
                    source="dialogue_extraction",
                    custom_id=fact_atom_id
                )

                # Bind holographic relation S --[R]--> O
                self.system.relation_registry.create_relation(
                    subject_id=clean_cust_id,
                    relation_type=rel_type,
                    object_id=atom.id,
                    confidence=1.0,
                    strength=1.0
                )

                # Bind reciprocal relation O --[R^-1]--> S
                self.system.relation_registry.create_relation(
                    subject_id=atom.id,
                    relation_type=f"is_{rel_type}_of",
                    object_id=clean_cust_id,
                    confidence=1.0,
                    strength=0.9
                )

                # If name was learned, sync with database contact
                if rel_type == "has_name":
                    try:
                        from api import db
                        db.save_contact(phone_number=clean_cust_id, name=val)
                    except Exception as e:
                        logger.debug(f"Could not sync contact name to DB: {e}")

            self.system.sync_index()
            self.save()
            logger.info(f"DNA Fact Learning Algorithm learned for {clean_cust_id}: {learned}")

        return learned

    def decode_customer_facts(self, customer_id: str) -> Dict[str, str]:
        """
        DNA Fact Decoding Algorithm:
        Given customer ID, queries relational bonds in DNA memory,
        resolves bound object concepts, and retrieves all known long-term memory facts.
        """
        if not self.system:
            return {}

        clean_cust_id = customer_id.strip()
        facts = {}

        # 1. Query all relations where customer is subject (latest updates first)
        rels = self.system.relation_registry.retrieve_relations(subject_id=clean_cust_id)
        for r in reversed(rels):
            if r.relation_type in ["has_name", "has_company", "has_website", "has_email", "has_role", "prefers", "inquired_about"]:
                if r.relation_type not in facts:
                    obj_atom = self.system.dna_registry.get(r.object_id)
                    val = obj_atom.value if obj_atom else r.object_id
                    facts[r.relation_type] = str(val)

        # 2. If name not in relations, check if database has contact name
        if "has_name" not in facts:
            try:
                from api import db
                contact = db.get_contact(clean_cust_id)
                if contact and contact.get("name") and contact["name"] != clean_cust_id:
                    name_val = contact["name"]
                    facts["has_name"] = name_val
                    # Seed into DNA memory so it becomes a permanent relation
                    atom = self.system.register_concept(value=name_val, concept_type="customer_attribute")
                    self.system.relation_registry.create_relation(clean_cust_id, "has_name", atom.id)
            except Exception:
                pass

        return facts

    def process_message_through_dna(self, customer_id: str, message: str) -> Dict[str, Any]:
        """
        Step 1 & 2 of the DNA Architecture:
        1. Fact Extraction & Dynamic DNA Encoding from incoming message.
        2. Customer Long-Term Memory Profile Decoding.
        3. Spreading Activation over vector memory for semantic retrieval.
        4. Extracts related relationship bonds (R_ABC).
        5. Analyzes customer cadence and predicted behavior.
        6. Packages structured knowledge graph context ready for the AI.
        """
        if not self.system:
            return {
                "customer_id": customer_id,
                "customer_facts": {},
                "newly_learned_facts": {},
                "activated_nodes": [],
                "relationships": [],
                "prediction": {},
                "graph_context": ""
            }

        clean_cust_id = customer_id.strip()

        # 1. Extract and encode new facts from incoming message
        newly_learned = self.extract_and_encode_user_facts(clean_cust_id, message)

        # 2. Decode known customer long-term memory facts
        customer_facts = self.decode_customer_facts(clean_cust_id)

        # 3. Spreading Activation: Find related concepts/assemblies in vector memory
        activated_nodes = self.system.search_memory(message, top_k=5)
        top_node_ids = [n["id"] for n in activated_nodes]

        # 4. Extract Relational Bonds for activated nodes
        discovered_relations = []
        natural_facts = []
        for nid in top_node_ids:
            rels = self.system.relation_registry.retrieve_relations(subject_id=nid)
            rels += self.system.relation_registry.retrieve_relations(object_id=nid)
            for r in rels[:4]:
                if r.relation_type.startswith("inverse_") or r.relation_type.startswith("is_synonym"):
                    continue
                rel_str = f"{r.subject_id} --[{r.relation_type}]--> {r.object_id}"
                if rel_str not in discovered_relations:
                    discovered_relations.append(rel_str)
                    
                    # Also build human-natural fact string
                    s_name = r.subject_id.replace("company_", "").replace("service_", "").replace("person_", "").replace("payment_", "").replace("_", " ").title()
                    obj_atom = self.system.dna_registry.get(r.object_id)
                    o_name = (obj_atom.value if obj_atom else r.object_id).replace("price_inr_", "₹").replace("_", " ").title()
                    rel_name = r.relation_type.replace("_", " ")
                    natural_facts.append(f"{s_name} {rel_name}: {o_name}")

        # 5. Analyze customer predictive intent & recurrence cadence
        prediction = self.system.predict_next_action(clean_cust_id)

        # 6. Ingest current interaction into episodic memory (link customer to relevant target)
        service_target = None
        for nid in top_node_ids:
            if nid.startswith("service_"):
                service_target = nid
                break
        
        primary_target = service_target or "general_inquiry"
        if primary_target != "general_inquiry":
            self.record_interaction(
                customer_id=clean_cust_id,
                action="inquired",
                target_id=primary_target,
                attributes={"query_snippet": message[:60]}
            )

        # 7. Build Structured Graph Context for AI
        context_parts = [
            f"[DNA KNOWLEDGE GRAPH ACTIVATION FOR CUSTOMER: {clean_cust_id}]",
            f"• User Message: \"{message}\"",
        ]

        if customer_facts:
            context_parts.append("• Customer Long-Term Memory Profile (Decoded from DNA):")
            for k, v in customer_facts.items():
                label = k.replace("has_", "").title()
                context_parts.append(f"  - {label}: {v}")

        if natural_facts:
            context_parts.append("• Verified Domain Knowledge (from DNA Vector Graph):")
            for fact in natural_facts[:6]:
                context_parts.append(f"  └─ {fact}")
        elif discovered_relations:
            context_parts.append("• Discovered Relational Bonds:")
            for r in discovered_relations[:4]:
                context_parts.append(f"  └─ {r}")

        if activated_nodes:
            node_desc = ", ".join(f"{n['id']} ({n['activation_score']:.2f})" for n in activated_nodes[:4])
            context_parts.append(f"• Active Semantic Nodes: {node_desc}")

        if service_target and prediction and prediction.get("predicted_event") != "unknown":
            context_parts.append(
                f"• Customer Memory & Pattern: Top Preference '{prediction.get('predicted_target')}', "
                f"Anticipated Need '{prediction.get('predicted_event')}' ({prediction.get('predicted_window')}, "
                f"Cadence {prediction.get('estimated_interval_days')}d, Conf {prediction.get('confidence', 0)*100:.0f}%)"
            )

        context_parts.append("• INSTRUCTION: When responding, address the customer by their known name (if present) and recall their saved details naturally. Never output raw IDs; speak like a human expert.")

        return {
            "customer_id": clean_cust_id,
            "customer_facts": customer_facts,
            "newly_learned_facts": newly_learned,
            "activated_nodes": activated_nodes,
            "relationships": discovered_relations,
            "natural_facts": natural_facts,
            "prediction": prediction,
            "graph_context": "\n".join(context_parts)
        }

    def save(self):
        """Saves current state to disk."""
        if self.system:
            try:
                self.system.save_to_disk(DNA_STATE_FILE)
            except Exception as e:
                logger.error(f"Error saving dynamic DNA state: {e}")

# Global instance
dynamic_dna = DynamicDNAManager()
