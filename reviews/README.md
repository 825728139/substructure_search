# 化学检查与验收案例

本目录保存可复现的结构检查、人工验收要求和当前来源样本摘要。它们支持后续实现，不是检索引擎的完整测试套件。研究过程和旧结论通过 Git 历史查看。

## 局部化学检查

| 检查 | 运行脚本 | 对应输出 |
|---|---|---|
| 骨架、互变、立体和覆盖边界 | [脚本](check_chemical_edge_cases.py) | [结果](chemical_edge_cases.json) |
| 反应环境、原子来源与同位素 | [脚本](check_reaction_relevance.py) | [结果](reaction_relevance_checks.json) |
| 映射歧义、来源份数和手性 | [脚本](check_mapping_and_stereo.py) | [结果](mapping_and_stereo_checks.json) |
| 目标母核—支链连接贡献 | [脚本](check_attachment_methods.py) | [结果](attachment_method_checks.json) |
| 单反应物替换的图回放 | [脚本](check_single_reactant_transfer.py) | [结果](single_reactant_transfer_checks.json) |
| 无环、开闭环与图连通性 | [脚本](check_acyclic_and_ring_changes.py) | [结果](acyclic_and_ring_change_checks.json) |
| Markush 联合位点、完整支链、对称映射与截断 | [脚本](check_markush_queries.py) | [结果](markush_query_checks.json) |
| 官能团谓词、相似度与子结构预筛反例 | [脚本](check_query_semantics.py) | [结果](query_semantics_checks.json) |
| 组分边界和通配结构 | [脚本](check_component_scope.py) | [结果](component_scope_checks.json) |

在项目根目录执行：

```bash
./scripts/project-uv run --locked python scripts/verify_environment.py
```

此命令在临时目录运行上述 9 个探针，检查依赖协作、生成 11 张设计图并验证文档完整性。探针的人工结构例子不进入真实先例计数，图匹配或回放通过不表示实验成功。

## 待实现的验收要求

- [详细规范第 13.1 节](../design/specification.md#131-化学验收案例)：105 项化学验收要求。
- [证据契约场景](evidence_contract_cases.json)：10 个结果状态与计数案例。
- [排序契约场景](ranking_contract_cases.json)：25 个资格、约束与未知信息案例。

上述清单需由业务实现逐项执行；JSON 格式正确不代表对应行为已经通过测试。

## 来源样本检查

[来源接入约定](../design/source_reference.md)定义当前字段语义。[审查脚本](audit_reaction_snapshot.py)读取本地 JSONL，检查映射、材料与模板的表示一致性，不连接数据库。

```bash
.venv/bin/python reviews/audit_reaction_snapshot.py \
  .cache/reaction-review/2026-10-28/sample.jsonl \
  --output .cache/reaction-review/2026-10-28/audit.json
```

[来源样本摘要](reaction_source_audit.json)记录采样时间、范围和输入哈希。原始样本位于本地忽略目录，需要另行获得有权访问的导出；克隆仓库不会获得这些数据。该审查不属于上述九个离线探针，不用于推算全库质量比例。
