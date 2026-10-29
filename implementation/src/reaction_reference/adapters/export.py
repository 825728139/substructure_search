"""开发与评测使用的显式有限样本导出；主键分页取数，不要求化学索引，不作为在线子结构回退。"""

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path


def export_sample(dsn, output, *, limit=300, after_id=0, timeout_ms=3000):
    """只读按主键导出 after_id 后至多 limit 条反应到新的 JSONL 文件。

    dsn 由环境配置传入，不写入文件；读取投影排除大二进制字段，设置 SQL 超时并记录来源快照。数据先写同目录临时文件，成功后原子发布且拒绝覆盖。失败不发布残缺文件，提取产品字段不升级为制备证据。
    """
    import psycopg
    from psycopg.rows import dict_row

    if not dsn:
        raise ValueError("RR_POSTGRES_DSN is required")
    if not 1 <= limit <= 20000:
        raise ValueError("Explicit sample limit must be between 1 and 20000")
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    # 显式选择轻量字段，避免把大体积化学二进制和映射原始载荷一并导出。
    columns = (
        "id,source_type,source_namespace,document_id,paragraph_nums,paragraph_reaction_ordinal,"
        "product_smiles,reactant_smiles,reagent_smiles,catalyst_smiles,solvent_smiles,"
        "reaction_smiles,mapped_reaction_smiles,reaction_class,"
        "temperature_min_c,temperature_max_c,duration_max_seconds,pressure_max_kpa"
    )
    with psycopg.connect(
        dsn, connect_timeout=5, row_factory=dict_row, autocommit=True
    ) as connection:
        connection.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SELECT set_config('statement_timeout', %s, true)", (str(timeout_ms),))
        snapshot_row = connection.execute(
            "SELECT pg_current_snapshot()::text AS snapshot"
        ).fetchone()
        if snapshot_row is None:
            raise RuntimeError("Source snapshot unavailable")
        snapshot = snapshot_row["snapshot"]
        rows = connection.execute(
            "SELECT " + columns + " FROM reaction.reactions WHERE id>%s ORDER BY id LIMIT %s",
            (after_id, limit),
        ).fetchall()
        connection.execute("ROLLBACK")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=".reaction-export-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            for row in rows:
                stream.write(
                    json.dumps(
                        {**row, "export_snapshot": snapshot}, ensure_ascii=False, default=str
                    )
                    + "\n"
                )
            stream.flush()
            os.fsync(stream.fileno())
        # 同目录硬链接原子创建最终名称；即使另一导出同时完成，也不会覆盖对方文件。
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return {
        "records": len(rows),
        "after_id": after_id,
        "last_id": rows[-1]["id"] if rows else None,
        "source_snapshot": snapshot,
        "path": str(destination),
        "scope": "bounded_explicit_primary_key_sample",
        "outcome_evidence": "not_exported_product_fields_are_not_preparation_witnesses",
    }
