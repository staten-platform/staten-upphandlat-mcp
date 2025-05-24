import types

import pytest

pl = pytest.importorskip("polars")

from upphandlat_mcp.tools import info_tools  # noqa: E402

class DummyCtx:
    def __init__(self, lifespan_context: dict[str, object]):
        self.request_context = types.SimpleNamespace(lifespan_context=lifespan_context)

    async def info(self, *args, **kwargs):
        pass

    async def error(self, *args, **kwargs):
        pass

    async def warning(self, *args, **kwargs):
        pass

    async def report_progress(self, *args, **kwargs):
        pass


@pytest.fixture()
def sample_context(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("name;value\nAlice;1\nBob;2\nAlice;3\n")
    df = pl.read_csv(csv_path, separator=";")
    sources_cfg = types.SimpleNamespace(
        sources=[types.SimpleNamespace(name="sample", description="Sample dataset")]
    )
    lifespan = {
        "dataframes": {"sample": df},
        "settings": None,
        "csv_sources_config": sources_cfg,
    }
    return lifespan


@pytest.mark.asyncio
async def test_list_available_dataframes(sample_context):
    ctx = DummyCtx(sample_context)
    result = await info_tools.list_available_dataframes(ctx)
    assert result == [{"name": "sample", "description": "Sample dataset"}]


@pytest.mark.asyncio
async def test_list_columns(sample_context):
    ctx = DummyCtx(sample_context)
    result = await info_tools.list_columns(ctx, "sample")
    assert result == ["name", "value"]


@pytest.mark.asyncio
async def test_get_schema(sample_context):
    ctx = DummyCtx(sample_context)
    schema = await info_tools.get_schema(ctx, "sample")
    assert set(schema.keys()) == {"name", "value"}


@pytest.mark.asyncio
async def test_distinct_values(sample_context):
    ctx = DummyCtx(sample_context)
    values = await info_tools.get_distinct_column_values(ctx, "sample", "name")
    assert sorted(values) == ["Alice", "Bob"]


rapidfuzz = pytest.importorskip("rapidfuzz")

@pytest.mark.asyncio
async def test_fuzzy_search(sample_context):
    ctx = DummyCtx(sample_context)
    matches = await info_tools.fuzzy_search_column_values(
        ctx,
        "sample",
        "name",
        "Alce",
        limit=1,
    )
    assert matches and matches[0]["value"] == "Alice"

