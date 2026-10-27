# 开发环境与验证

本项目使用 Python 3.12、RDKit 2026.03.2 和 uv 管理的独立环境。运行依赖与开发依赖在 [pyproject.toml](pyproject.toml) 中声明，解析后的具体版本由 [uv.lock](uv.lock) 固定；Python 版本见 [.python-version](.python-version)。

环境准备属于 [实现计划](implementation_plan.md) 的 M0 阶段。业务包、检索 CLI、HTTP 业务接口及完整引擎测试仍需按计划实现。

## 安装与复现

需要已有 `uv` 命令。图表生成还依赖系统 Graphviz 的 `dot` 命令和中文字体，这些不属于 Python 锁文件管理范围。本机已有这些系统工具。

在项目根目录执行：

```bash
# 首次安装解释器；--no-bin 避免向用户全局目录添加可执行文件。
./scripts/project-uv python install 3.12.12 --no-bin

# 按已提交的锁文件安装，默认包含 dev 组。
./scripts/project-uv sync --locked

# 验证依赖协作、现有化学探针、图表生成与文档链接。
./scripts/project-uv run --locked python scripts/verify_environment.py
```

首次安装需要联网；已安装且缓存完整时，可以在 uv 命令中加入 `--offline`。缺少缓存会明确失败，不会更换依赖版本。

当前默认 Python 包索引为清华 TUNA 的 PyPI 镜像，已在 `pyproject.toml` 显式配置，锁文件记录具体下载地址和内容哈希。本机访问 PyPI 官方下载较慢，因此选用实测可用的镜像。更换索引时需要重新生成并审阅锁文件，不能带着另一来源的锁文件假定 `--locked` 会自动切换来源。

[scripts/project-uv](scripts/project-uv) 将解释器、虚拟环境和下载缓存限定在项目目录：

| 路径 | 用途 | 是否提交 |
|---|---|---|
| `.runtime/python/` | uv 安装的独立 Python | 否 |
| `.runtime/cpython/` | 当前机器通过 Conda 安装的备用 Python | 否 |
| `.venv/` | 本项目运行与开发依赖 | 否 |
| `.cache/uv/` | 下载与安装缓存 | 否 |
| `.cache/environment-check/latest.json` | 最近一次成功的环境验证报告 | 否 |
| `.python-version`、`pyproject.toml`、`uv.lock` | 可复现版本与依赖配置 | 是 |

后续运行优先使用 `./scripts/project-uv run --locked ...`，也可以直接调用 `.venv/bin/python`，或执行 `source .venv/bin/activate`。不要通过系统默认 `python3` 推断本项目使用的 Python 版本。

### 当前机器的解释器来源

本机访问 GitHub 的 Python 独立发行版下载很慢并触发重试，因此改用已有 Conda，从官方 `repo.anaconda.com/pkgs/main` 获取同版本 Python。Conda 仅提供独立解释器；项目依赖全部安装在 uv 管理的 `.venv` 中。重建本机环境可使用：

```bash
CONDA_PKGS_DIRS=.cache/conda conda create --prefix .runtime/cpython \
  --override-channels --channel https://repo.anaconda.com/pkgs/main \
  --no-default-packages python=3.12.12 -y
./scripts/project-uv sync --locked --python .runtime/cpython/bin/python
```

已有 `.venv` 后，普通的 `run --locked` 会复用它。其他机器可以使用上面的 uv 独立解释器方案，无需安装 Conda。当前验证平台为本机 Linux x86_64；其他系统需重新执行同一验证脚本。

## 检查范围

2026-10-27 已在本机 Linux x86_64 完成安装与验证，主要版本如下：

| 组件 | 实际版本 |
|---|---|
| Python / uv | 3.12.12 / 0.9.22 |
| RDKit / NumPy | 2026.03.2 / 2.5.4 |
| FastAPI / Pydantic | 0.162.0 / 2.14.1 |
| Uvicorn / HTTPX | 0.54.0 / 0.28.1 |
| pytest / Ruff / mypy | 9.1.1 / 0.17.3 / 1.20.2 |
| Hypothesis / import-linter | 6.170.12 / 2.15 |

52 个已安装第三方包通过依赖一致性检查；`sync --locked --offline --check` 确认无需变更。新环境中 9 个现有化学探针通过、11 张设计图重新生成成功、31 份 Markdown 和 11 个 SVG 的完整性检查通过。新增环境脚本通过 Ruff 检查。

[环境检查脚本](scripts/verify_environment.py) 验证：

1. Python 3.12 及声明的主要依赖可以导入，并记录版本。
2. FastAPI、Pydantic 与 HTTPX 的本地异步 ASGI 调用协同正常；严格字段校验拒绝类型错误输入，调用有整体时间上限。
3. RDKit 能解析结构、生成分子图片；已有 `reviews/check_*.py` 和 `audits/probes/*.py` 探针成功执行。
4. Graphviz 能重新生成现有设计图；Markdown 链接和 SVG 文件通过完整性检查。

探针和图表在临时目录执行，避免验证时重写已经提交的研究结果。完整报告保存在本地 `.cache/environment-check/latest.json`。

这些检查证明环境可用于开发和重现局部研究。三层 Markush 编译器、来源适配器、反应贡献分析、排序和检索 API 尚未由这些检查验证。当前没有完整业务测试套件，不能把安装了 pytest 记作通过引擎测试。

## 开发工具与依赖更新

已声明 pytest、pytest-cov、pytest-asyncio、Ruff、mypy、Hypothesis、import-linter、JSON Schema 验证器及构建工具。业务模块出现后，再配置模块导入约束、完整类型检查、测试发现与 CI。

新增或更新依赖时，先修改 `pyproject.toml`，再通过 `./scripts/project-uv lock` 解析，并用 `./scripts/project-uv sync --locked` 安装及重新验证。提交清单和锁文件；不能只手工修改本地 `.venv`。

RDKit 暂固定为 `2026.3.2`（其运行时显示为 `2026.03.2`）。升级需额外审查匹配语义、芳香性、立体与原子对应行为，不能只验证导入成功。

目前 `tool.uv.package = false`：环境包含第三方依赖，尚不发布或安装一个空的 `reaction_reference` 业务包。到 M0 创建真实业务包时，再补齐构建后端、包发现、CLI 入口和包安装检查。
