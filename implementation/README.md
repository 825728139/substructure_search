# 反应参考检索实现

输入一个具体有机目标分子的 SMILES，在模型预测之前生成整体、核心、分片三层 Markush 查询，找出参考反应，分析实际连接与修饰贡献，给出有来源约束的反应物替换建议和可追溯资料包。提供 CLI、Python SDK、HTTP API 和内部查看页面，不包含收费功能。

交接阅读从 [中文代码交接指南](docs/HANDOVER.md) 开始；其中包括项目目录、实际调用链、关键对象和编号含义、修改入口及验证步骤。全部具名 Python 函数有中文说明，可通过 [函数索引](docs/FUNCTION_INDEX.md) 直接定位。

![项目运行架构](docs/system-architecture.svg)

![核心业务逻辑](docs/core-business-flow.svg)

两图分别提供 [运行架构 PNG](docs/system-architecture.png) 与 [业务逻辑 PNG](docs/core-business-flow.png)，可编辑的 `.dot` 源文件位于同一目录。

## 启动

需要 Python 3.12 和 uv。当前工作区已经在本目录的 `.venv/` 安装了锁定环境，可以从仓库根目录直接运行：

```bash
./implementation/scripts/rr serve
```

打开 <http://127.0.0.1:8000>；接口文档在 `/docs`。默认来源是六条**明确标记的合成示例**，用于检查结构匹配、反应变化和单反应物替换，真实文献制备命中数始终为零。示例目标 `CCCNC(=O)c1ccccc1` 可以看到将来源乙胺换成丙胺的图回放建议；它不代表实验已经成功。

全新克隆安装：

```bash
cd implementation
uv sync --frozen --python 3.12
uv run --frozen reaction-reference serve
```

命令行导出完整结果：

```bash
./implementation/scripts/rr search --target 'CCCNC(=O)c1ccccc1' --output var/reference.json
./implementation/scripts/rr preview --target 'CCCNC(=O)c1ccccc1'
./implementation/scripts/rr capabilities
```

`search` 退出码：`0` 表示已完成声明的有限来源/家族范围，`2` 表示返回部分结果，`1` 表示请求或运行失败。默认在线参考模式允许部分结果；检查 `coverage_state / stop_reasons / family_states`，不要把退出码 2 当成“没有参考”。结构候选数、真实制备实验数、输入使用数、推定替换建议分别统计。

## 使用实际来源

JSONL 可以采用本项目 [ReactionRecord 契约](contracts/ReactionRecord.schema.json)，也可以使用现有反应表导出字段。每行一条反应；五类 `*_smiles` 必须是数组。单独的产物数组不构成“报告制得”证据。

```bash
./implementation/scripts/rr search --source jsonl --source-path /path/reactions.jsonl \
  --target '你的目标SMILES' --output var/reference.json
```

服务切换到 JSONL：设置 `RR_SOURCE_KIND=jsonl` 和 `RR_SOURCE_PATH=/absolute/path/reactions.jsonl` 后启动。适配器限定为 20,000 条、256 MiB 的开发/评测来源，不把 Python 顺序读取当作千万级在线方案。

PostgreSQL 通过环境变量 `RR_POSTGRES_DSN` 接入，命令使用 `--source postgres`。凭据不写入代码、结果包或 Git。读取使用 Repeatable Read 和只读事务；要求有效的 mol GiST 索引。可用的指纹 GiST 索引提供整侧 KNN 初选，随后独立的 mol 子结构游标和逐材料 Markush 核验补充参考。KNN 池不是全量子结构筛选保证；现有整侧指纹也不冒充具体产物的指纹。每条 SQL 有超时，不执行全量 COUNT 或对全量命中做排序。接口依据为 [RDKit Cartridge 官方说明](https://www.rdkit.org/docs/Cartridge.html#operators)。当前来源未提供具体材料质量索引，因此不在源 SQL 内临时全表计算分子量。

2026-10-29 的只读检查确认源库尚无这些化学索引，在线适配器会报告未就绪。可以显式导出一个有数量上限的样本先使用，不会自动回退全表扫描，也不会自动修改源库：

```bash
./implementation/scripts/rr export-sample --limit 300 --output var/reactions.jsonl
```

`configs/internal.env.example` 列出允许配置。`RR_EVIDENCE_PATH` 可加载[审核证据覆盖文件](contracts/EvidenceAnnotation.schema.json)：每条审核必须绑定来源记录哈希、审核人/日期、具体产品观察和引文位置；只有明确的操作段落才赋予 `documented_step`。来源变更造成哈希不符时，拒绝套用旧审核。合成示例的来源标记不能被覆盖为文献事实。

## 调用接口

```bash
curl -X POST http://127.0.0.1:8000/v1/search-runs \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: example-1' \
  -d '{"target":{"value":"CCCNC(=O)c1ccccc1"}}'
```

通过返回的 `run_id` 查询状态和 `/results`，完整包使用 `/package`。原子编号对应 `target_input_smiles` 的解析顺序；`target_smiles` 是用于身份比较的规范表示，不用它重排已有编号。其他接口包括 `/cancel`、`/rerank`、`/evidence/{id}` 和带原子高亮的 `/structures/{reference_id}.svg`。分页游标绑定不可变快照；重排只使用已保存的全部候选，不再次查询来源。设置 `RR_API_TOKEN` 后，业务接口需要 `Authorization: Bearer ...`。内部令牌代表一个访问范围，不提供外部多租户账户。

```python
from reaction_reference.domain.models import SearchRequest, Target
from reaction_reference.interfaces.sdk import Client

# 放在脚本 main 函数中；独立进程采用 spawn。
if __name__ == "__main__":
    with Client() as client:
        package = client.search(SearchRequest(target=Target(value="CCCNC(=O)c1ccccc1")))
        print(package.statistics["by_layer"])
```

## 项目目录与模块

```text
implementation/
├── src/reaction_reference/
│   ├── domain/                 # 请求、查询家族、见证、反应、证据和结果契约
│   ├── chemistry/              # 结构、带位点的完整 R 块、联合映射与完整目标校验
│   ├── retrieval/              # 三层家族、严格目标补查、缺失位点定向家族
│   ├── reaction_analysis/      # 端点校对、真实键/原子属性变化、环变化、目标位点投影
│   ├── analogs/                # 来源自回放、radius-2 模板/有限注册规则、单反应物替换
│   ├── evidence/               # 产品观察、输入使用、来源引用、已返回材料关系和摘要
│   ├── ranking/                # 九方向事实/未知、参考优先与实验适配、展示多样性
│   ├── application/            # 检索编排、全局预算、阶段结果和 manifest
│   ├── ports/                  # 来源接口
│   ├── adapters/               # JSONL/只读 PG、证据审核、独立进程、文件快照
│   ├── interfaces/             # CLI、SDK、HTTP、内部页面和结构图
│   ├── evaluation/             # 真实目标选样、目标制备记录屏蔽、标注指标
│   └── resources/              # 可执行有限规则与明确标记的合成示例
├── contracts/                  # 导出的 JSON Schema / OpenAPI，CI 检查漂移
├── configs/                    # 内部环境配置示例
├── tests/                      # 化学回归、来源/预算、API 生命周期与模块边界
├── evaluation/                 # 真实样本试跑报告；未经标注不计算方法召回率
├── scripts/                    # 启动、自检、中文说明检查/函数索引、只读来源探针
├── deploy/                     # Dockerfile 与单协调器 Compose
└── docs/                       # 中文交接指南、函数索引、两张架构图及实现状态
```

## 验证与评测

```bash
cd implementation
uv run --frozen python scripts/check.py
```

检查包括全仓库 Python 中文说明与独立/行尾注释、Ruff、mypy、模块导入边界、化学及服务测试、契约漂移、wheel 打包。用 `python scripts/check_comments.py --write-index` 可刷新函数阅读索引。运行记录见 [实现与验证范围](docs/STATUS.md)。默认不访问源库；可选只读来源探针为 `uv run python scripts/probe_source.py`。

```bash
./implementation/scripts/rr select-evaluation-targets --source-path var/reactions.jsonl \
  --output var/targets.jsonl --count 12
./implementation/scripts/rr evaluate --source-path var/reactions.jsonl \
  --targets var/targets.jsonl --output var/evaluation.json
```

每个目标分别测“保留目标记录”和“屏蔽全部生成该目标的记录”。自动选样是结构多样性选样；标注状态默认 `unreviewed`。只有设置了审核后的有用方法记录标签，才计算对应标注召回；正例标注不被当作完整相关性标注来计算精确率。当前结果不代表下游模型效果或千万级性能。

## 运行约束

API 必须单协调进程、单 Uvicorn worker；目录锁会拒绝同时写同一个运行目录。计算任务在独立子进程中执行，支持硬超时/取消；源 SQL 另有限时。预算从执行开始计算，强制终止后的清理可能额外占用最多约 2 秒。服务重启后，不续接已失效的来源会话，保留已有快照并标记中断。

运行文件保存在 `RR_STORE_PATH`，默认 `var/runs`。当前没有自动到期清理，内部试用需监控并在停止服务后清理不再需要的运行目录；删除目录会使对应结果不可读。不要把运行目录当作永久资料归档。

Docker/Compose 配置位于 `deploy/`，可用 `docker compose -f deploy/compose.yaml up --build` 启动。默认只绑定本机端口。当前机器的 Docker daemon 访问权限不足，镜像构建和容器运行尚未验证；本机 Python 服务已完成运行验证。

保护基/互变异构体自动展开、任意可变路径 Markush、金属配位处理、共同中间体主动补查、供应/危害外部资料接入、化学可行性和条件预测尚未实现，均有明确能力状态。现有材料身份关系只是已返回记录之间的线索。模板回放成功不证明选择性、实验可行性或条件可照搬。完整范围见 [STATUS](docs/STATUS.md)；产品和化学设计见[上层实现计划](../implementation_plan.md)。
