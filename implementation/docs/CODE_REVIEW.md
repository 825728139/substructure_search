# 整体代码审查与修复记录

2026-10-29。本轮覆盖查询规划、Markush 核验、来源适配、真实反应贡献、替换回放、证据与排序、执行和文件快照、CLI、HTTP、内部页面及评测。确认并修复以下 15 类问题，均保留可重复的回归检查。

P1 表示会造成错误化学结论、证据资格错误、任务资料范围矛盾或失去关键资源约束；P2 表示导致特定输入失败、来源选择错误或操作结果混用。严重程度针对本项目的参考检索用途。

| 编号 | 级别 | 触发条件与原问题 | 修复及验证 |
|---|---|---|---|
| 01 | P1 | 同一核心连接多个相同支链时，总先尝试第一个来源块；`CC(C)O` 对自身的中心碳查询最高只得到 75% 联合覆盖 | 来源块只能使用一次，成功对应后才占用；无法扩展则继续寻找其他块。异丙醇和三甲胺自身覆盖均恢复为 100% |
| 02 | P1 | 定向查询要求两个相同甲基，但两个条件都可由一个甲基满足，乙醇错误满足异丙醇的完整 R 组合 | 必需精确块按位置与结构计数核验。桥连块在同一核心位置的多根连接边不重复计为多个实际块 |
| 03 | P1 | 核心外只有一个碳时，没有内部键需要检查，双键或三键连接的碳也被当作烷基 | 烷基类别同时要求核心连接键为单键；乙烯、乙炔反例不再命中烷基约束 |
| 04 | P1 | 同一产品同时有富集和失败/普通回收记录，仍被算作合格获得命中 | 富集和制备使用相同的冲突规则；冲突观察仍完整保留，不再给出阳性获得资格 |
| 05 | P1 | 审核文件的实际输入引用只有空白字符，仍可把未知投料升级为确认使用 | 引用先检查去空白后的内容，空白审核记为无效并保留原记录 |
| 06 | P1 | 材料列表中既有明确禁用物又有一个非法 SMILES，集合构造异常使禁用结论丢失 | 逐材料识别；已知禁用项仍返回 `fail`，脏材料另记未知原因 |
| 07 | P1 | 初始阶段包提前把未开始的能力标为完成；重启或监督异常又可能只更新失败状态，已保存资料仍显示完整范围 | 按执行阶段报告能力状态；共用 `interrupt_snapshot` 保存部分范围快照、停止原因及任务指针，原快照保持不可变 |
| 08 | P2 | 错误认证头含非 ASCII 字符，字符串形式的常量时间比较触发异常 | 按字节执行常量时间比较；非法令牌返回 401 |
| 09 | P2 | 上一任务的状态、结果、错误或下载晚返回，覆盖新任务页面；旧包甚至使用新任务编号命名 | 异步操作绑定任务与页面版本，旧响应不再更新当前视图；轮询改为串行，结构图及导出绑定展示快照 |
| 10 | P1 | 用索引定义字符串判断列是否已建索引，索引名称含 `products_mol` 就可能误报能力 | 从系统目录读取有效 GiST 的实际键列，排除索引名称、表达式和 INCLUDE 列造成的误判；真实来源目录查询已只读执行成功 |
| 11 | P1 | 来源/审核文件先完整读入内存，随后才检查 256 MiB / 32 MiB 上限，大文件可能在检查前耗尽内存 | 读取调用本身带字节上限及一个溢出哨兵；使用拒绝无界读取的文件替身验证两条入口 |
| 12 | P2 | 有效目标产品前还有一个非法产品结构，屏蔽评测重新解析脏产品而崩溃 | 从来源已核验的产品候选建立屏蔽集合；仍屏蔽整条目标来源记录并保留来源问题 |
| 13 | P2 | CLI 默认 `fixture` 覆盖环境中的 PostgreSQL 配置；显式 `fixture` 又可能继承真实 JSONL 路径 | 未指定来源时尊重环境；显式文件路径选择 JSONL；显式示例选择包内数据；拒绝互相冲突的来源参数 |
| 14 | P2 | 服务持有协调锁时，`inspect-run` 为读状态也创建协调器，导致查看失败 | 状态查看直接使用只读文件仓库操作，不获取协调锁或触发重启恢复 |
| 15 | P1 | 重排先保存成功状态再写快照，写盘失败后留下无结果的成功任务 | 先记录运行状态，快照保存成功后再统一终结；写入失败明确标记失败，正常及故障回归均通过 |

## 回归证据与复现入口

[整体审查回归](../tests/test_review_regressions.py)涵盖 01～08、10～12、15。修复前，先执行的 16 个后端场景中有 15 个失败；原本已正确处理的显式冲突场景通过。认证反例随后纳入完整接口回归。重排落盘顺序的两条新增反例修复前均失败；另增加初始阶段能力状态回归。

[前端异步回归](../tests/check_frontend_state.cjs)模拟状态、结果、错误和下载的乱序响应。这四个场景在修复前全部失败；修复后全部通过，并增加当前任务正常显示/导出和串行轮询两个正例。[Python 入口](../tests/test_frontend.py)把它们纳入 pytest；需要 Node.js，缺失时 pytest 会明确显示跳过。本次环境执行了全部六个场景。

[命令行回归](../tests/test_cli.py)覆盖环境来源、显式示例、显式路径、冲突参数和服务运行期间查看状态，修复前 6 个场景中有 5 个失败，修复后全部通过。

在仓库根目录运行：

```bash
implementation/.venv/bin/python implementation/scripts/check.py
```

本轮完整检查包含 92 项通过的测试、中文说明及注释检查、Ruff、mypy、契约漂移和 wheel 构建。实现/规则哈希和验证范围记录在 [verification.json](../evaluation/verification.json)。[固定样本报告](../evaluation/sample_report.json)重新执行了 12 个真实目标、24 个保留/屏蔽任务；它只能支持固定样本范围的结构命中与隔离结论。

## 主要修改位置

| 职责 | 文件 |
|---|---|
| 支链类别、重复块核验与覆盖 | [structures.py](../src/reaction_reference/chemistry/structures.py)、[markush.py](../src/reaction_reference/chemistry/markush.py)、[planner.py](../src/reaction_reference/retrieval/planner.py) |
| 来源大小上限、真实索引键与审核引用 | [sources.py](../src/reaction_reference/adapters/sources.py)、[annotations.py](../src/reaction_reference/adapters/annotations.py) |
| 证据冲突和明确实验排除项 | [claims.py](../src/reaction_reference/evidence/claims.py)、[engine.py](../src/reaction_reference/ranking/engine.py) |
| 中断状态与不可变快照 | [run_store.py](../src/reaction_reference/adapters/run_store.py)、[execution.py](../src/reaction_reference/adapters/execution.py) |
| 接口认证、命令行和页面异步状态 | [api.py](../src/reaction_reference/interfaces/api.py)、[cli.py](../src/reaction_reference/interfaces/cli.py)、[sdk.py](../src/reaction_reference/interfaces/sdk.py)、[index.html](../src/reaction_reference/interfaces/static/index.html) |
| 脏数据下的目标屏蔽 | [runner.py](../src/reaction_reference/evaluation/runner.py) |

## 本轮验证边界

- 真实来源的目录查询已验证，但当前缺少 `products_mol` 所需 GiST，未进行千万级索引召回或执行计划性能验收。
- 真实目标的有用方法标签仍未独立审核；本轮结构/逻辑回归不能替代化学方法准确率、迁移可行性或实验验证。
- 前端测试使用可控 DOM 与网络替身验证异步逻辑，本轮没有增加真实浏览器视觉验收或容器部署验收。
- 这是一次代码与反例审查，覆盖已确认的错误，不宣称实现已经不存在其他 bug。当前未支持能力继续以 [STATUS](STATUS.md) 为准。
