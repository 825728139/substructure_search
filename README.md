# 基于子结构搜索的反应先例检索

用户输入完整目标分子，系统在模型预测之前，检索能够参考的分子、底物及反应方法。默认使用三层 Markush 家族查询，再分析实际连接贡献、真实环变化、来源约束的单反应物替换类比，最终提供可追溯的参考资料包。

当前已完成设计文档、局部化学探针和独立开发环境配置，尚未提供检索引擎或业务 API。

- [产品与化学计划](plan.md)
- [项目实现计划、模块与目录结构](implementation_plan.md)
- [结果过滤与排序](ranking_plan.md)
- [开发环境安装和验证](ENVIRONMENT.md)
- [详细化学规范](design/specification.md)
- [来源字段与接入约定](design/source_reference.md)
- [化学检查与验收案例](reviews/README.md)

阅读顺序：先看产品计划和实现计划，再按开发模块查阅详细规范。当前决定直接维护在对应文档中，修订过程通过 Git 查看。

![检索流程](diagrams/scaffold-search.png)
