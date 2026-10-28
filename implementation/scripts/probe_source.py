"""Read-only constant chemistry probes and catalog readiness; never creates indexes."""

import json
import os

import psycopg
from psycopg.rows import dict_row

from reaction_reference.adapters.sources import PostgresSource


def main():
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
