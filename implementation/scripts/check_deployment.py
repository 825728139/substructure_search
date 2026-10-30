"""检查运行中的合成示例部署：真实 HTTP 检索、分页、SVG、资料包及冻结重排。"""

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(base, path, token, payload=None):
    """发送有超时的 HTTP 请求并返回原始响应体；令牌只放在请求头中。"""
    headers = {"Authorization": "Bearer " + token} if token else {}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def check(base, token, expected_hash=None):
    """验证包内示例服务的完整请求链，返回有限验收结果；不会改动来源反应数据。"""
    assert json.loads(fetch(base, "/health/live", token))["status"] == "alive"
    if token:
        try:
            fetch(base, "/health/ready", "")
        except urllib.error.HTTPError as exc:
            try:
                assert exc.code == 401
            finally:
                exc.close()
        else:
            raise AssertionError("配置令牌的部署不应允许匿名读取就绪信息")
    assert json.loads(fetch(base, "/health/ready", token))["status"] == "ready"
    assert "目标分子" in fetch(base, "/", token).decode("utf-8")
    submitted = json.loads(
        fetch(
            base,
            "/v1/search-runs",
            token,
            {
                "target": {"value": "CCCNC(=O)c1ccccc1"},
                "budget": {"max_tasks": 100},
            },
        )
    )
    run_id = submitted["run_id"]
    prefix = "/v1/search-runs/" + run_id
    deadline = time.monotonic() + 30
    while True:
        state = json.loads(fetch(base, prefix, token))
        if state["lifecycle"] in ("succeeded", "failed", "timed_out", "cancelled"):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("部署检索在验收期限内未结束")
        time.sleep(0.1)
    assert state["lifecycle"] == "succeeded", state.get("error")
    package = json.loads(fetch(base, prefix + "/package", token))
    assert package["results"] and package["proposals"]
    assert all(reference["record"]["source"]["synthetic"] for reference in package["results"]), (
        "本检查要求包内合成示例来源"
    )
    assert package["statistics"]["preparation_hits"] == 0
    if expected_hash is not None:
        assert package["manifest"]["implementation_hash"] == expected_hash
    first = json.loads(fetch(base, prefix + "/results?limit=1", token))
    assert first["next_cursor"]
    query = urllib.parse.urlencode({"limit": 1, "cursor": first["next_cursor"]})
    second = json.loads(fetch(base, prefix + "/results?" + query, token))
    assert first["snapshot_id"] == second["snapshot_id"] == package["snapshot_id"]
    assert first["results"][0]["item"]["id"] != second["results"][0]["item"]["id"]
    reference_id = first["results"][0]["item"]["id"]
    svg = fetch(base, prefix + f"/structures/{reference_id}.svg", token)
    assert b"<svg" in svg and b"</svg>" in svg
    derived = json.loads(
        fetch(
            base,
            prefix + "/rerank",
            token,
            {
                "ranking_profile": "lab_fit",
                "lab_context": {"max_temperature_c": 25.5},
            },
        )
    )
    assert derived["lifecycle"] == "succeeded" and derived["parent_run_id"] == run_id
    reranked = json.loads(fetch(base, "/v1/search-runs/" + derived["run_id"] + "/package", token))
    assert reranked["source_snapshot"] == package["source_snapshot"]
    assert {reference["id"] for reference in reranked["results"]} == {
        reference["id"] for reference in package["results"]
    }
    assert reranked["manifest"]["reranked_from_snapshot"] == package["snapshot_id"]
    return {
        "passed": True,
        "authenticated_readiness": bool(token),
        "implementation_hash": package["manifest"]["implementation_hash"],
        "references": len(package["results"]),
        "proposals": len(package["proposals"]),
        "structure_svg": True,
        "snapshot_pagination": True,
        "frozen_rerank": True,
        "scope": "packaged_synthetic_fixture_over_real_http",
    }


def main():
    """读取地址和可选预期代码哈希，运行验收并输出 JSON；访问令牌从环境读取。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-hash")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = check(args.base_url, os.environ.get("RR_API_TOKEN", ""), args.expected_hash)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
