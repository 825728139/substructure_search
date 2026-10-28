from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RR_", extra="ignore")
    source_kind: Literal["jsonl", "postgres"] = "jsonl"
    source_path: Path = Field(
        default_factory=lambda: Path(
            str(files("reaction_reference").joinpath("resources/synthetic.jsonl"))
        )
    )
    postgres_dsn: str | None = Field(default=None, repr=False)
    store_path: Path = Path("var/runs")
    max_concurrent_runs: int = Field(default=2, ge=1, le=8)
    max_queued_runs: int = Field(default=16, ge=1, le=128)
    source_timeout_ms: int = Field(default=1500, ge=100, le=10000)
    evidence_path: Path | None = None
    api_token: str | None = Field(default=None, repr=False)
    cursor_secret: str | None = Field(default=None, repr=False)

    def worker_config(self):
        return {
            "source_kind": self.source_kind,
            "source_path": str(self.source_path),
            "postgres_dsn": self.postgres_dsn,
            "source_timeout_ms": self.source_timeout_ms,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
        }
