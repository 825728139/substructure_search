"""人工验证Demo：正式规划结构图、来源反应绘图和访问控制。"""

from fastapi.testclient import TestClient

from reaction_reference.chemistry.structures import parse
from reaction_reference.interfaces.api import create_app
from reaction_reference.interfaces.depiction import query_images, reaction_svg
from reaction_reference.retrieval.planner import initial_families


def test_demo_preview_uses_formal_planner_and_rdkit(settings):
    """预览绘制全部正式家族及源端预筛，不访问反应数据库。"""
    with TestClient(create_app(settings)) as client:
        assert client.get("/demo").status_code == 200
        response = client.post("/v1/demo/preview", json={"target": {"value": "CCNC(=O)c1ccccc1"}})
        assert response.status_code == 200
        data = response.json()
        assert "<svg" in data["target_svg"]
        assert len(data["queries"]) == len(initial_families(parse("CCNC(=O)c1ccccc1")))
        assert all(
            "<svg" in q["query_svg"] and "<svg" in q["prefilter_svg"] for q in data["queries"]
        )


def test_demo_endpoints_require_configured_token(settings):
    """Demo图像数据与检索数据遵循同一内部认证。"""
    settings.api_token = "demo-test"
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/demo/preview", json={"target": {"value": "CCO"}}).status_code == 401
        assert client.get("/v1/search-runs/unknown/demo").status_code == 401


def test_reaction_depiction_uses_actual_materials(amide):
    """反应图从真实材料角色生成，不需映射或拟合成目标。"""
    from types import SimpleNamespace

    svg = reaction_svg(SimpleNamespace(record=amide))
    assert "<svg" in svg and "</svg>" in svg
    images = query_images("CCO", initial_families(parse("CCO")))
    assert images["queries"]
