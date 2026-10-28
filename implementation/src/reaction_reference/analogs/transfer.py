from itertools import permutations

from rdkit import Chem
from rdkit.Chem import rdChemReactions

from reaction_reference.chemistry.structures import canonical, digest, meets_target, parse
from reaction_reference.domain.models import Proposal
from reaction_reference.retrieval.planner import functional_matches
from reaction_reference.rules import load_rules


def source_rules(record):
    rules = list(load_rules()[0]["transfer_rules"])
    template = record.retro_template
    if template and len(template) <= 20000 and template.count(">") == 2:
        try:
            products, agents, inputs = template.split(">")
            reverse = rdChemReactions.ReactionFromSmarts(template)
            forward_text = inputs + ">>" + products
            forward = rdChemReactions.ReactionFromSmarts(forward_text)
            if (
                not agents
                and reverse.GetNumReactantTemplates() == 1
                and 1 <= forward.GetNumReactantTemplates() <= 4
                and sum(m.GetNumAtoms() for m in forward.GetReactants()) <= 128
                and not forward.Validate(silent=True)[1]
                and not reverse.Validate(silent=True)[1]
            ):
                rules.insert(
                    0,
                    {
                        "id": "source_radius2_retro:" + digest(template),
                        "forward": forward_text,
                        "retro": template,
                    },
                )
        except (ValueError, RuntimeError):
            pass
    return rules


def replay(reaction, inputs, max_sets=16):
    groups = reaction.RunReactants(tuple(inputs), maxProducts=max_sets + 1)
    output, invalid = [], 0
    for group in groups[:max_sets]:
        try:
            products = []
            for product in group:
                Chem.SanitizeMol(product)
                products.append(canonical(product))
            output.append(products)
        except (ValueError, RuntimeError):
            invalid += 1
    return output, len(groups) <= max_sets, invalid == 0


def generate_proposals(reference, target, budget):
    record = reference.record
    if record.event_scope != "documented_step" or not record.documented_step_ref:
        return [], "source_step_not_assigned"
    if reference.analysis.state == "unknown":
        return [], "source_mapping_not_validated"
    observed = any(
        o.product_instance_id == reference.material.instance_id
        and o.result == "reported_prepared"
        and o.evidence_text
        and o.evidence_text.strip()
        and o.source_location
        and o.source_location.strip()
        for o in record.observations
    )
    if not observed:
        return [], "source_preparation_evidence_missing"
    if any(
        o.product_instance_id == reference.material.instance_id
        and o.result in ("failed", "conflict", "recovered")
        for o in record.observations
    ):
        return [], "source_outcome_conflict"
    if any(m.actual_input is not True for m in record.materials if m.role == "reactant"):
        return [], "actual_reactant_use_not_verified"
    actual = [parse(m.smiles) for m in record.materials if m.role == "reactant"]
    if len(actual) > 4 or not actual:
        return [], "reactant_assignment_unsupported"
    proposals = []
    target_key = canonical(target)
    for rule in source_rules(record):
        budget.check()
        forward = rdChemReactions.ReactionFromSmarts(rule["forward"])
        reverse = rdChemReactions.ReactionFromSmarts(rule["retro"])
        if forward.GetNumReactantTemplates() != len(actual):
            continue
        for assignment in permutations(actual):
            if not all(
                m.HasSubstructMatch(q)
                for m, q in zip(assignment, forward.GetReactants(), strict=False)
            ):
                continue
            original_sets, original_complete, original_valid = replay(
                forward, assignment, budget.config.max_replay_sets
            )
            if not original_valid or not any(
                canonical(reference.material.smiles) in g for g in original_sets
            ):
                continue
            original_keys = [canonical(m) for m in assignment]
            budget.task("transfer_replay", reference.id)
            retro_sets, retro_complete, retro_valid = replay(
                reverse, [target], budget.config.max_replay_sets
            )
            for group in retro_sets:
                budget.check()
                if len(group) != len(original_keys):
                    continue
                changed = [
                    i
                    for i, (old, new) in enumerate(zip(original_keys, group, strict=False))
                    if old != new
                ]
                if len(changed) != 1:
                    continue
                candidates = [parse(s) for s in group]
                if any(a.GetAtomicNum() == 0 for m in candidates for a in m.GetAtoms()):
                    continue
                product_sets, complete, valid = replay(
                    forward, candidates, budget.config.max_replay_sets
                )
                found = any(any(meets_target(parse(s), target) for s in g) for g in product_sets)
                if not found:
                    continue
                limitations = [
                    "proposal_not_experimentally_observed",
                    "conditions_not_validated_for_new_inputs",
                    "proposed_starting_material_availability_unknown",
                    "graph_replay_does_not_predict_selectivity_or_major_product",
                ]
                old_groups = [name for name, _, _ in functional_matches(assignment[changed[0]])]
                new_groups = [name for name, _, _ in functional_matches(candidates[changed[0]])]
                if any(
                    new_groups.count(name) > old_groups.count(name)
                    for name in ("amine", "hydroxyl")
                ):
                    limitations.append("additional_competing_functional_sites_require_review")
                if record.source.synthetic:
                    limitations.append("synthetic_source_illustration_not_literature")
                proposals.append(
                    Proposal(
                        id=digest([reference.id, rule["id"], group, target_key]),
                        source_reference_id=reference.id,
                        source=record.source,
                        source_step_ref=record.documented_step_ref,
                        replaced_slot=changed[0],
                        original_reactants=original_keys,
                        proposed_reactants=group,
                        target_smiles=target_key,
                        replay_product_sets=product_sets,
                        enumeration_complete=complete and retro_complete and original_complete,
                        validation_complete=valid and retro_valid,
                        target_found=True,
                        rule_id=rule["id"],
                        limitations=limitations,
                    )
                )
                if len(proposals) >= 2:
                    return proposals, None
    return proposals, None
