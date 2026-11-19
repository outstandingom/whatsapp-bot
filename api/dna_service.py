"""
Dynamic DNA Memory Service for WhatsApp Bot
Zero hardcoded domain data: Learns entities, concepts, attributes, and relationships
dynamically through the DNA Encoding Algorithm and holographic vector composition.
"""

import os
import sys
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

    def save(self):
        """Saves current state to disk."""
        if self.system:
            try:
                self.system.save_to_disk(DNA_STATE_FILE)
            except Exception as e:
                logger.error(f"Error saving dynamic DNA state: {e}")

# Global instance
dynamic_dna = DynamicDNAManager()
