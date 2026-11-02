"""有歧义的反应中心投影：保留候选对应，区分精确位置与区域一致的方法支持。"""

from reaction_reference.chemistry.regions import structural_regions


def region_consensus(conclusions, target, *, enumeration_complete):
    """仅在全部对应枚举完成且每种成键解释均落在同一具体母核/头部区域时确认区域。

    不合并候选成键，不把部分对应或跨不同母核的解释冒充共识；完全无成键也不推断。
    """
    if not enumeration_complete:
        return {
            "state": "unresolved",
            "reason": "mapping_enumeration_incomplete_or_multiple_products",
        }
    if not conclusions or any(not formed for formed, _ in conclusions):
        return {"state": "unresolved", "reason": "not_all_alternatives_support_target_formation"}
    regions = structural_regions(target)
    for kind, candidates in (
        ("core_internal", regions["core_regions"]),
        ("core_branch_head", regions["head_regions"]),
    ):
        for region in candidates:
            if all(all(set(pair) <= region for pair in formed) for formed, _ in conclusions):
                return {
                    "state": "confirmed",
                    "kind": kind,
                    "target_region_atoms": sorted(region),
                    "mapping_enumeration_complete": True,
                    "support": "all_product_correspondences_agree_on_one_region",
                }
    return {"state": "unresolved", "reason": "alternatives_do_not_share_one_core_or_head_region"}


def has_region_method(projection):
    """判断投影是否具备完整枚举的区域级成键共识，供贡献分类、过滤和评分统一使用。"""
    region = projection.get("region_consensus", {})
    return (
        projection.get("support") == "ambiguous_product_mapping"
        and region.get("state") == "confirmed"
        and region.get("mapping_enumeration_complete") is True
        and region.get("kind") in ("core_internal", "core_branch_head")
        and bool(projection.get("projection_alternatives"))
    )


def projection_strength(projection):
    """比较同材料不同见证的方法支持强度：精确成键、区域成键、原子变化、普通线索。"""
    if projection.get("formed_target_bonds"):
        return 3
    if has_region_method(projection):
        return 2
    return 1 if projection.get("changed_target_atoms") else 0
