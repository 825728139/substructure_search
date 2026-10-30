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

命令行未指定 `--source` 时使用环境中的来源配置；`--source-path` 显式选择 JSONL 文件。`--source fixture` 固定使用包内示例，不能同时指定来源路径。服务运行期间可用 `./implementation/scripts/rr inspect-run 任务编号` 只读查看同一运行目录中的状态。

`preview` 只根据目标和请求生成查询家族，不读取来源或接管运行目录，服务运行期间也可使用。Python 可直接调用 `Client.preview(request)`，无需创建客户端实例。

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

有限导出保留 `reaction_center_r2` 来源模板，重新加载后可参与受约束回放。旧导出若缺失此字段，需要显式重新导出才能补齐；模板存在不代表反应有制备证据。

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
├── contracts/                  # 导出的 JSON Schema / OpenAPI，本地检查漂移
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

当前共 429 项测试；其中前端异步状态回归使用 Node.js，缺失时会明确显示跳过。本轮确认问题、修复及测试对应关系见[整体代码审查记录](docs/CODE_REVIEW.md)。

### 真实来源和浏览器集成检查

PostgreSQL 回归要求 `initdb`、`pg_ctl`、`pg_config` 在 PATH 中，且该 PostgreSQL 已安装 RDKit 扩展。测试自动创建和关闭私有 Unix socket 临时库，不接受生产连接参数。浏览器回归需要可选 Playwright 和 Chromium；缺少这些依赖时 pytest 会明确跳过相应测试。本次验证使用 Playwright 1.64.1：

```bash
# 在 implementation 目录运行；浏览器安装属于开发验证，不是服务运行依赖。
uv run --frozen --with playwright==1.64.1 python -m playwright install chromium
uv run --frozen --with playwright==1.64.1 python scripts/check.py
```

已有 Chromium 可通过 `RR_TEST_CHROMIUM_PATH` 指定可执行文件。需要单独排查时运行 `tests/test_postgres_integration.py` 或 `tests/test_browser_integration.py`。本机已通过 33 项真实 SQL 和 7 项真实浏览器检查；小样本集成通过不代表现库执行计划、全库性能或跨浏览器兼容性已验收。

后续三轮新增的 11 类修复与逐轮验证见[三轮复审记录](docs/MULTI_ROUND_REVIEW.md)。审核文件按补丁处理：省略字段会保留来源原值，显式空列表表示清空；使用 Python 模型生成补丁时应调用 `model_dump_json(exclude_unset=True)` 保留字段是否提供的区别。

任务并发、半包超时、排队取消、关闭和持久化的代码修复及故障注入证据见[执行层审查记录](docs/RUNTIME_REVIEW.md)。

来源定位不完整时按记录保留实验计数；读取快照会核对内容与路径身份；有限样本导出成功后才发布最终文件。相关反例和空结果重排校验见[数据边界审查](docs/DATA_BOUNDARY_REVIEW.md)。

```bash
./implementation/scripts/rr select-evaluation-targets --source-path var/reactions.jsonl \
  --output var/targets.jsonl --count 12
./implementation/scripts/rr evaluate --source-path var/reactions.jsonl \
  --targets var/targets.jsonl --output var/evaluation.json
```

每个目标分别测“保留目标记录”和“屏蔽全部生成该目标的记录”。自动选样是结构多样性选样；标注状态默认 `unreviewed`。只有设置了审核后的有用方法记录标签，才计算对应标注召回；正例标注不被当作完整相关性标注来计算精确率。当前结果不代表下游模型效果或千万级性能。

## 运行约束

API 必须单协调进程、单 Uvicorn worker；目录锁会拒绝同时写同一个运行目录。计算任务在独立子进程中执行，支持硬超时/取消；源 SQL 另有限时。预算从进程启动准备开始计算；通信半包不会阻塞监督循环。进程与接收线程清理额外等待最多约 3 秒，另有文件 I/O 耗时。SDK 默认等待包含排队时间，显式传入 `wait(timeout=...)` 可限制调用方等待。服务重启后，不续接已失效的来源会话，保留已有快照并标记中断。

运行文件保存在 `RR_STORE_PATH`，默认 `var/runs`。当前没有自动到期清理，内部试用需监控并在停止服务后清理不再需要的运行目录；删除目录会使对应结果不可读。不要把运行目录当作永久资料归档。

重启时单个损坏状态或快照会单独记录到 `/health/ready` 的 `recovery_issues`，原文件保留，其他有效任务继续恢复；权限或真实磁盘 I/O 错误仍会报错。该机制用于隔离局部损坏，不会自动修复坏文件。

运行收尾时若中断快照无法发布、但状态文件仍可写，任务记为 `failed`，错误码为 `snapshot_finalization_failed`。状态仍可查询，默认结果读取返回 409；旧快照保留，可按原快照编号显式导出。此兜底不能保证整个运行目录不可写时仍能保存终态。

Docker/Compose 配置位于 `deploy/`，在本目录可用 `docker compose -f deploy/compose.yaml up --build` 启动，默认只绑定本机端口。镜像安装 RDKit 绘图需要的系统共享库，并在构建阶段验证绘图模块导入。构建参数 `PIP_INDEX_URL` 仅指定 pip 安装 uv 时使用的镜像，默认使用 PyPI；它不会覆盖 `uv.lock` 中锁定的运行依赖下载地址，当前锁文件使用清华镜像。

本机已使用无特权 Podman 按 Docker 格式构建镜像，并以 UID 10001、只读根目录、独立运行卷验证真实 HTTP、结构图、重排和重启保留。Docker daemon 权限仍不可用，因此 Compose 编排本身只做了配置检查。

合成示例部署就绪后，可运行以下检查；访问令牌从 `RR_API_TOKEN` 环境变量读取。检查会创建示例任务，应对包内示例部署运行：

```bash
python scripts/check_deployment.py --base-url http://127.0.0.1:8000 --output /tmp/container-check.json
```

项目采用本地检查和手动部署，不配置持续集成。部署检查脚本按需运行，用于确认目标环境的依赖和接口可用。

保护基/互变异构体自动展开、任意可变路径 Markush、金属配位处理、共同中间体主动补查、供应/危害外部资料接入、化学可行性和条件预测尚未实现，均有明确能力状态。现有材料身份关系只是已返回记录之间的线索。模板回放成功不证明选择性、实验可行性或条件可照搬。完整范围见 [STATUS](docs/STATUS.md)；产品和化学设计见[上层实现计划](../implementation_plan.md)。
