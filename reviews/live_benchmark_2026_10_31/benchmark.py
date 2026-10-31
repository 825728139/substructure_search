"""只读真实库基准：仅重定向表名，保留原有检索和排序算法，并记录逐次耗时。"""

import argparse
import json
import multiprocessing
import os
import time
from pathlib import Path

import psycopg
from rdkit import Chem
from rdkit.Chem import Descriptors

from reaction_reference.adapters.sources import PostgresSource
from reaction_reference.application.search import search
from reaction_reference.domain.models import SearchRequest, Target
from reaction_reference.rules import code_fingerprint

ROOT = Path(
    os.environ.get(
        "RR_BENCH_OUTPUT",
        str(Path(__file__).resolve().parents[2] / ".cache/live-benchmark-2026-10-31"),
    )
)
SOURCE_TABLE = os.environ.get("RR_BENCH_TABLE", "reaction_v2")
if SOURCE_TABLE not in ("reaction_v2", "reaction_v3"):
    raise ValueError("测试来源仅允许 reaction_v2 或 reaction_v3")
TARGETS = [
    (
        "T01",
        "乙酰苯胺：小分子酰胺",
        "CC(=O)Nc1ccccc1",
        "预先指定的小分子，检查宽查询和真实酰胺转化",
    ),
    ("T02", "β-丙氨酸乙酯：无环目标", "CCOC(=O)CCN", "预先指定的无环目标，盐形差异单独判断"),
    (
        "T03",
        "甲氧基苯基–吡啶：联芳基",
        "COc1ccc(-c2cccnc2)cc1",
        "预先指定的芳基连接目标，检查是否找到构建连接的方法",
    ),
    (
        "T04",
        "Boc哌啶–氟苯甲酰胺：支链接母核",
        "CC(C)(C)OC(=O)N1CCC(NC(=O)c2ccc(F)cc2)CC1",
        "预先指定的较大多官能团目标，检查酰胺连接与保护基差异",
    ),
    (
        "T05",
        "Boc哌啶β-酮酯：库内阳性",
        "CCOC(=O)CC(=O)C1CCN(C(=O)OC(C)(C)C)CC1",
        "前次只读核验中reaction_v2的id=2产物；作为自命中阳性，不代表泛化",
    ),
    (
        "T06",
        "Boc脯氨酸甲酯：手性目标",
        "COC(=O)[C@@H]1CCCN1C(=O)OC(C)(C)C",
        "预先指定手性结构；连接相同不能代替立体结果证据",
    ),
    (
        "T07",
        "Boc哌啶酰化Meldrum酸：库内阳性",
        "CC(C)(C)OC(=O)N1CCC(C(=O)C2C(=O)OC(C)(C)OC2=O)CC1",
        "前次只读核验中reaction_v2的id=3产物；检查环状片段的真实反应作用",
    ),
    (
        "T08",
        "2-吡咯烷酮：小环内酰胺",
        "O=C1CCCN1",
        "预先指定的环状目标，不预猜断环位点，观察返回先例是否提供成环或后修饰",
    ),
]

TARGETS.extend(
    [
        (
            "T09",
            "多取代苯甲酰胺：无精确先例目标",
            "CC(C)(C)OC(=O)N1CCC(NC(=O)c2cc(F)c(OC(F)F)cc2Cl)CC1",
            "独立构造的T04支链替换目标；限定精确GIN探针确认12分以上来源无同一产物",
        ),
        (
            "T10",
            "氟代联芳基羟乙基酰胺：无精确先例目标",
            "COc1cc(F)c(-c2cc(C(=O)NCCO)cnc2)cc1",
            "独立构造的多连接目标；限定精确GIN探针确认12分以上来源无同一产物",
        ),
        (
            "T11",
            "氟代支化氨基酯：无精确先例目标",
            "CCOC(=O)C(C)(F)CCN",
            "独立构造的无环目标；限定精确GIN探针确认12分以上来源无同一产物",
        ),
    ]
)


def encode(value):
    """以中文可读形式序列化测试记录。"""
    return json.dumps(value, ensure_ascii=False, indent=2)


class ConnectionTrace:
    """只在测试连接中改表名，保留SQL参数、只读事务、门槛和查询顺序。"""

    def __init__(self, connection, events):
        """记录真实连接及本次调用的独立事件列表。"""
        self.connection, self.events = connection, events

    def query(self, query):
        """把固定来源表及其索引目录查询改到新表，不改检索条件。"""
        text = query if isinstance(query, str) else query.as_string(self.connection)
        return text.replace("reaction.reactions", f"reaction.{SOURCE_TABLE}").replace(
            "t.relname='reactions'", f"t.relname='{SOURCE_TABLE}'"
        )

    def execute(self, query, *args, **kwargs):
        """记录真实SQL执行时间与异常类型，不记录连接密码或SQL参数。"""
        query = self.query(query)
        started = time.perf_counter()
        error = None
        kind = (
            "knn"
            if "LIMIT 512" in query
            else "hydrate"
            if "to_jsonb(d)" in query
            else "catalog"
            if "pg_index" in query or "information_schema" in query
            else "control"
        )
        try:
            return self.connection.execute(query, *args, **kwargs)
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            self.events.append(
                {"kind": kind, "ms": (time.perf_counter() - started) * 1000, "error": error}
            )

    def cursor(self, *args, **kwargs):
        """包装服务端游标，单独计时打开与取页。"""
        return CursorTrace(self.connection.cursor(*args, **kwargs), self)

    def __getattr__(self, name):
        """其他属性和关闭操作交给真实连接。"""
        return getattr(self.connection, name)


class CursorTrace:
    """服务端游标计时包装，不更改分页或错误处理。"""

    def __init__(self, cursor, parent):
        """保存游标和对应连接计时器。"""
        self.cursor, self.parent = cursor, parent

    def execute(self, query, *args, **kwargs):
        """记录子结构游标声明时间。"""
        started = time.perf_counter()
        error = None
        try:
            return self.cursor.execute(self.parent.query(query), *args, **kwargs)
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            self.parent.events.append(
                {
                    "kind": "cursor_open",
                    "ms": (time.perf_counter() - started) * 1000,
                    "error": error,
                }
            )

    def fetchmany(self, *args, **kwargs):
        """记录数据库实际取页耗时及返回行数。"""
        started = time.perf_counter()
        error = None
        count = None
        try:
            rows = self.cursor.fetchmany(*args, **kwargs)
            count = len(rows)
            return rows
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            self.parent.events.append(
                {
                    "kind": "fetch",
                    "ms": (time.perf_counter() - started) * 1000,
                    "rows": count,
                    "error": error,
                }
            )

    def __getattr__(self, name):
        """关闭与游标状态读取保持原实现。"""
        return getattr(self.cursor, name)


def run_worker(target, repeat, budget_ms, timeout_ms, max_tasks, max_reactions):
    """在独立进程运行真实应用检索，实时保存最后阶段包，结束时落盘完整计时。"""
    tag = f"{target[0]}-{budget_ms}-r{repeat}"
    events = []
    source = None
    started = time.perf_counter()
    first_result = None
    report = {
        "target_id": target[0],
        "label": target[1],
        "target_smiles": target[2],
        "repeat": repeat,
        "budget_ms": budget_ms,
        "statement_timeout_ms": timeout_ms,
        "database_table": f"reaction.{SOURCE_TABLE}",
        "minimum_final_score": 12,
        "implementation_hash": code_fingerprint(),
        "harness_override": "only_source_table_and_catalog_table_name",
        "pid": os.getpid(),
    }
    original_connect = psycopg.connect

    def connect(*args, **kwargs):
        """为本进程来源创建真实的计时连接。"""
        return ConnectionTrace(original_connect(*args, **kwargs), events)

    def progress(package):
        """保存最新阶段包，并记录首次出现非空结果的时间。"""
        nonlocal first_result
        if package.results and first_result is None:
            first_result = (time.perf_counter() - started) * 1000
        (ROOT / f"{tag}.package.json").write_text(package.model_dump_json())

    try:
        psycopg.connect = connect
        try:
            source = PostgresSource(os.environ["RR_BENCH_DSN"], timeout_ms=timeout_ms)
        finally:
            psycopg.connect = original_connect
        report["connect_ms"] = (time.perf_counter() - started) * 1000
        request = SearchRequest(
            target=Target(value=target[2]),
            budget={"time_ms": budget_ms, "max_tasks": max_tasks, "max_reactions": max_reactions},
        )
        report["request"] = request.model_dump()
        package = search(request, source, run_id=tag, on_progress=progress)
        progress(package)
        report.update(
            status="returned",
            statistics=package.statistics,
            coverage_state=package.coverage_state,
            stop_reasons=package.stop_reasons,
            source_issues=package.source_issues,
            reference_count=len(package.results),
            displayed_count=len(package.displayed_reference_ids),
            proposal_count=len(package.proposals),
            exact_reference_count=sum(r.target_requirements_satisfied for r in package.results),
        )
    except Exception as exc:
        report.update(status="error", error_type=type(exc).__name__, error_message=str(exc)[:300])
    finally:
        if source:
            try:
                source.close()
            except Exception as exc:
                report["close_error"] = type(exc).__name__
        report.update(
            worker_elapsed_ms=(time.perf_counter() - started) * 1000,
            first_result_ms=first_result,
            events=events,
        )
        (ROOT / f"{tag}.metrics.json").write_text(encode(report))


def main():
    """顺序运行固定目标，限制并发为一，并以外层进程时限兜底原生计算。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default=",".join(t[0] for t in TARGETS))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--budget-ms", type=int, default=10000)
    parser.add_argument("--timeout-ms", type=int, default=1500)
    parser.add_argument("--max-tasks", type=int, default=40)
    parser.add_argument("--max-reactions", type=int, default=60)
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for target in TARGETS:
        mol = Chem.MolFromSmiles(target[2])
        assert mol is not None
        manifest.append(
            {
                "id": target[0],
                "label": target[1],
                "smiles": target[2],
                "selection_reason": target[3],
                "molecular_weight": Descriptors.MolWt(mol),
                "heavy_atoms": mol.GetNumHeavyAtoms(),
                "rings": mol.GetRingInfo().NumRings(),
            }
        )
    (ROOT / "targets.json").write_text(encode(manifest))
    for repeat in range(1, args.repeats + 1):
        for target in TARGETS:
            if target[0] not in args.ids.split(","):
                continue
            tag = f"{target[0]}-{args.budget_ms}-r{repeat}"
            path = ROOT / f"{tag}.metrics.json"
            if path.exists():
                saved = json.loads(path.read_text())
                if saved.get("database_table") != f"reaction.{SOURCE_TABLE}":
                    raise ValueError("输出目录已有其他表的测试结果，请使用独立目录")
                print(tag + " 已有结果，保留", flush=True)
                continue
            started = time.perf_counter()
            process = multiprocessing.get_context("spawn").Process(
                target=run_worker,
                args=(
                    target,
                    repeat,
                    args.budget_ms,
                    args.timeout_ms,
                    args.max_tasks,
                    args.max_reactions,
                ),
            )
            process.start()
            process.join(args.budget_ms / 1000 + 12)
            if process.is_alive():
                process.terminate()
                process.join(3)
                if process.is_alive():
                    process.kill()
                    process.join(3)
            report = (
                json.loads(path.read_text())
                if path.exists()
                else {
                    "target_id": target[0],
                    "repeat": repeat,
                    "budget_ms": args.budget_ms,
                    "status": "outer_timeout",
                    "database_table": f"reaction.{SOURCE_TABLE}",
                    "minimum_final_score": 12,
                }
            )
            report.update(
                total_wall_ms=(time.perf_counter() - started) * 1000, exit_code=process.exitcode
            )
            path.write_text(encode(report))
            process.close()
            print(
                encode(
                    {
                        k: report.get(k)
                        for k in [
                            "target_id",
                            "repeat",
                            "budget_ms",
                            "status",
                            "total_wall_ms",
                            "reference_count",
                            "displayed_count",
                            "proposal_count",
                            "stop_reasons",
                        ]
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
