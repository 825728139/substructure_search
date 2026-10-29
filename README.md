# 基于子结构搜索的反应先例检索

用户输入完整目标分子，系统在模型预测之前，检索能够参考的分子、底物及反应方法。默认使用三层 Markush 家族查询，再分析实际连接贡献、真实环变化、来源约束的单反应物替换类比，最终提供可追溯的参考资料包。

系统用于内部研究，按内部服务规划，不包含收费、订阅、套餐或账务功能。

可运行项目位于 [implementation](implementation/README.md)，包含检索引擎、反应贡献分析、来源约束替换、排序、CLI、SDK、API 和内部查看页面。启动：`./implementation/scripts/rr serve`。已实现范围与尚未验证的能力见 [实现状态](implementation/docs/STATUS.md)。

- [产品与化学计划](plan.md)
- [项目实现计划、模块与目录结构](implementation_plan.md)
- [实现项目、启动与接口说明](implementation/README.md)
- [中文代码交接指南、项目结构与阅读路线](implementation/docs/HANDOVER.md)
- [项目运行架构图](implementation/docs/system-architecture.svg)
- [核心业务逻辑图](implementation/docs/core-business-flow.svg)
- [整体代码审查与修复记录](implementation/docs/CODE_REVIEW.md)
- [三轮代码复审记录](implementation/docs/MULTI_ROUND_REVIEW.md)
- [执行层代码审查：并发、超时、取消与持久化](implementation/docs/RUNTIME_REVIEW.md)
- [数据边界审查：来源身份、快照归属与原子导出](implementation/docs/DATA_BOUNDARY_REVIEW.md)
- [结果过滤与排序](ranking_plan.md)
- [开发环境安装和验证](ENVIRONMENT.md)
- [详细化学规范](design/specification.md)
- [来源字段与接入约定](design/source_reference.md)
- [化学检查与验收案例](reviews/README.md)

理解需求先看产品计划和实现计划；接手代码先看中文交接指南，再按函数索引定位实现。当前决定直接维护在对应文档中，修订过程通过 Git 查看。

![检索流程](diagrams/scaffold-search.png)
