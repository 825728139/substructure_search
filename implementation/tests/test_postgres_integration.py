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
                product_fp bfp, reactant_fp bfp
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


@pytest.mark.parametrize("role", ["product", "reactant"])
def test_indexed_cursor_pages_and_read_only_session(indexed_source_dsn, role):
    """真实服务端游标按页返回全部材料，严格只读事务拒绝写入。"""
    source = PostgresSource(indexed_source_dsn)
    try:
        cursor, items = 0, []
        while True:
            page = source.candidate_page(carbon_family(), role, cursor, 1, "CCO")
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


@pytest.mark.parametrize("details_by_id", [False, True])
def test_knn_selection_and_detail_hydration(indexed_source_dsn, details_by_id):
    """真实指纹近邻首项命中乙醇，详情名称通过结构对应，并可切换独立子结构通道。"""
    if details_by_id:
        with psycopg.connect(indexed_source_dsn, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE reaction.reaction_details ADD COLUMN reaction_id bigint"
            )
            connection.execute("UPDATE reaction.reaction_details SET reaction_id=1")
    source = PostgresSource(indexed_source_dsn)
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
    source = PostgresSource(indexed_source_dsn, timeout_ms=100)
    try:
        with psycopg.connect(indexed_source_dsn) as writer:
            writer.execute("LOCK TABLE reaction.reactions IN ACCESS EXCLUSIVE MODE")
            with pytest.raises(psycopg.errors.QueryCanceled):
                source.candidate_page(carbon_family(name="timeout"), "product", 0, 10, "CCO")
            writer.rollback()
        page = source.candidate_page(carbon_family(name="after-timeout"), "product", 0, 10, "CCO")
        assert len(page.items) == 3
    finally:
        source.close()


def test_repeatable_read_keeps_material_fields_frozen(indexed_source_dsn):
    """来源建立快照后其他会话更新原行，本次查询和详情仍必须对应旧材料结构。"""
    source = PostgresSource(indexed_source_dsn)
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
    source = PostgresSource(indexed_source_dsn)
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
    source = PostgresSource(indexed_source_dsn)
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
    source = PostgresSource(indexed_source_dsn)
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
    source = PostgresSource(indexed_source_dsn)
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
    source = PostgresSource(indexed_source_dsn)
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
