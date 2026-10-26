# 定向修订：Markush 优先，关键功能限制与宽 R 联合召回

日期：2026-10-26。用户要求：不只检索连续精确片段，应尽量用 Markush 覆盖多位点支链；重要官能团限制保留，对非关键外围不过度限制。

## 采用的设计

- [主计划](../plan.md)将三层默认形式改为 Markush 家族，完整目标身份为并行补充。
- [专项规范](../design/markush_queries.md)定义固定要素、可变 R、全支链类别、可选 H、额外取代、分离锚点、联合约束、桥接结构和真实共存组合。
- 活性影响不明的外围属性原则上进入后续反应环境比较，不一律锁死；未限制不等于宣称对反应无影响。
- [详细规则](../design/specification.md)第 4.12、5.1、6.1、9.3 节及统计、验收同步；具体通式来源与内部查询通式分开。
- 排序、证据契约和预算配置同步。默认不对 R 设统一化学尺寸上限；资源上限导致未评估/截断，不静默当成不匹配。
- [Markush 图](../diagrams/markush-query.svg)新增，总览与核心支链图更新。

本次维持已有反应驱动的开/闭环分析，不重新引入无来源目标环前体枚举。

## 技术依据与验证

[RDKit Book](https://www.rdkit.org/docs/RDKit_Book.html#generic-markush-queries-in-substructure-matching)说明通用基团查询及显式启用参数；[Python 文档](https://www.rdkit.org/docs/GettingStartedInPython.html#advanced-substructure-matching)给出完整支链后检查示例。它们支持部分查询机制，不意味着任意专利 Markush 语义均可直接执行。

[探针](check_markush_queries.py)与[结果](markush_query_checks.json)使用 RDKit 2026.03.2：3 个通用基团案例、11 个多位点家族案例、2 个显式选项检查通过，共 16 个局部检查。

新增 12 项主设计验收至 99 项。11 张流程图渲染，文档链接、章节引用、配置和差异空白检查通过。没有实现完整家族生成/编译、所有支链空间搜索或真实反应排序；不报告召回率或实验有效性。
