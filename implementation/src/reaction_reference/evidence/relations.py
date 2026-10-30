"""仅在已返回记录之间寻找完整材料身份链接，保留实验支持状态，不主动推演合成路线。"""

from collections import defaultdict

from reaction_reference.chemistry.structures import canonical, digest
from reaction_reference.domain.models import Material, ReactionRecord
from reaction_reference.evidence.claims import evidence_for


def material_relations(references, max_relations=100):
    """连接不同来源记录中同身份的产品与反应物，返回（关系列表、范围内枚举是否完成）。

    输入为已评估参考，按记录去重后用保留同位素/立体的规范身份关联；有真实制备和使用证据才赋予相应支持。max_relations 截断时返回不完整；身份相同不证明条件兼容或路线可直接拼接。
    """
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
    result: list[dict] = []
    for key in sorted(products.keys() & inputs.keys()):
        for producer, product in products[key]:
            for consumer, material in inputs[key]:
                if producer.id == consumer.id:
                    continue
                # 只有确实发现下一条未能保留的关联，才证明上限造成了遗漏。
                if len(result) >= max_relations:
                    return result, False
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
    return result, True
