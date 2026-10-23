# 第 1 轮：查询编译语义

发现：主设计保留电荷/H 的原则没有明确落到查询谓词；普通 SMILES 分子作为子结构查询可能过宽。完整身份与单向包含也必须分开。

调研：[RDKit Book 的原子匹配语义](https://www.rdkit.org/docs/RDKit_Book.html#atom-atom-matching-in-substructure-queries)。本地 RDKit 2026.03.2 中，普通 `CCO` 分子查询能命中乙醇、醇盐和醚；显式 OH 谓词分别返回真、假、假。

修订：详细规则第 9.3 节定义完整身份、核心包含、官能团、环系和扩展的编译契约，并要求保留属性清单及完整结构立体复核。

验证：[结构探针](probes/01_query_semantics.py)及[结果](probes/01_query_semantics.json)，3 项通过；文档完整性检查通过。探针不是检索引擎或完整查询编译器。

剩余：实际预筛实现仍需与同语义全扫描对照；本轮不能证明所有 SMARTS 的正确性。
