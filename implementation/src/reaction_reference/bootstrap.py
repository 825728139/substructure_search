"""组合根：在这里选择具体适配器并连接应用服务，领域与化学模块不反向依赖此处。"""

from reaction_reference.adapters.annotations import AnnotatedSource
from reaction_reference.adapters.execution import RunManager
from reaction_reference.adapters.sources import JsonlSource, PostgresSource
from reaction_reference.ports.sources import CompoundSource
from reaction_reference.settings import Settings


def open_source(settings, *, exhaustive=False) -> CompoundSource:
    """根据 Settings 创建 JSONL 或只读 PG 来源，并可包装审核证据适配器。

    exhaustive 只应用于有限 JSONL；包装失败关闭已创建来源后重抛，成功时由调用方承担 close。
    """
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
    """使用给定或默认 Settings 创建 RunManager，供 SDK/API 共享同一装配方式。"""
    return RunManager(settings or Settings())
