"""Explicit bounded primary-key export for development, independent of chemical indexes."""

import json
from pathlib import Path


def export_sample(dsn, output, *, limit=300, after_id=0, timeout_ms=3000):
    import psycopg
    from psycopg.rows import dict_row

    if not dsn:
        raise ValueError("RR_POSTGRES_DSN is required")
    if not 1 <= limit <= 20000:
        raise ValueError("Explicit sample limit must be between 1 and 20000")
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # The explicit projection excludes large binary chemistry and mapper payloads.
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
        with destination.open("x") as stream:
            for row in rows:
                row["export_snapshot"] = snapshot
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        connection.execute("ROLLBACK")
    return {
        "records": len(rows),
        "after_id": after_id,
        "last_id": rows[-1]["id"] if rows else None,
        "source_snapshot": snapshot,
        "path": str(destination),
        "scope": "bounded_explicit_primary_key_sample",
        "outcome_evidence": "not_exported_product_fields_are_not_preparation_witnesses",
    }
