"""手工来源验收脚本：只读常量 SMARTS/指纹探针与有效化学索引能力检查，不输出凭据。"""

import json
import os

import psycopg
from psycopg.rows import dict_row

from reaction_reference.adapters.sources import PostgresSource


def main():
    """读取 RR_POSTGRES_DSN，执行只读常量化学探针和索引就绪检查并打印 JSON。

    不执行全表反应检索或 DDL；缺少化学索引按未就绪输出，连接等系统错误向进程调用方报告。
    """
    dsn = os.environ["RR_POSTGRES_DSN"]
    with psycopg.connect(
        dsn, autocommit=True, connect_timeout=5, row_factory=dict_row
    ) as connection:
        connection.execute("BEGIN READ ONLY")
        connection.execute("SET LOCAL statement_timeout='1500ms'")
        row = connection.execute(
            """
          SELECT rdkit_version() AS server_rdkit,
                 'CCO'::mol @> %s::qmol AS alcohol_match,
                 'CCOC'::mol @> %s::qmol AS ether_match,
                 morganbv_fp('CCO'::mol,2) <%%> morganbv_fp(%s::mol,2) AS fingerprint_distance
        """,
            ("[#6&A&+0:1]-[#8&A&+0&H1&X2:2]", "[#6&A&+0:1]-[#8&A&+0&H1&X2:2]", "CCO"),
        ).fetchone()
        connection.execute("ROLLBACK")
    try:
        source = PostgresSource(dsn)
    except ValueError as exc:
        ready = {"ready": False, "reason": str(exc)}
    else:
        source.close()
        ready = {"ready": True}
    print(
        json.dumps(
            {
                "constant_chemistry_probes": row,
                "indexed_source": ready,
                "scope": "no_full_table_queries_or_ddl",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
