from reaction_reference.adapters.annotations import AnnotatedSource
from reaction_reference.adapters.execution import RunManager
from reaction_reference.adapters.sources import JsonlSource, PostgresSource
from reaction_reference.ports.sources import CompoundSource
from reaction_reference.settings import Settings


def open_source(settings, *, exhaustive=False) -> CompoundSource:
    source: CompoundSource
    if settings.source_kind == "postgres":
        if not settings.postgres_dsn:
            raise ValueError("RR_POSTGRES_DSN is required")
        source = PostgresSource(settings.postgres_dsn, timeout_ms=settings.source_timeout_ms)
    else:
        source = JsonlSource(settings.source_path, exhaustive=exhaustive)
    if settings.evidence_path:
        try:
            return AnnotatedSource(source, settings.evidence_path)
        except Exception:
            source.close()
            raise
    return source


def create_manager(settings=None):
    return RunManager(settings or Settings())
