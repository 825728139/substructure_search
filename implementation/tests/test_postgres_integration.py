"""真实 PostgreSQL/RDKit 集成回归；仅使用本机自动创建并清理的临时数据库。"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from reaction_reference.adapters.sources import PostgresSource
from reaction_reference.application.search import search
from reaction_reference.domain.models import QueryFamily, SearchRequest, Target


@pytest.fixture(scope="session")
def postgres_cluster():
    """使用本机二进制启动私有 Unix socket 测试库，退出时停止，不接受外部连接配置。"""
    executables = {name: shutil.which(name) for name in ("initdb", "pg_ctl", "pg_config")}
    if not all(executables.values()):
        pytest.skip("真实来源回归需要本机 PostgreSQL 与 RDKit 扩展")
    shared = subprocess.run(
        [executables["pg_config"], "--sharedir"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if not (Path(shared) / "extension/rdkit.control").is_file():
        pytest.skip("本机 PostgreSQL 未安装 RDKit 扩展")
    with tempfile.TemporaryDirectory(prefix="rr-pg-") as directory:
        root = Path(directory)
        data = root / "data"
        subprocess.run(
            [
                executables["initdb"],
                "-D",
                str(data),
                "--no-locale",
                "--encoding=UTF8",
                "--auth-local=trust",
                "--auth-host=reject",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            subprocess.run(
                [
                    executables["pg_ctl"],
                    "-D",
                    str(data),
                    "-l",
                    str(root / "server.log"),
                    "-o",
                    f"-k {root} -h '' -p 5432",
                    "-w",
                    "start",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            dsn = f"host={root} port=5432 dbname=postgres connect_timeout=3"
            with psycopg.connect(dsn, autocommit=True) as connection:
                connection.execute("CREATE EXTENSION rdkit")
            yield dsn
        finally:
            subprocess.run(
                [executables["pg_ctl"], "-D", str(data), "-m", "immediate", "-w", "stop"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )


@pytest.fixture
def indexed_source_dsn(postgres_cluster):
    """为每项测试重建临时反应表、化学索引和三条示例，字段与生产适配器投影一致。"""
    with psycopg.connect(postgres_cluster, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS reaction CASCADE")
        connection.execute("CREATE SCHEMA reaction")
        connection.execute("SET rdkit.morgan_fp_size = 2048")
        connection.execute("""
            CREATE TABLE reaction.reactions (
                id bigint PRIMARY KEY, source_type text DEFAULT 'test',
                source_namespace text DEFAULT 'integration', document_id text DEFAULT 'TEST',
                paragraph_nums text[] DEFAULT ARRAY['1'], paragraph_reaction_ordinal integer DEFAULT 1,
                product_smiles text[], reactant_smiles text[], reagent_smiles text[] DEFAULT '{}',
                catalyst_smiles text[] DEFAULT '{}', solvent_smiles text[] DEFAULT '{}',
                reaction_smiles text, mapped_reaction_smiles text, reaction_class text,
                reaction_center_r2 text, temperature_min_c real,
                temperature_max_c real, duration_max_seconds bigint,
                pressure_max_kpa real, products_mol mol, reactants_mol mol,
                product_fp bfp, reactant_fp bfp, final_score integer DEFAULT 12
            )
        """)
        connection.execute("""
            CREATE TABLE reaction.reaction_details (
                source_type text DEFAULT 'test', source_namespace text DEFAULT 'integration',
                document_id text DEFAULT 'TEST', paragraph_nums text[] DEFAULT ARRAY['1'],
                paragraph_reaction_ordinal integer DEFAULT 1, products jsonb, reactants jsonb,
                temperature_text text,
                PRIMARY KEY (source_type,source_namespace,document_id,paragraph_nums,paragraph_reaction_ordinal)
            )
        """)
        for number, product, reactant in [
            (1, "CCO", "CC=O"),
            (2, "CCN", "CCBr"),
            (3, "CCCO", "CCC=O"),
        ]:
            connection.execute(
                """
                INSERT INTO reaction.reactions
                (id,paragraph_reaction_ordinal,product_smiles,reactant_smiles,products_mol,reactants_mol,product_fp,reactant_fp)
                VALUES (%s,%s,%s,%s,%s::mol,%s::mol,morganbv_fp(%s::mol,2),morganbv_fp(%s::mol,2))
            """,
                (number, number, [product], [reactant], product, reactant, product, reactant),
            )
        connection.execute(
            "INSERT INTO reaction.reaction_details (products,reactants,temperature_text) VALUES (%s,%s,%s)",
            (Jsonb([{"smiles": "OCC", "name": "乙醇"}]), Jsonb([]), "室温"),
        )
        for column, operator in [
            ("products_mol", "gist_mol_ops"),
            ("reactants_mol", "gist_mol_ops"),
            ("product_fp", "gist_bfp_ops"),
            ("reactant_fp", "gist_bfp_ops"),
        ]:
            connection.execute(
                f"CREATE INDEX ON reaction.reactions USING gist ({column} {operator})"
            )
    return postgres_cluster


def carbon_family(*, layer="fragment", name="carbon"):
    """构造固定一个碳的家族，用于区分来源分页与应用层完整核验的职责。"""
    return QueryFamily(
        id=name,
        layer=layer,
        core_smarts="[#6]",
        target_atoms=[0],
        rule_id="integration",
        rule_version="1",
        description="真实来源集成测试",
    )


@pytest.mark.parametrize("column,value,name", [("products", True, None), ("reactants", 7, "乙醇")])
def test_malformed_optional_detail_container_keeps_other_details(
    indexed_source_dsn, column, value, name
):
    """异常材料详情容器不能使真实加载整体回退；其余材料名称和条件文本仍须保留。"""
    from psycopg import sql

    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute(
            sql.SQL("UPDATE reaction.reaction_details SET {}=%s").format(sql.Identifier(column)),
            (Jsonb(value),),
        )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        package = search(
            SearchRequest(target=Target(value="CCO")),
            source,
        )
        reference = next(r for r in package.results if r.target_requirements_satisfied)
        assert reference.material.name == name
        assert reference.record.conditions.text == "室温"
        assert not any(
            issue["code"] == "source_hydration_failed" for issue in package.source_issues
        )
        assert not reference.preparation_hit
    finally:
        source.close()


@pytest.mark.parametrize("role", ["product", "reactant"])
def test_indexed_cursor_pages_and_read_only_session(indexed_source_dsn, role):
    """真实服务端游标按页返回全部材料，严格只读事务拒绝写入。"""
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        cursor, items = 0, []
        while True:
            page = source.candidate_page(carbon_family(), role, cursor, 1, "CCO", stage=1)
            items.extend(page.items)
            if page.next_cursor is None:
                assert page.stream_exhausted and page.scope_complete
                break
            assert page.next_cursor > cursor
            cursor = page.next_cursor
        assert {item.record.id for item in items} == {
            "integration:1",
            "integration:2",
            "integration:3",
        }
        assert len(items) == 3 and all(item.material.role == role for item in items)
        assert not source.issues
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            source.connection.execute("DELETE FROM reaction.reactions")
    finally:
        source.close()


@pytest.mark.parametrize("role", ["product", "reactant"])
@pytest.mark.parametrize("failure", [None, "cursor_order", "later_page_processing"])
def test_failed_page_closes_existing_cursor_and_allows_restart(
    indexed_source_dsn, monkeypatch, role, failure
):
    """后续页失败时释放此前已存在的服务端游标；同一家族可重新从零分页，正常续页不受影响。"""
    source = PostgresSource(indexed_source_dsn, table="reactions")
    family = carbon_family(name="retry-existing-cursor")
    try:
        first = source.candidate_page(family, role, 0, 1, "CCO", stage=1)
        assert first.next_cursor == 1
        names = source.connection.execute(
            "SELECT name FROM pg_cursors WHERE name LIKE 'rr_%'"
        ).fetchall()
        assert len(names) == 1
        remaining = []
        if failure:
            with monkeypatch.context() as fault:
                if failure == "later_page_processing":

                    def fail_processing(*_):
                        """在真实 FETCH 已完成后模拟材料处理异常。"""
                        raise RuntimeError("模拟后续页材料处理失败")

                    fault.setattr(source, "_items", fail_processing)
                with pytest.raises(ValueError if failure == "cursor_order" else RuntimeError):
                    source.candidate_page(
                        family, role, 2 if failure == "cursor_order" else 1, 1, "CCO", stage=1
                    )
            remaining = source.connection.execute(
                "SELECT name FROM pg_cursors WHERE name=%s", (names[0]["name"],)
            ).fetchall()
            items, cursor = [], 0
        else:
            items, cursor = list(first.items), first.next_cursor
        assert source.connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
        while True:
            page = source.candidate_page(family, role, cursor, 1, "CCO", stage=1)
            items.extend(page.items)
            if page.next_cursor is None:
                assert page.stream_exhausted and page.scope_complete
                break
            assert page.next_cursor > cursor
            cursor = page.next_cursor
        assert not remaining
        assert len(items) == 3
        assert {item.record.id for item in items} == {
            "integration:1",
            "integration:2",
            "integration:3",
        }
    finally:
        source.close()


def test_first_page_processing_failure_does_not_poison_cursor_cleanup(
    indexed_source_dsn, monkeypatch
):
    """第一页处理失败会使新游标随保存点回滚消失，重复清理也不能让连接陷入事务错误。"""
    source = PostgresSource(indexed_source_dsn, table="reactions")
    family = carbon_family(name="retry-first-page")
    try:
        with monkeypatch.context() as fault:

            def fail_processing(*_):
                """在首个真实 FETCH 后抛错，使新游标在回滚时被服务器自动删除。"""
                raise RuntimeError("模拟首个页面处理失败")

            fault.setattr(source, "_items", fail_processing)
            with pytest.raises(RuntimeError, match="模拟首个页面处理失败"):
                source.candidate_page(family, "product", 0, 1, "CCO", stage=1)
        assert not source.connection.execute(
            "SELECT name FROM pg_cursors WHERE name LIKE 'rr_%'"
        ).fetchall()
        assert source.connection.execute("SELECT 1 AS value").fetchone()["value"] == 1
        page = source.candidate_page(family, "product", 0, 10, "CCO", stage=1)
        assert page.stream_exhausted and page.scope_complete and len(page.items) == 3
    finally:
        source.close()


@pytest.mark.parametrize("details_by_id", [False, True])
def test_knn_selection_and_detail_hydration(indexed_source_dsn, details_by_id):
    """真实指纹近邻首项命中乙醇，详情名称通过结构对应，并可切换独立子结构通道。"""
    if details_by_id:
        with psycopg.connect(indexed_source_dsn, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE reaction.reaction_details ADD COLUMN reaction_id bigint"
            )
            connection.execute("UPDATE reaction.reaction_details SET reaction_id=1")
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        family = carbon_family(layer="core")
        nearest = source.candidate_page(family, "product", 0, 1, "CCO")
        assert nearest.items[0].record.id == "integration:1"
        assert "knn" in nearest.enumeration_kind
        hydrated = source.hydrate(nearest.items[0].record)
        assert hydrated.materials[0].name == "乙醇"
        assert hydrated.materials[0].instance_id == nearest.items[0].material.instance_id
        assert hydrated.conditions.text == "室温"
        direct = source.candidate_page(family, "product", 0, 10, "CCO", stage=1)
        assert len(direct.items) == 3 and direct.scope_complete
    finally:
        source.close()


def test_query_timeout_preserves_independent_query(indexed_source_dsn):
    """真正的表锁等待触发查询超时，回滚保存点后另一个家族仍可使用同一来源会话。"""
    source = PostgresSource(indexed_source_dsn, table="reactions", timeout_ms=100)
    try:
        with psycopg.connect(indexed_source_dsn) as writer:
            writer.execute("LOCK TABLE reaction.reactions IN ACCESS EXCLUSIVE MODE")
            with pytest.raises(psycopg.errors.QueryCanceled):
                source.candidate_page(carbon_family(name="timeout"), "product", 0, 10, "CCO")
            writer.rollback()
        # 锁等待仍用 100ms；后续只验证连接恢复，不把首次加载或机器调度耗时当作事务故障。
        source.connection.execute("SELECT set_config('statement_timeout', '1500ms', true)")
        page = source.candidate_page(carbon_family(name="after-timeout"), "product", 0, 10, "CCO")
        assert len(page.items) == 3
    finally:
        source.close()


def test_repeatable_read_keeps_material_fields_frozen(indexed_source_dsn):
    """来源建立快照后其他会话更新原行，本次查询和详情仍必须对应旧材料结构。"""
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
            writer.execute("UPDATE reaction.reactions SET product_smiles=ARRAY['CCN'] WHERE id=1")
        page = source.candidate_page(carbon_family(), "product", 0, 10, "CCO")
        item = next(item for item in page.items if item.record.id == "integration:1")
        assert item.material.smiles == "CCO"
        assert source.hydrate(item.record).materials[0].name == "乙醇"
    finally:
        source.close()


def test_sql_row_paging_survives_dirty_and_multiple_materials(indexed_source_dsn):
    """SQL 游标按行推进，脏行不提前终结流，多产物行也不能跳过后一行。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute("UPDATE reaction.reactions SET product_smiles=ARRAY['invalid('] WHERE id=1")
        writer.execute(
            "UPDATE reaction.reactions SET product_smiles=ARRAY['CCN','CCO'], products_mol='CCN.CCO'::mol WHERE id=2"
        )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        cursor, items, empty_pages = 0, [], 0
        while True:
            page = source.candidate_page(carbon_family(), "product", cursor, 1, "CCO")
            items.extend(page.items)
            empty_pages += not page.items and page.next_cursor is not None
            if page.next_cursor is None:
                assert not page.scope_complete
                break
            cursor = page.next_cursor
        assert empty_pages == 1
        assert len(items) == 3
        assert {item.record.id for item in items} == {"integration:2", "integration:3"}
        assert len({item.material.instance_id for item in items}) == 3
    finally:
        source.close()


def test_indexed_source_runs_the_full_search_pipeline(indexed_source_dsn):
    """真实 PG 候选、结构核验和详情共同生成资料包，产品字段不升级成制备证据。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute(
            "UPDATE reaction.reactions SET temperature_min_c=20,temperature_max_c=25,duration_max_seconds=3600 WHERE id=1"
        )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        package = search(
            SearchRequest(target=Target(value="CCO"), budget={"max_tasks": 100}), source
        )
    finally:
        source.close()
    exact = [
        ref
        for ref in package.results
        if ref.target_requirements_satisfied and ref.material.role == "product"
    ]
    assert len(exact) == 1
    assert exact[0].material.name == "乙醇"
    assert exact[0].record.conditions.duration_seconds == 3600
    assert not exact[0].preparation_hit and not package.source_issues
    assert package.coverage_state == "partial"


@pytest.mark.parametrize(
    "column,value",
    [
        ("source_type", ""),
        ("source_namespace", ""),
        ("document_id", " "),
        ("paragraph_nums", []),
        ("paragraph_nums", [""]),
        ("paragraph_nums", [None]),
    ],
)
def test_incomplete_source_keys_do_not_attach_unidentified_details(
    indexed_source_dsn, column, value
):
    """两侧同为空定位不构成可靠实验关联，不能把未知归属的详情接到反应上。"""
    from psycopg import sql

    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute(
            sql.SQL("UPDATE reaction.reactions SET {}=%s WHERE id=1").format(
                sql.Identifier(column)
            ),
            (value,),
        )
        writer.execute(
            sql.SQL("UPDATE reaction.reaction_details SET {}=%s").format(sql.Identifier(column)),
            (value,),
        )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        page = source.candidate_page(carbon_family(), "product", 0, 10, "CCO")
        item = next(item for item in page.items if item.record.source.record_id == "1")
        hydrated = source.hydrate(item.record)
        assert hydrated.materials[0].name is None
        assert hydrated.conditions.text is None
    finally:
        source.close()


def test_direct_reaction_id_link_does_not_require_paragraph_locator(indexed_source_dsn):
    """明确反应 ID 已建立可靠关联时，段落定位缺失不应阻止读取对应详情。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute("ALTER TABLE reaction.reaction_details ADD COLUMN reaction_id bigint")
        writer.execute(
            "UPDATE reaction.reaction_details SET reaction_id=1,document_id='',paragraph_nums=ARRAY[]::text[]"
        )
        writer.execute(
            "UPDATE reaction.reactions SET document_id='',paragraph_nums=ARRAY[]::text[] WHERE id=1"
        )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        page = source.candidate_page(carbon_family(), "product", 0, 10, "CCO")
        item = next(item for item in page.items if item.record.source.record_id == "1")
        assert source.hydrate(item.record).materials[0].name == "乙醇"
    finally:
        source.close()


@pytest.mark.parametrize("template", ["[CH2:1][OH:2]>>[CH:1]=[O:2]", None])
def test_bounded_export_preserves_source_replay_template(indexed_source_dsn, tmp_path, template):
    """有限导出再加载后必须保留在线来源的回放模板；缺失模板仍保持空值。"""
    from reaction_reference.adapters.export import export_sample
    from reaction_reference.adapters.sources import JsonlSource
    from reaction_reference.analogs.transfer import source_rules

    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute(
            "UPDATE reaction.reactions SET reaction_center_r2=%s WHERE id=1", (template,)
        )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        page = source.candidate_page(carbon_family(), "product", 0, 10, "CCO")
        online = next(item.record for item in page.items if item.record.source.record_id == "1")
        assert online.retro_template == template
        output = tmp_path / "sample.jsonl"
        exported = export_sample(indexed_source_dsn, output, limit=1)
        assert exported["records"] == 1 and exported["last_id"] == 1
        offline = JsonlSource(output)
        try:
            assert not offline.issues
            restored = offline.records[0]
            assert restored.retro_template == online.retro_template
            assert [rule["id"] for rule in source_rules(restored)] == [
                rule["id"] for rule in source_rules(online)
            ]
        finally:
            offline.close()
    finally:
        source.close()


@pytest.mark.parametrize("link", ["reaction_id", "source_locator"])
def test_ambiguous_details_are_not_arbitrarily_attached(indexed_source_dsn, link):
    """详情关联命中多行时不能任取其一；事务继续可用，检索保留原始轻量参考。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        if link == "reaction_id":
            writer.execute("ALTER TABLE reaction.reaction_details ADD COLUMN reaction_id bigint")
            writer.execute("UPDATE reaction.reaction_details SET reaction_id=1")
            writer.execute(
                "INSERT INTO reaction.reaction_details "
                "(paragraph_reaction_ordinal,reaction_id,products,temperature_text) "
                "VALUES (99,1,%s,'另一条温度记录')",
                (Jsonb([{"smiles": "CCO", "name": "另一个名称"}]),),
            )
        else:
            writer.execute(
                "ALTER TABLE reaction.reaction_details DROP CONSTRAINT reaction_details_pkey"
            )
            writer.execute(
                "INSERT INTO reaction.reaction_details (products,temperature_text) "
                "VALUES (%s,'另一条温度记录')",
                (Jsonb([{"smiles": "CCO", "name": "另一个名称"}]),),
            )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        page = source.candidate_page(carbon_family(), "product", 0, 10, "CCO")
        record = next(item.record for item in page.items if item.record.source.record_id == "1")
        with pytest.raises(ValueError, match="Ambiguous"):
            source.hydrate(record)
        assert record.id not in source._hydrated
        assert source.connection.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        assert any(issue["code"] == "ambiguous_reaction_details" for issue in source.issues)
    finally:
        source.close()
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        package = search(
            SearchRequest(
                target=Target(value="CCO"),
                options={"include_usage": False, "include_proposals": False},
                budget={"max_tasks": 100},
            ),
            source,
        )
        exact = next(
            reference for reference in package.results if reference.target_requirements_satisfied
        )
        assert exact.material.name is None and exact.record.conditions.text is None
        assert package.coverage_state == "partial"
        assert any(issue["code"] == "ambiguous_reaction_details" for issue in package.source_issues)
        assert any(issue["code"] == "source_hydration_failed" for issue in package.source_issues)
    finally:
        source.close()


def test_indexed_and_jsonl_sources_agree_after_full_family_verification(
    indexed_source_dsn, tmp_path
):
    """同一结构集经过不同来源预筛和分页后，完整核验应保留相同的具体产物。"""
    import json

    from reaction_reference.adapters.sources import JsonlSource
    from reaction_reference.chemistry.markush import match_family
    from reaction_reference.chemistry.structures import canonical, parse
    from reaction_reference.retrieval.planner import initial_families

    examples = [
        "CCO",
        "CC(C)O",
        "CCN",
        "CC(=O)NCC",
        "C[C@H](O)CC",
        "C/C=C/C(=O)N",
        "[2H]OC(C)C",
        "C[13CH2]CO",
        "[O-][N+](=O)c1ccccc1",
        "c1ccc2ccccc2c1",
        "C1CCC2(CC1)CCCC2",
        "C1CC2CCC1C2",
    ]
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute("DELETE FROM reaction.reactions")
        for number, smiles in enumerate(examples, 1):
            writer.execute(
                "INSERT INTO reaction.reactions "
                "(id,paragraph_reaction_ordinal,product_smiles,products_mol) "
                "VALUES (%s,%s,%s,%s::mol)",
                (number, number, [smiles], smiles),
            )
        projection = ",".join(PostgresSource.lightweight_columns)
        rows = writer.execute(
            "SELECT " + projection + " FROM reaction.reactions ORDER BY id"
        ).fetchall()
    path = tmp_path / "equivalent.jsonl"
    path.write_text(
        "".join(
            json.dumps(dict(zip(PostgresSource.lightweight_columns, row, strict=True))) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    def verified_ids(source, family, target, stage=0):
        """逐页核验所有候选，用实例身份归并；空页也必须遵循来源游标继续读取。"""
        cursor, identities = 0, set()
        while True:
            page = source.candidate_page(
                family, "product", cursor, 2, canonical(target), stage=stage
            )
            for item in page.items:
                result = match_family(
                    family,
                    parse(item.material.smiles),
                    target,
                    item.structure_id,
                    max_mappings=2048,
                )
                assert result.enumeration_complete
                if result.state == "match":
                    identities.add((item.record.id, item.material.instance_id))
            if page.next_cursor is None:
                return identities
            assert page.next_cursor > cursor
            cursor = page.next_cursor

    offline = JsonlSource(path, exhaustive=True)
    try:
        for number, smiles in enumerate(examples, 1):
            target = parse(smiles, target=True)
            indexed = PostgresSource(indexed_source_dsn, table="reactions")
            try:
                for original in initial_families(target):
                    # 本例比较完整候选流，禁用首阶段 KNN，避免把有界初选当成完整召回。
                    family = original.model_copy(update={"layer": "fragment"})
                    expected = verified_ids(offline, family, target)
                    actual = verified_ids(indexed, family, target, stage=1)
                    assert actual == expected, (smiles, original.rule_id)
                    assert (f"integration:{number}", f"{number}:product:0") in actual
            finally:
                indexed.close()
        assert not offline.issues
    finally:
        offline.close()


@pytest.mark.parametrize("overlay", ["malformed", "duplicate", "missing", "empty"])
def test_overlay_initialization_releases_real_source_connection(
    indexed_source_dsn, tmp_path, overlay, monkeypatch
):
    """审核初始化失败时，即使保留异常回溯，底层只读会话也须立即释放。"""
    import json
    import time

    from psycopg.conninfo import make_conninfo

    from reaction_reference import bootstrap
    from reaction_reference.settings import Settings

    path = tmp_path / "review.jsonl"
    if overlay == "malformed":
        path.write_text("{broken\n", encoding="utf-8")
    elif overlay == "duplicate":
        row = {
            "record_id": "integration:1",
            "expected_source_hash": "a" * 64,
            "reviewer": "资源清理测试",
            "reviewed_at": "2026-10-30",
        }
        path.write_text((json.dumps(row) + "\n") * 2, encoding="utf-8")
    elif overlay == "empty":
        path.write_text("", encoding="utf-8")
    application_name = "rr-overlay-connection-review"
    settings = Settings(
        source_kind="postgres",
        postgres_table="reactions",
        postgres_dsn=make_conninfo(indexed_source_dsn, application_name=application_name),
        evidence_path=path,
        store_path=tmp_path / "runs",
    )
    opened = []
    constructor = bootstrap.PostgresSource

    def capture_source(*args, **kwargs):
        """保留真实来源对象以检查主动关闭，避免依赖对象被回收时的自动清理。"""
        source = constructor(*args, **kwargs)
        opened.append(source)
        return source

    monkeypatch.setattr(bootstrap, "PostgresSource", capture_source)
    with psycopg.connect(indexed_source_dsn, autocommit=True) as observer:

        def connections():
            """通过独立观察会话检查目标应用名是否仍持有真实数据库连接。"""
            return observer.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE application_name=%s",
                (application_name,),
            ).fetchone()[0]

        assert connections() == 0
        if overlay == "empty":
            source = bootstrap.open_source(settings)
            try:
                assert connections() == 1
                assert not opened[0].connection.closed
            finally:
                source.close()
        else:
            expected = FileNotFoundError if overlay == "missing" else ValueError
            with pytest.raises(expected) as failure:
                bootstrap.open_source(settings)
            assert failure.value.__traceback__ is not None
        assert len(opened) == 1 and opened[0].connection.closed
        # 客户端已经同步关闭；服务端移除会话条目允许有短暂的进程退出延迟。
        deadline = time.monotonic() + 2
        while connections():
            assert time.monotonic() < deadline, "审核来源连接关闭后仍残留数据库会话"
            time.sleep(0.01)


@pytest.mark.parametrize("overlay", ["missing", "malformed"])
@pytest.mark.parametrize("terminate_backend", [False, True])
def test_overlay_failure_keeps_original_error_when_real_connection_cleanup_fails(
    indexed_source_dsn, tmp_path, monkeypatch, overlay, terminate_backend
):
    """审核初始化失败且真实连接关闭也报错时，仍返回审核原错并释放客户端与服务器会话。"""
    import time

    from pydantic import ValidationError

    from reaction_reference import bootstrap
    from reaction_reference.settings import Settings

    path = tmp_path / "review.jsonl"
    if overlay == "malformed":
        path.write_text("{broken\n", encoding="utf-8")
    settings = Settings(
        source_kind="postgres",
        postgres_table="reactions",
        postgres_dsn=indexed_source_dsn,
        evidence_path=path,
    )
    constructor = bootstrap.PostgresSource
    opened, pids, cleanup_errors = [], [], []
    try:
        with psycopg.connect(indexed_source_dsn, autocommit=True) as observer:

            def capture_source(*args, **kwargs):
                """建立真实来源，按场景终止本测试后端，并记录真实关闭过程中的驱动异常。"""
                source = constructor(*args, **kwargs)
                opened.append(source)
                pids.append(source.connection.info.backend_pid)
                close = source.close

                def record_close():
                    """调用真实关闭逻辑，保留驱动异常以证明关闭故障确实发生。"""
                    try:
                        close()
                    except psycopg.Error as error:
                        cleanup_errors.append(error)
                        raise

                monkeypatch.setattr(source, "close", record_close)
                if terminate_backend:
                    assert observer.execute(
                        "SELECT pg_terminate_backend(%s, 1000)",
                        (pids[-1],),
                    ).fetchone()[0]
                return source

            monkeypatch.setattr(bootstrap, "PostgresSource", capture_source)
            expected = FileNotFoundError if overlay == "missing" else ValidationError
            with pytest.raises(expected) as failure:
                bootstrap.open_source(settings)
            if overlay == "missing":
                assert failure.value.filename == str(path)
            else:
                assert failure.value.errors()[0]["type"] == "json_invalid"
            assert len(opened) == 1 and opened[0].connection.closed
            assert len(cleanup_errors) == int(terminate_backend)
            pid = pids[0]
            deadline = time.monotonic() + 2
            while observer.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE pid=%s", (pid,)
            ).fetchone()[0]:
                assert time.monotonic() < deadline
                time.sleep(0.01)
    finally:
        for source in opened:
            source.connection.close()


@pytest.mark.parametrize("role", ["product", "reactant"])
@pytest.mark.parametrize("mode", ["knn", "core_fallback", "fragment", "strict"])
def test_quality_score_gate_applies_to_every_database_recall(indexed_source_dsn, role, mode):
    """所有数据库召回通道排除低分与未知分数，边界十二分可命中且分页不跳漏。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute("SET rdkit.morgan_fp_size=2048")
        writer.execute("DELETE FROM reaction.reactions")
        for number, score in enumerate([None, 0, 11, 12, 13], 1):
            writer.execute(
                """
                INSERT INTO reaction.reactions
                (id,final_score,product_smiles,reactant_smiles,products_mol,reactants_mol,
                 product_fp,reactant_fp)
                VALUES (%s,%s,ARRAY['CCO'],ARRAY['CCO'],'CCO'::mol,'CCO'::mol,
                        morganbv_fp('CCO'::mol,2),morganbv_fp('CCO'::mol,2))
                """,
                (number, score),
            )
    family = carbon_family(layer="fragment" if mode == "fragment" else "whole")
    if mode == "strict":
        family = family.model_copy(update={"relation": "strict"})
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        cursor, found = 0, []
        while True:
            page = source.candidate_page(
                family, role, cursor, 1, "CCO", stage=1 if mode == "core_fallback" else 0
            )
            found.extend(item.record.id for item in page.items)
            if page.next_cursor is None:
                assert page.stream_exhausted and page.scope_complete
                break
            cursor = page.next_cursor
        assert sorted(found) == ["integration:4", "integration:5"]
        assert "final_score_ge_12" in source.selection_policy
    finally:
        source.close()


@pytest.mark.parametrize("role", ["product", "reactant"])
def test_quality_filter_runs_before_knn_pool_limit(indexed_source_dsn, role):
    """六百个低分完全相同结构不能占满近邻池，合格但相似度较低的先例仍须被召回。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute("SET rdkit.morgan_fp_size=2048")
        writer.execute("DELETE FROM reaction.reactions")
        writer.execute("""
            INSERT INTO reaction.reactions
            (id,final_score,product_smiles,reactant_smiles,products_mol,reactants_mol,
             product_fp,reactant_fp)
            SELECT n,11,ARRAY['CCO'],ARRAY['CCO'],'CCO'::mol,'CCO'::mol,
                   morganbv_fp('CCO'::mol,2),morganbv_fp('CCO'::mol,2)
            FROM generate_series(1,600) n
        """)
        writer.execute("""
            INSERT INTO reaction.reactions
            (id,final_score,product_smiles,reactant_smiles,products_mol,reactants_mol,
             product_fp,reactant_fp)
            VALUES (601,12,ARRAY['CCCO'],ARRAY['CCCO'],'CCCO'::mol,'CCCO'::mol,
                    morganbv_fp('CCCO'::mol,2),morganbv_fp('CCCO'::mol,2))
        """)
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        page = source.candidate_page(carbon_family(layer="whole"), role, 0, 1000, "CCO")
        assert [item.record.id for item in page.items] == ["integration:601"]
        assert page.next_cursor is None and page.stream_exhausted
    finally:
        source.close()


@pytest.fixture
def v3_source_dsn(indexed_source_dsn):
    """在私有测试库建去重组和真实来源；低分代表、高分并列及无合格来源均有覆盖。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute("SET rdkit.morgan_fp_size=2048")
        writer.execute("CREATE TABLE reaction.reaction_v2 (LIKE reaction.reactions INCLUDING ALL)")
        writer.execute("INSERT INTO reaction.reaction_v2 SELECT * FROM reaction.reactions")
        writer.execute("CREATE TABLE reaction.reaction_v3 (LIKE reaction.reactions INCLUDING ALL)")
        writer.execute("ALTER TABLE reaction.reaction_v3 ADD COLUMN detail_count bigint DEFAULT 1")
        writer.execute("INSERT INTO reaction.reaction_v3 SELECT r.*,1 FROM reaction.reactions r")
        writer.execute(
            "UPDATE reaction.reaction_v3 SET reaction_smiles='CC=O>>CCO',final_score=17,detail_count=4 WHERE id=1"
        )
        writer.execute(
            "UPDATE reaction.reaction_v2 SET reaction_smiles='CC=O>>CCO',final_score=10,temperature_max_c=999 WHERE id=1"
        )
        writer.execute("UPDATE reaction.reaction_v3 SET reaction_smiles='CCBr>>CCN' WHERE id=2")
        writer.execute("UPDATE reaction.reaction_v2 SET reaction_smiles='CCBr>>CCN' WHERE id=2")
        writer.execute(
            "UPDATE reaction.reaction_v3 SET reaction_smiles='CCC=O>>CCCO',final_score=15 WHERE id=3"
        )
        writer.execute(
            "UPDATE reaction.reaction_v2 SET reaction_smiles='CCC=O>>CCCO',final_score=NULL WHERE id=3"
        )
        writer.execute("""
            CREATE TABLE reaction.reaction_v3_sources (
                reaction_v3_id bigint, source_reaction_id bigint PRIMARY KEY
            )
        """)
        writer.execute("INSERT INTO reaction.reaction_v3_sources VALUES (1,1),(2,2),(3,3)")
        for number, score in [(10, 17), (11, 17), (12, 12)]:
            writer.execute(
                """
                INSERT INTO reaction.reaction_v2
                (id,source_namespace,document_id,paragraph_reaction_ordinal,product_smiles,
                 reactant_smiles,reagent_smiles,catalyst_smiles,solvent_smiles,
                 reaction_smiles,mapped_reaction_smiles,reaction_center_r2,
                 temperature_max_c,duration_max_seconds,pressure_max_kpa,final_score)
                VALUES (%s,'chosen',%s,%s,ARRAY['CCO'],ARRAY['CC=O'],ARRAY['[H][H]'],
                        ARRAY['[Pd]'],ARRAY['CO'],'CC=O>>CCO',
                        '[CH3:1][CH:2]=[O:3]>>[CH3:1][CH2:2][OH:3]',
                        '[C:1][C:2][O:3]>>[C:1][C:2]=[O:3]',25,3600,101,%s)
            """,
                (number, f"GOOD{number}", number, score),
            )
            writer.execute("INSERT INTO reaction.reaction_v3_sources VALUES (1,%s)", (number,))
            writer.execute(
                """
                INSERT INTO reaction.reaction_details
                (source_namespace,document_id,paragraph_reaction_ordinal,products,reactants,temperature_text)
                VALUES ('chosen',%s,%s,%s,'[]','合格来源的温度原文')
            """,
                (f"GOOD{number}", number, Jsonb([{"smiles": "CCO", "name": f"来源{number}产物"}])),
            )
        writer.execute("""
            CREATE VIEW reaction.reaction_v3_source_scores AS
            SELECT l.reaction_v3_id,l.source_reaction_id,v.final_score,
                   v.final_score=g.final_score AS is_highest_score
            FROM reaction.reaction_v3_sources l JOIN reaction.reaction_v2 v ON v.id=l.source_reaction_id
            JOIN reaction.reaction_v3 g ON g.id=l.reaction_v3_id
        """)
        writer.execute("""
            CREATE VIEW reaction.reaction_v3_details AS
            SELECT l.reaction_v3_id,l.source_reaction_id,d.*
            FROM reaction.reaction_v3_sources l JOIN reaction.reaction_v2 v ON v.id=l.source_reaction_id
            JOIN reaction.reaction_details d
            USING(source_type,source_namespace,document_id,paragraph_nums,paragraph_reaction_ordinal)
        """)
        # 用真实生产形式的非空部分GiST覆盖反应物两个通道。
        for row in writer.execute(
            "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='reaction' AND tablename='reaction_v3'"
        ):
            if "USING gist (reactant" in row[1]:
                from psycopg import sql

                writer.execute(sql.SQL("DROP INDEX reaction.{}").format(sql.Identifier(row[0])))
        writer.execute(
            "CREATE INDEX ON reaction.reaction_v3 USING gist (reactants_mol) WHERE reactants_mol IS NOT NULL"
        )
        writer.execute(
            "CREATE INDEX ON reaction.reaction_v3 USING gist (reactant_fp) WHERE reactant_fp IS NOT NULL"
        )
    return indexed_source_dsn


@pytest.mark.parametrize("role", ["product", "reactant"])
@pytest.mark.parametrize("mode", ["knn", "fragment", "strict", "core_fallback"])
def test_v3_selects_qualified_source_before_matching_and_details(v3_source_dsn, role, mode):
    """所有召回通道使用合格实验身份和事实；低分代表、并列其他来源和失效组不混入。"""
    from reaction_reference.bootstrap import open_source
    from reaction_reference.settings import Settings

    settings = Settings(source_kind="postgres", postgres_dsn=v3_source_dsn)
    assert settings.worker_config()["postgres_table"] == "reaction_v3"
    source = open_source(settings)
    try:
        family = carbon_family(layer="fragment" if mode == "fragment" else "whole")
        if mode == "strict":
            family = family.model_copy(update={"relation": "strict"})
        cursor, items = 0, []
        while True:
            page = source.candidate_page(
                family, role, cursor, 1, "CCO", stage=1 if mode == "core_fallback" else 0
            )
            items.extend(page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        assert {i.record.id for i in items} == {"chosen:10", "integration:2"}
        selected = next(i for i in items if i.record.id == "chosen:10")
        assert selected.record.source.document_id == "GOOD10"
        assert selected.record.conditions.temperature_max_c == 25
        assert selected.record.conditions.duration_seconds == 3600
        assert selected.record.conditions.pressure_max_kpa == 101
        assert selected.record.mapped_reaction_smiles == "[CH3:1][CH:2]=[O:3]>>[CH3:1][CH2:2][OH:3]"
        assert selected.record.retro_template == "[C:1][C:2][O:3]>>[C:1][C:2]=[O:3]"
        assert [m.smiles for m in selected.record.materials if m.role == "catalyst"] == ["[Pd]"]
        metadata = selected.record.raw["dedup_source_selection"]
        assert metadata["group_id"] == 1 and metadata["group_max_score"] == 17
        assert metadata["source_reaction_id"] == 10 and metadata["source_final_score"] == 17
        assert metadata["group_source_count"] == 4 and metadata["other_sources_evaluated"] is False
        hydrated = source.hydrate(selected.record)
        assert hydrated.id == selected.record.id
        assert [m.instance_id for m in hydrated.materials] == [
            m.instance_id for m in selected.record.materials
        ]
        assert hydrated.conditions.text == "合格来源的温度原文"
        assert next(m for m in hydrated.materials if m.role == "product").name == "来源10产物"
        assert (
            source.connection.execute(
                "SELECT count(*) AS n FROM reaction.reaction_v3_source_scores WHERE reaction_v3_id=1"
            ).fetchone()["n"]
            == 4
        )
        assert any(i["code"] == "no_qualified_group_source" for i in source.issues)
        assert not page.scope_complete
    finally:
        source.close()


def test_v3_pipeline_matches_selected_material_order_and_keeps_source_on_detail_failure(
    v3_source_dsn,
):
    """端到端匹配按所选来源材料顺序；详情失败时仍只保留该合格来源的图事实。"""
    with psycopg.connect(v3_source_dsn, autocommit=True) as writer:
        writer.execute(
            "UPDATE reaction.reaction_v3 SET product_smiles=ARRAY['CCO','CCN'],products_mol='CCO.CCN'::mol,reaction_smiles='CC=O>>CCN.CCO' WHERE id=1"
        )
        writer.execute(
            "UPDATE reaction.reaction_v2 SET product_smiles=ARRAY['CCN','OCC'],reaction_smiles='CC=O>>CCN.CCO' WHERE id IN (10,11,12)"
        )
        writer.execute(
            "CREATE TABLE reaction.bad_details AS SELECT * FROM reaction.reaction_v3_details"
        )
        writer.execute(
            "UPDATE reaction.bad_details SET document_id='WRONG' WHERE source_reaction_id=10"
        )
        writer.execute(
            "CREATE OR REPLACE VIEW reaction.reaction_v3_details AS SELECT * FROM reaction.bad_details"
        )
    source = PostgresSource(v3_source_dsn)
    try:
        package = search(
            SearchRequest(
                target=Target(value="CCO"),
                budget={"max_tasks": 100},
                options={"include_proposals": False, "include_usage": False},
            ),
            source,
        )
        refs = [
            r
            for r in package.results
            if r.record.id == "chosen:10" and r.target_requirements_satisfied
        ]
        assert refs
        for ref in refs:
            assert ref.material.smiles == "OCC" and ref.material.instance_id == "10:product:1"
            assert ref.record.source.document_id == "GOOD10"
            assert (
                ref.record.conditions.temperature_max_c == 25 and ref.record.conditions.text is None
            )
            assert ref.record.raw["dedup_source_selection"]["source_final_score"] == 17
        assert any(i["code"] == "source_hydration_failed" for i in package.source_issues)
        assert source.connection.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
    finally:
        source.close()


def test_v3_missing_views_never_falls_back_to_old_table(v3_source_dsn):
    """默认v3依赖缺失应显式报错，不能悄悄读取仍存在的旧反应表。"""
    with psycopg.connect(v3_source_dsn, autocommit=True) as writer:
        writer.execute("DROP VIEW reaction.reaction_v3_source_scores")
    with pytest.raises(ValueError, match="v3 source scores"):
        PostgresSource(v3_source_dsn)


def test_unrelated_partial_index_does_not_claim_complete_substructure_support(indexed_source_dsn):
    """任意额外分数或其他条件的部分索引不能误认为覆盖全部允许来源。"""
    from psycopg import sql

    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        for row in writer.execute(
            "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='reaction' AND tablename='reactions'"
        ):
            if "USING gist (products_mol" in row[1]:
                writer.execute(sql.SQL("DROP INDEX reaction.{}").format(sql.Identifier(row[0])))
        writer.execute(
            "CREATE INDEX ON reaction.reactions USING gist (products_mol) WHERE final_score>=18"
        )
    with pytest.raises(ValueError, match="GiST on products_mol"):
        PostgresSource(indexed_source_dsn, table="reactions")


@pytest.mark.parametrize("layer", ["whole", "fragment"])
def test_knn_core_filter_precedes_candidate_pagination(indexed_source_dsn, layer):
    """有限近邻池先限制当前核心，不能让不含氧的高相似候选占用醇查询的分页名额。"""
    source = PostgresSource(indexed_source_dsn, table="reactions")
    family = carbon_family(layer=layer).model_copy(update={"core_smarts": "[#8]", "id": "oxygen"})
    try:
        first = source.candidate_page(family, "product", 0, 1, "CCN")
        assert len(first.items) == 1
        found = list(first.items)
        cursor = first.next_cursor
        while cursor is not None:
            page = source.candidate_page(family, "product", cursor, 1, "CCN")
            found.extend(page.items)
            cursor = page.next_cursor
        assert {r.record.id for r in found} == {"integration:1", "integration:3"}
        assert len(found) == 2
    finally:
        source.close()


def test_core_change_seed_can_recover_outside_knn_without_dropping_nearby(indexed_source_dsn):
    """近邻前512均保留核心时，补入池外真实核心变化线索，并保留近邻及不重复分页。"""
    with psycopg.connect(indexed_source_dsn, autocommit=True) as writer:
        writer.execute("SET rdkit.morgan_fp_size=2048")
        writer.execute("DELETE FROM reaction.reactions")
        writer.execute("""
            INSERT INTO reaction.reactions
            (id,product_smiles,reactant_smiles,products_mol,reactants_mol,product_fp,final_score)
            SELECT n,ARRAY['CCO'],ARRAY['CCO'],'CCO'::mol,'CCO'::mol,morganbv_fp('CCO'::mol,2),12
            FROM generate_series(1,520) n
        """)
        writer.execute("""
            INSERT INTO reaction.reactions
            (id,product_smiles,reactant_smiles,products_mol,reactants_mol,product_fp,final_score)
            VALUES(1001,ARRAY['CCCO'],ARRAY['CCC=O'],'CCCO'::mol,'CCC=O'::mol,morganbv_fp('CCCO'::mol,2),12),
                  (1002,ARRAY['CCCCO'],ARRAY['CCCC=O'],'CCCCO'::mol,'CCCC=O'::mol,morganbv_fp('CCCCO'::mol,2),11)
        """)
    family = carbon_family(layer="whole").model_copy(
        update={"core_smarts": "[#6]-[#8]", "id": "alcohol-core"}
    )
    source = PostgresSource(indexed_source_dsn, table="reactions")
    try:
        page = source.candidate_page(family, "product", 0, 2, "CCO")
        assert page.items[0].record.id == "integration:1001"
        assert page.items[1].material.smiles == "CCO"
        assert len(source._knn[("product", "CCO")]) == 512
        ids = [r.record.id for r in page.items]
        cursor = page.next_cursor
        while cursor is not None:
            page = source.candidate_page(family, "product", cursor, 100, "CCO")
            ids.extend(r.record.id for r in page.items)
            cursor = page.next_cursor
        assert len(ids) == 513 and len(set(ids)) == 513 and "integration:1002" not in ids
        # 相同核心在分片层不复用整体层的池外种子，独立通道仍能找到近邻池之外的记录。
        fragment = family.model_copy(update={"layer": "fragment", "id": "alcohol-fragment"})
        near_fragment = source.candidate_page(fragment, "product", 0, 600, "CCO")
        near_ids = {r.record.id for r in near_fragment.items}
        assert len(near_ids) == 512 and "integration:1001" not in near_ids
        independent = source.candidate_page(fragment, "product", 0, 600, "CCO", stage=1)
        independent_ids = {r.record.id for r in independent.items}
        assert "integration:1001" in independent_ids and "integration:1002" not in independent_ids
    finally:
        source.close()
