import hashlib
import json
from pathlib import Path

from rdkit import Chem, DataStructs

from reaction_reference.chemistry.structures import (
    canonical,
    digest,
    parse,
    parse_material,
    similarity,
)
from reaction_reference.domain.models import (
    Conditions,
    Material,
    Observation,
    ReactionRecord,
    SourceRef,
)
from reaction_reference.ports.sources import Candidate, CandidatePage


def import_native(row):
    """Adapt existing exported fields, preserving unknown outcomes and input roles."""
    if "source" in row and "materials" in row:
        return ReactionRecord.model_validate(row)
    record_id = str(row["id"])
    namespace = str(row.get("source_namespace") or row.get("source_type") or "patent")
    details = row.get("details") or {}
    if not isinstance(details, dict):
        raise ValueError("Source details must be an object")
    materials = []
    for role in ("product", "reactant", "reagent", "catalyst", "solvent"):
        entries = details.get(role + "s") or []
        structures = row.get(role + "_smiles") or []
        if not isinstance(structures, (list, tuple)) or any(
            not isinstance(s, str) or not s for s in structures
        ):
            raise ValueError("Source material structures must be arrays of nonempty SMILES strings")
        for i, smiles in enumerate(structures):
            compatible = []
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("smiles"):
                    continue
                try:
                    if canonical(entry["smiles"]) == canonical(smiles):
                        compatible.append(entry)
                except ValueError:
                    continue
            names = {entry.get("name") for entry in compatible}
            name = next(iter(names)) if len(names) == 1 else None
            materials.append(
                Material(
                    instance_id=f"{record_id}:{role}:{i}",
                    role=role,
                    smiles=smiles,
                    name=name,
                    actual_input=None,
                )
            )
    source = SourceRef(
        namespace=namespace,
        record_id=record_id,
        experiment_id=f"{namespace}:{row.get('document_id')}:{row.get('paragraph_nums')}:{row.get('paragraph_reaction_ordinal', record_id)}",
        document_id=str(row["document_id"]) if row.get("document_id") is not None else None,
        location=str(row.get("paragraph_nums") or ""),
    )
    observations = []
    # An array of extracted products alone is NOT a preparation witness.
    # Explicitly annotated outcomes can be added by the evidence importer.
    for material in materials:
        if material.role == "product":
            observations.append(Observation(product_instance_id=material.instance_id))
    return ReactionRecord(
        id=f"{namespace}:{record_id}",
        source=source,
        materials=materials,
        observations=observations,
        mapped_reaction_smiles=row.get("mapped_reaction_smiles"),
        reaction_smiles=row.get("reaction_smiles"),
        reaction_class=str(row["reaction_class"])
        if row.get("reaction_class") is not None
        else None,
        retro_template=row.get("reaction_center_r2"),
        conditions=Conditions(
            temperature_min_c=row.get("temperature_min_c"),
            temperature_max_c=row.get("temperature_max_c"),
            pressure_max_kpa=row.get("pressure_max_kpa"),
            duration_seconds=row.get("duration_max_seconds"),
            text=details.get("temperature_text"),
        ),
        raw={
            "source_record_hash": digest(row, 64),
            "source_locator": {
                key: row.get(key)
                for key in (
                    "id",
                    "source_namespace",
                    "document_id",
                    "paragraph_nums",
                    "paragraph_reaction_ordinal",
                )
            },
            "raw_details_retained_in_source": True,
        },
    )


class JsonlSource:
    """A bounded fixed dataset, with Pattern prefilter plus reference-mode selection."""

    max_selection_stage = 2
    hydration_requires_io = False
    selection_policy = "bounded_jsonl_pattern_core_then_hac_windows_similarity_order_then_full_markush_verification"

    def __init__(self, path, *, exhaustive=False, max_records=20000):
        self.path = Path(path)
        payload = self.path.read_bytes()
        if len(payload) > 256 * 1024 * 1024:
            raise ValueError(
                "Use an indexed source or explicit offline import for datasets above 256 MiB"
            )
        self.snapshot_id = "jsonl:" + hashlib.sha256(payload).hexdigest()
        self.issues = []
        self.exhaustive = exhaustive
        self.candidates = []
        self.records = []
        identities: dict[str, str] = {}
        conflicted_ids = set()
        lines = [line for line in payload.splitlines() if line.strip()]
        if len(lines) > max_records:
            raise ValueError("The bounded JSONL adapter record limit was exceeded")
        for number, line in enumerate(lines, 1):
            try:
                record = import_native(json.loads(line))
            except (ValueError, KeyError, TypeError) as exc:
                self.issues.append(
                    {"line": number, "code": "invalid_record", "reason": str(exc)[:300]}
                )
                continue
            fingerprint = digest(record.model_dump(), 64)
            if record.id in identities:
                if identities[record.id] != fingerprint:
                    conflicted_ids.add(record.id)
                    self.issues.append(
                        {"record_id": record.id, "code": "conflicting_record_identity"}
                    )
                continue
            identities[record.id] = fingerprint
            self.records.append(record)
            for material in record.materials:
                if material.role not in ("product", "reactant"):
                    continue
                try:
                    molecule = parse_material(material.smiles)
                    if len(Chem.GetMolFrags(molecule)) != 1:
                        raise ValueError("Material contains multiple unresolved graph components")
                except ValueError as exc:
                    self.issues.append(
                        {
                            "record_id": record.id,
                            "instance_id": material.instance_id,
                            "code": "invalid_or_ambiguous_structure",
                            "reason": str(exc),
                        }
                    )
                    continue
                sid = digest([canonical(molecule), material.role])
                self.candidates.append(
                    (Candidate(sid, material, record), molecule, Chem.PatternFingerprint(molecule))
                )
        self.records = [r for r in self.records if r.id not in conflicted_ids]
        self.candidates = [
            item for item in self.candidates if item[0].record.id not in conflicted_ids
        ]
        self._selection_cache = {}

    def candidate_page(self, family, role, cursor, limit, target_smiles, stage=0):
        key = (family.id, role, target_smiles, stage, self.exhaustive)
        if key not in self._selection_cache:
            query = Chem.MolFromSmarts(family.core_smarts)
            if query is None:
                raise ValueError("Invalid query")
            # Generic attributes/R constraints only make the full check more restrictive;
            # this fingerprint uses the connected necessary core, not the full target.
            pattern = Chem.PatternFingerprint(query)
            target = parse(target_smiles)
            target_hac = max(1, target.GetNumHeavyAtoms())
            selected = []
            for item, molecule, fingerprint in self.candidates:
                if item.material.role != role or not DataStructs.AllProbeBitsMatch(
                    pattern, fingerprint
                ):
                    continue
                if not self.exhaustive and family.layer != "fragment" and stage < 2:
                    # Explicit reference preference, never a chemical no-match claim.
                    bounds = (0.5, 1.6) if stage == 0 else (0.25, 3.0)
                    ratio = molecule.GetNumHeavyAtoms() / target_hac
                    if not bounds[0] <= ratio <= bounds[1]:
                        continue
                selected.append((item, similarity(target, molecule)))
            selected.sort(
                key=lambda x: (-x[1], x[0].structure_id, x[0].record.id, x[0].material.instance_id)
            )
            self._selection_cache[key] = [item for item, _ in selected]
        selected = self._selection_cache[key]
        items = selected[cursor : cursor + limit]
        done = cursor + len(items) >= len(selected)
        return CandidatePage(
            items,
            None if done else cursor + len(items),
            done,
            done and not self.issues,
            "fixed_dataset_scan"
            if self.exhaustive or family.layer == "fragment" or stage == 2
            else f"reference_hac_window_stage_{stage}",
        )

    def close(self):
        self._selection_cache.clear()

    def hydrate(self, record):
        return record


class PostgresSource:
    """Read-only existing schema. Indexed side candidates are individually verified.

    A nearest-neighbor pool is a bounded preference, not a safe substructure filter.
    The independent substructure cursor never sorts/counts the entire hit set.
    """

    hydration_requires_io = True
    selection_failure_fallback = True
    selection_policy = "optional_indexed_side_fp_knn_top512_then_independent_indexed_core_cursor; no_server_mass_window"
    lightweight_columns = (
        "id",
        "source_type",
        "source_namespace",
        "document_id",
        "paragraph_nums",
        "paragraph_reaction_ordinal",
        "product_smiles",
        "reactant_smiles",
        "reagent_smiles",
        "catalyst_smiles",
        "solvent_smiles",
        "reaction_smiles",
        "mapped_reaction_smiles",
        "reaction_class",
        "reaction_center_r2",
        "temperature_min_c",
        "temperature_max_c",
        "duration_max_seconds",
        "pressure_max_kpa",
    )

    def __init__(self, dsn, *, timeout_ms=1500):
        import psycopg
        from psycopg.rows import dict_row

        self.connection = psycopg.connect(
            dsn, connect_timeout=5, row_factory=dict_row, autocommit=True
        )
        self.issues = []
        self._details_columns = None
        self._cursors, self._rows, self._hydrated, self._knn = {}, {}, {}, {}
        try:
            self.connection.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            self.connection.execute(
                "SELECT set_config('statement_timeout', %s, true)", (str(timeout_ms),)
            )
            self.connection.execute("SELECT set_config('rdkit.morgan_fp_size', '2048', true)")
            self.connection.execute("SELECT set_config('rdkit.do_chiral_sss', 'false', true)")
            snapshot = self.connection.execute(
                "SELECT pg_current_snapshot()::text AS snapshot"
            ).fetchone()
            if snapshot is None:
                raise RuntimeError("Source snapshot unavailable")
            self.snapshot_id = "postgres-session:" + digest([snapshot["snapshot"], id(self)])
            rows = self.connection.execute("""
                SELECT pg_get_indexdef(i.indexrelid) AS indexdef
                FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname='reaction' AND t.relname='reactions'
                AND i.indisvalid AND i.indisready AND i.indpred IS NULL
            """).fetchall()
            self._indexes = [r["indexdef"] for r in rows]
            self._assert_index("products_mol")
            self.max_selection_stage = 1 if self._has_index("product_fp") else 0
        except Exception:
            self.connection.close()
            raise

    def _has_index(self, column):
        return any(
            column in definition and "USING gist" in definition for definition in self._indexes
        )

    def _assert_index(self, column):
        if not self._has_index(column):
            raise ValueError(f"Indexed source capability unavailable: GiST on {column} is required")

    def _items(self, rows, role):
        items = []
        for data in rows:
            try:
                record = import_native(data)
            except (ValueError, KeyError, TypeError) as exc:
                self.issues.append(
                    {
                        "record_id": str(data.get("id")),
                        "code": "invalid_record",
                        "reason": str(exc)[:300],
                    }
                )
                continue
            self._rows[record.id] = data
            for material in record.materials:
                if material.role != role:
                    continue
                try:
                    molecule = parse_material(material.smiles)
                    if len(Chem.GetMolFrags(molecule)) != 1:
                        raise ValueError("Ambiguous material components")
                except ValueError as exc:
                    self.issues.append(
                        {"record_id": record.id, "code": "invalid_structure", "reason": str(exc)}
                    )
                    continue
                items.append(Candidate(digest([canonical(molecule), role]), material, record))
        return items

    def candidate_page(self, family, role, cursor, limit, target_smiles, stage=0):
        from psycopg import sql

        column = "products_mol" if role == "product" else "reactants_mol"
        fp_column = "product_fp" if role == "product" else "reactant_fp"
        self._assert_index(column)
        projection = sql.SQL(",").join(sql.Identifier(c) for c in self.lightweight_columns)
        key = (family.id, role, stage)
        self.connection.execute("SAVEPOINT rr_query")
        try:
            nearest = (
                stage == 0
                and family.layer != "fragment"
                and family.relation != "strict"
                and self._has_index(fp_column)
            )
            if nearest:
                pool_key = (role, target_smiles)
                if pool_key not in self._knn:
                    query = sql.SQL("""
                        SELECT {projection} FROM reaction.reactions
                        WHERE {fp} IS NOT NULL
                        ORDER BY {fp} <%%> morganbv_fp(mol_from_smiles(%s::cstring),2)
                        LIMIT 512
                    """).format(projection=projection, fp=sql.Identifier(fp_column))
                    self._knn[pool_key] = self.connection.execute(
                        query, (target_smiles,)
                    ).fetchall()
                pool = self._knn[pool_key]
                rows = pool[cursor : cursor + limit]
                done = cursor + len(rows) >= len(pool)
                enumeration = "side_aggregate_fp_knn_top512_individual_graph_verification_required"
            else:
                if key not in self._cursors:
                    if cursor:
                        raise ValueError("Source cursor cannot be resumed outside its read session")
                    server = self.connection.cursor(name="rr_" + digest(key))
                    query = sql.SQL(
                        "SELECT {projection} FROM reaction.reactions WHERE {column} @> %s::qmol"
                    ).format(projection=projection, column=sql.Identifier(column))
                    server.execute(query, (family.core_smarts,))
                    self._cursors[key] = (server, 0)
                server, expected = self._cursors[key]
                if expected != cursor:
                    raise ValueError("Out-of-order source cursor")
                rows = server.fetchmany(limit)
                done = len(rows) < limit
                self._cursors[key] = (server, cursor + len(rows))
                enumeration = (
                    "indexed_side_substructure_session_cursor_without_global_sort_or_size_window"
                )
            items = self._items(rows, role)
            self.connection.execute("RELEASE SAVEPOINT rr_query")
        except Exception:
            self.connection.execute("ROLLBACK TO SAVEPOINT rr_query")
            self.connection.execute("RELEASE SAVEPOINT rr_query")
            self._cursors.pop(key, None)
            raise
        return CandidatePage(
            items, None if done else cursor + len(rows), done, done and not self.issues, enumeration
        )

    def hydrate(self, record):
        if record.id in self._hydrated:
            return self._hydrated[record.id]
        row = self._rows[record.id]
        self.connection.execute("SAVEPOINT rr_hydrate")
        try:
            result = import_native({**row, "details": self._fetch_details(row)})
            self.connection.execute("RELEASE SAVEPOINT rr_hydrate")
        except Exception:
            self.connection.execute("ROLLBACK TO SAVEPOINT rr_hydrate")
            self.connection.execute("RELEASE SAVEPOINT rr_hydrate")
            raise
        self._hydrated[record.id] = result
        return result

    def _fetch_details(self, row):
        from psycopg import sql

        if self._details_columns is None:
            self._details_columns = {
                r["column_name"]
                for r in self.connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='reaction' AND table_name='reaction_details'"
                ).fetchall()
            }
        columns = self._details_columns
        keys = (
            ["reaction_id"]
            if "reaction_id" in columns
            else [
                "source_type",
                "source_namespace",
                "document_id",
                "paragraph_nums",
                "paragraph_reaction_ordinal",
            ]
        )
        if not set(keys) <= columns:
            return {}
        values = [row["id"]] if keys == ["reaction_id"] else [row[k] for k in keys]
        if any(value is None for value in values):
            return {}
        condition = sql.SQL(" AND ").join(
            sql.SQL("{} = %s").format(sql.Identifier(key)) for key in keys
        )
        found = self.connection.execute(
            sql.SQL(
                "SELECT to_jsonb(d) AS data FROM reaction.reaction_details d WHERE {} LIMIT 1"
            ).format(condition),
            values,
        ).fetchone()
        return found["data"] if found else {}

    def close(self):
        try:
            self.connection.execute("ROLLBACK")
        finally:
            self.connection.close()
