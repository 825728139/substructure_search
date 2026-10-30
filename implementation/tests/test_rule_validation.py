"""规则配置回归：校验入口不能接受会使单目标回放失败或混淆建议身份的配置。"""

import json

import pytest

from reaction_reference import rules
from reaction_reference.interfaces.cli import main


def install_rules(tmp_path, monkeypatch, transfers):
    """把受控回放规则写入临时资源根目录，保留其他已验证的规则配置。"""
    configuration, _ = rules.load_rules()
    configuration["transfer_rules"] = transfers
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "rules.json").write_text(json.dumps(configuration), encoding="utf-8")
    monkeypatch.setattr(rules, "files", lambda _: tmp_path)


def test_duplicate_transfer_ids_are_rejected(tmp_path, monkeypatch):
    """重复回放规则 ID 会混淆建议去重与来源追溯，必须在加载时拒绝。"""
    rule = rules.load_rules()[0]["transfer_rules"][0]
    install_rules(tmp_path, monkeypatch, [rule, dict(rule)])
    with pytest.raises(ValueError, match="duplicate.*transfer|transfer.*duplicate"):
        rules.load_rules()


@pytest.mark.parametrize(
    "forward,retro",
    [
        ("[C:1][Br].[O:2]>>[C:1][O:2]", "[C:1][O:2].[Br:3]>>[C:1][Br:3].[O:2]"),
        ("[C:1].[O:2]>>[C:1][O:2]", "[C:1][O:2]>>[C:1][O:2]"),
        (
            "[C:1].[C:2].[C:3].[C:4].[C:5]>>[C:1][C:2][C:3][C:4][C:5]",
            "[C:1][C:2][C:3][C:4][C:5]>>[C:1].[C:2].[C:3].[C:4].[C:5]",
        ),
    ],
)
def test_transfer_arity_matches_single_target_runtime(tmp_path, monkeypatch, forward, retro):
    """语法可编译但目标/输入数量不符合实际调用方式的规则不能被报告为有效。"""
    install_rules(
        tmp_path,
        monkeypatch,
        [{"id": "arity", "forward": forward, "retro": retro, "scope": "测试"}],
    )
    with pytest.raises(ValueError, match="arity|single.target|reactant"):
        rules.load_rules()


def test_multiple_forward_products_remain_supported(tmp_path, monkeypatch):
    """单目标逆向回放并不要求正向只生成一个产物，合法副产物不能被错误禁止。"""
    rule = {
        "id": "with-coproduct",
        "forward": "[C:1][Br:2]>>[C:1].[Br:2]",
        "retro": "[C:1]>>[C:1]Br",
        "scope": "测试",
    }
    install_rules(tmp_path, monkeypatch, [rule])
    loaded, _ = rules.load_rules()
    assert loaded["transfer_rules"] == [rule]


def test_rule_validation_command_rejects_unsupported_replay(tmp_path, monkeypatch, capsys):
    """命令行校验不能对运行时不支持的多目标逆向规则打印有效结果。"""
    install_rules(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "two-targets",
                "forward": "[C:1].[O:2]>>[C:1][O:2]",
                "retro": "[C:1].[O:2]>>[C:1].[O:2]",
                "scope": "测试",
            }
        ],
    )
    assert main(["validate-rules"]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)["code"] == "request_failed"
