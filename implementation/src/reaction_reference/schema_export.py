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
