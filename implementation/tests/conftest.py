import pytest

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.domain.models import SearchRequest, Target
from reaction_reference.settings import Settings


@pytest.fixture
def fixture_path():
    return Settings().source_path


@pytest.fixture
def source(fixture_path):
    instance = JsonlSource(fixture_path, exhaustive=True)
    yield instance
    instance.close()


@pytest.fixture
def amide(source):
    return next(r for r in source.records if r.id == "demo-amide-ethyl")


@pytest.fixture
def request_factory():
    def create(smiles="CCCNC(=O)c1ccccc1", **kwargs):
        return SearchRequest(target=Target(value=smiles), **kwargs)

    return create


@pytest.fixture
def settings(tmp_path):
    return Settings(store_path=tmp_path / "runs")
