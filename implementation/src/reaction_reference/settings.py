"""RR_ 环境配置入口：只管理连接、容量、目录及内部令牌；化学匹配语义由请求和版本规则确定。"""

from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """内部服务配置，敏感连接/令牌不参与 repr；默认使用包内合成示例和本地运行目录。"""

    model_config = SettingsConfigDict(env_prefix="RR_", extra="ignore")
    source_kind: Literal["jsonl", "postgres"] = "jsonl"
    source_path: Path = Field(
        # 每次构造配置时定位安装包内资源，兼容源码运行和 wheel 安装。
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
        """提取子进程建立来源所需的可序列化配置，返回普通字典。

        包含私有连接信息，只允许经父子进程参数传递；不得写入日志、manifest 或用户结果。
        """
        return {
            "source_kind": self.source_kind,
            "source_path": str(self.source_path),
            "postgres_dsn": self.postgres_dsn,
            "source_timeout_ms": self.source_timeout_ms,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
        }
