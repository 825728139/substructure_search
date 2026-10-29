"""回归测试：共享合成来源、请求和临时目录夹具。"""

import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.domain.models import SearchRequest, Target
from reaction_reference.settings import Settings


@pytest.fixture
def fixture_path():
    """返回随包分发的合成示例路径，确保默认测试不访问真实来源。"""
    return Settings().source_path


@pytest.fixture
def source(fixture_path):
    """为测试创建有限穷尽 JSONL 来源，yield 后清空来源缓存。"""
    instance = JsonlSource(fixture_path, exhaustive=True)
    yield instance
    instance.close()


@pytest.fixture
def amide(source):
    """从合成来源挑出乙胺酰胺化记录，供映射与单输入替换测试使用。"""
    return next(r for r in source.records if r.id == "demo-amide-ethyl")


@pytest.fixture
def request_factory():
    """提供统一请求构造器，允许测试仅覆盖与当前场景相关的字段。"""

    def create(smiles="CCCNC(=O)c1ccccc1", **kwargs):
        """将目标 SMILES 和覆盖参数构造成严格 SearchRequest，返回测试请求。"""
        return SearchRequest(target=Target(value=smiles), **kwargs)

    return create


@pytest.fixture
def settings(tmp_path):
    """为每个测试分配独立临时运行目录，避免协调锁与作业状态互相污染。"""
    return Settings(store_path=tmp_path / "runs")
