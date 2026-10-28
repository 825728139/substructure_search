"""Identity links in returned real records, never an invented synthesis route."""

from collections import defaultdict

from reaction_reference.chemistry.structures import canonical, digest
from reaction_reference.domain.models import Material, ReactionRecord
from reaction_reference.evidence.claims import evidence_for


def material_relations(references, max_relations=100):
    records = {ref.record.id: ref.record for ref in references}
    products: dict[str, list[tuple[ReactionRecord, Material]]] = defaultdict(list)
    inputs: dict[str, list[tuple[ReactionRecord, Material]]] = defaultdict(list)
    for record in records.values():
        for material in record.materials:
            if material.role not in ("product", "reactant"):
                continue
            try:
                key = canonical(material.smiles)
            except ValueError:
                continue
            (products if material.role == "product" else inputs)[key].append((record, material))
    result = []
    for key in sorted(products.keys() & inputs.keys()):
        for producer, product in products[key]:
            for consumer, material in inputs[key]:
                if producer.id == consumer.id:
                    continue
                qualified = (
                    evidence_for(producer, product)[0] and evidence_for(consumer, material)[2]
                )
                result.append(
                    {
                        "id": digest(
                            [producer.id, product.instance_id, consumer.id, material.instance_id]
                        ),
                        "material_smiles": key,
                        "producer_record": producer.id,
                        "producer_material": product.instance_id,
                        "consumer_record": consumer.id,
                        "consumer_material": material.instance_id,
                        "support": "reported_preparation_and_use"
                        if qualified
                        else "graph_identity_clue",
                        "source_refs": [producer.source.model_dump(), consumer.source.model_dump()],
                        "limitations": [
                            "identity_link_not_a_validated_combined_route",
                            "conditions_and_intermediate_form_compatibility_unverified",
                        ],
                    }
                )
                if len(result) >= max_relations:
                    return result, False
    return result, True
