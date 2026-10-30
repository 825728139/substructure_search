"""命令行入口：检索、预览、服务、来源有限导出、评测及契约导出共用业务模块。"""

import argparse
import json
import sys
from pathlib import Path

from reaction_reference.adapters.files import atomic_write_text
from reaction_reference.domain.models import (
    BudgetConfig,
    RerankRequest,
    SearchOptions,
    SearchRequest,
    Target,
)
from reaction_reference.interfaces.sdk import Client
from reaction_reference.rules import capabilities, load_rules
from reaction_reference.settings import Settings


def _write(data, path=None):
    """把可 JSON 序列化数据写入指定文件或标准输出，保留中文并缩进。

    指定文件时创建父目录；写入失败由外层命令入口统一转换为失败退出码。
    """
    content = json.dumps(data, ensure_ascii=False, indent=2)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(path), content + "\n")
    else:
        print(content)


def main(argv=None):
    """解析 argv 并分派 CLI 命令，返回进程退出码。

    检索成功返回 0，资料为部分范围返回 2，请求/运行错误返回 1；其他管理命令完成时返回 0。来源连接只从 Settings 读取；服务默认仅绑定 127.0.0.1，不在这里实现第二套化学流程。
    """
    parser = argparse.ArgumentParser(prog="reaction-reference")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("search", "preview"):
        child = sub.add_parser(command)
        target = child.add_mutually_exclusive_group(required=True)
        target.add_argument("--target")
        target.add_argument("--target-file")
        child.add_argument("--source", choices=["jsonl", "fixture", "postgres"])
        child.add_argument("--source-path")
        child.add_argument("--output")
        child.add_argument("--exhaustive-fixture", action="store_true")
        child.add_argument("--time-ms", type=int, default=10000)
    inspect = sub.add_parser("inspect-run")
    inspect.add_argument("run_id")
    re = sub.add_parser("rerank")
    re.add_argument("run_id")
    re.add_argument(
        "--profile",
        choices=["reference_first", "lab_fit", "process_reference"],
        default="reference_first",
    )
    sub.add_parser("validate-rules")
    sub.add_parser("capabilities")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    export = sub.add_parser("export-schemas")
    export.add_argument("--output-dir", default="contracts")
    sample = sub.add_parser("export-sample")
    sample.add_argument("--output", required=True)
    sample.add_argument("--limit", type=int, default=300)
    sample.add_argument("--after-id", type=int, default=0)
    select = sub.add_parser("select-evaluation-targets")
    select.add_argument("--source-path", required=True)
    select.add_argument("--output", required=True)
    select.add_argument("--count", type=int, default=12)
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--source-path", required=True)
    evaluation.add_argument("--targets", required=True)
    evaluation.add_argument("--output", required=True)
    evaluation.add_argument("--max-tasks", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        if args.command == "select-evaluation-targets":
            from reaction_reference.evaluation.runner import select_targets

            _write(select_targets(args.source_path, args.output, args.count))
            return 0
        if args.command == "evaluate":
            from reaction_reference.evaluation.runner import evaluate

            _write(evaluate(args.source_path, args.targets, args.output, max_tasks=args.max_tasks))
            return 0
        if args.command == "export-sample":
            from reaction_reference.adapters.export import export_sample

            _write(
                export_sample(
                    settings.postgres_dsn, args.output, limit=args.limit, after_id=args.after_id
                )
            )
            return 0
        if args.command == "serve":
            import uvicorn

            from reaction_reference.interfaces.api import create_app

            uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1)
            return 0
        if args.command == "validate-rules":
            rules, content_hash = load_rules()
            _write({"version": rules["version"], "hash": content_hash, "valid": True})
            return 0
        if args.command == "capabilities":
            _write(capabilities())
            return 0
        if args.command == "export-schemas":
            from reaction_reference.schema_export import export_schemas

            export_schemas(Path(args.output_dir))
            return 0
        if args.command == "inspect-run":
            from reaction_reference.adapters.run_store import FileRunStore

            # 只读状态不创建协调器，也不触发重启恢复，允许与运行中的服务共用目录。
            _write(FileRunStore(settings.store_path).load(args.run_id).model_dump(mode="json"))
            return 0
        if args.command in ("search", "preview"):
            if args.source_path and args.source in ("fixture", "postgres"):
                raise ValueError("--source-path requires a JSONL source")
            updates: dict = {}
            if args.source is not None:
                updates["source_kind"] = "postgres" if args.source == "postgres" else "jsonl"
            if args.source_path:
                updates.update(source_kind="jsonl", source_path=Path(args.source_path))
            if args.source == "fixture":
                # 显式示例使用模型声明的包内默认数据，避免继承真实来源文件路径。
                updates["source_path"] = Settings.model_fields["source_path"].get_default(
                    call_default_factory=True
                )
            settings = settings.model_copy(update=updates)
            text = Path(args.target_file).read_text().strip() if args.target_file else args.target
            if not text or len(text.splitlines()) != 1:
                raise ValueError("Provide exactly one nonempty target SMILES")
            request = SearchRequest(
                target=Target(value=text),
                budget=BudgetConfig(time_ms=args.time_ms),
                options=SearchOptions(exhaustive_fixture=args.exhaustive_fixture),
            )
            if args.command == "preview":
                # 纯查询规划不创建协调器，不能占目录锁或触发遗留任务恢复。
                _write({"families": [f.model_dump() for f in Client.preview(request)]}, args.output)
                return 0
            with Client(settings) as client:
                result = client.search(request)
                _write(result.model_dump(mode="json"), args.output)
                return 0 if result.coverage_state == "complete" else 2
        with Client(settings) as client:
            if args.command == "rerank":
                _write(
                    client.rerank(
                        args.run_id, RerankRequest(ranking_profile=args.profile)
                    ).model_dump(mode="json")
                )
        return 0
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        print(
            json.dumps({"code": "request_failed", "message": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
