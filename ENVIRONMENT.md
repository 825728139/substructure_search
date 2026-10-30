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

当前默认 Python 包索引为清华 TUNA 的 PyPI 镜像，已在 `pyproject.toml` 显式配置，锁文件记录具体下载地址和内容哈希。更换索引时需要重新生成并审阅锁文件。

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

本机通过 Conda 安装 Python 解释器，项目依赖由 uv 管理。重建本机环境可使用：

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

环境依赖检查、9 个局部化学探针和 11 张设计图生成已通过。每次验证的版本、输出与时间保存在本地报告中；文档与数据文件数量由检查脚本动态统计。

[环境检查脚本](scripts/verify_environment.py) 验证：

1. Python 3.12 及声明的主要依赖可以导入，并记录版本。
2. FastAPI、Pydantic 与 HTTPX 的本地异步 ASGI 调用协同正常；严格字段校验拒绝类型错误输入，调用有整体时间上限。
3. RDKit 能解析结构、生成分子图片；`reviews/check_*.py` 中的 9 个探针成功执行，范围见 [验证说明](reviews/README.md)。
4. Graphviz 能重新生成现有设计图；Markdown 链接和 SVG 文件通过完整性检查。

探针和图表在临时目录执行，避免验证时重写已经提交的研究结果。完整报告保存在本地 `.cache/environment-check/latest.json`。

本页上述检查用于设计探针和环境复现。业务实现现已在 `implementation/` 使用自己的 `pyproject.toml`、`uv.lock` 和 `.venv`；其化学、来源、预算、API 和打包验证独立记录在 [实现状态](implementation/docs/STATUS.md)，执行方式为该目录下 `uv run --frozen python scripts/check.py`。设计探针通过与业务测试通过分别记录。

## 开发工具与依赖更新

已声明 pytest、pytest-cov、pytest-asyncio、Ruff、mypy、Hypothesis、import-linter、JSON Schema 验证器及构建工具。业务实现的模块导入约束、类型检查和本地测试已在 `implementation/` 配置；根目录环境继续用于设计探针与图表。

新增或更新依赖时，先修改 `pyproject.toml`，再通过 `./scripts/project-uv lock` 解析，并用 `./scripts/project-uv sync --locked` 安装及重新验证。提交清单和锁文件；不能只手工修改本地 `.venv`。

RDKit 暂固定为 `2026.3.2`（其运行时显示为 `2026.03.2`）。升级需额外审查匹配语义、芳香性、立体与原子对应行为，不能只验证导入成功。

仓库根目录设置 `tool.uv.package = false`，用于管理设计检查所需的开发环境。可安装的 `reaction_reference` 业务包已位于 `implementation/`，使用该目录独立的构建配置、依赖锁和运行环境；启动与安装方式见[项目 README](implementation/README.md)。

## Git 与 VS Code

仓库元数据使用标准 `.git/` 目录，VS Code 源代码管理和普通 `git` 命令共享同一份提交、索引与远端配置。直接使用 `git status`、`git log --oneline` 和 `git show <commit>`；`./scripts/plan-git` 仅兼容原有命令写法，也操作这份标准仓库。

本机曾使用的 `.plan-history.git/` 现仅作为迁移前的历史备份保留，不再接收提交，也不提交到远端。若 VS Code 仍显示初始化前的状态，刷新源代码管理视图即可。
