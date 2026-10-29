"""导出受版本管理的数据契约与 OpenAPI；临时应用资源在导出完成后关闭。"""

import json
import tempfile
from pathlib import Path

from reaction_reference.adapters.annotations import EvidenceAnnotation
from reaction_reference.domain.models import (
    QueryFamily,
    ReactionRecord,
    ReferencePackage,
    RerankRequest,
    RunState,
    SearchRequest,
)


def export_schemas(directory):
    """把请求、家族、反应、证据审核、资料包与状态 Schema 及 OpenAPI 写入 directory。

    导出时创建临时运行目录，不访问生产来源；Pydantic 类 docstring 会进入 Schema 描述，因此修改契约注释后应重新导出并检查漂移。
    """
    directory.mkdir(parents=True, exist_ok=True)
    for model in (
        SearchRequest,
        QueryFamily,
        ReactionRecord,
        ReferencePackage,
        RunState,
        RerankRequest,
        EvidenceAnnotation,
    ):
        (directory / f"{model.__name__}.schema.json").write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
        )
    from reaction_reference.interfaces.api import create_app
    from reaction_reference.settings import Settings

    with tempfile.TemporaryDirectory() as temporary:
        app = create_app(
            Settings(
                store_path=Path(temporary),
                evidence_path=None,
                postgres_dsn=None,
                source_kind="jsonl",
            )
        )
        try:
            (directory / "openapi.json").write_text(
                json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
            )
        finally:
            app.state.client.close()
