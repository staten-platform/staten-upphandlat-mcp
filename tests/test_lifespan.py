import pytest
import yaml

pl = pytest.importorskip("polars")  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from upphandlat_mcp.core.config import settings as app_settings  # noqa: E402
from upphandlat_mcp.lifespan import context as lifespan_context  # noqa: E402
from upphandlat_mcp.lifespan.context import app_lifespan  # noqa: E402


@pytest.fixture(autouse=True)
def reset_lifespan(monkeypatch):
    monkeypatch.setattr(
        "upphandlat_mcp.lifespan.context._global_lifespan_data_cache",
        None,
        raising=False,
    )
    monkeypatch.setattr(
        "upphandlat_mcp.lifespan.context._initialized_successfully",
        False,
        raising=False,
    )
    yield
    monkeypatch.setattr(
        "upphandlat_mcp.lifespan.context._global_lifespan_data_cache",
        None,
        raising=False,
    )
    monkeypatch.setattr(
        "upphandlat_mcp.lifespan.context._initialized_successfully",
        False,
        raising=False,
    )


@pytest.mark.asyncio
async def test_app_lifespan_loads_dataframe(tmp_path, monkeypatch):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("a,b\n1,2\n3,4\n")
    config = {
        "toolbox_title": "Test",
        "toolbox_description": "Test",
        "sources": [
            {
                "name": "sample",
                "url": csv_path.as_uri(),
                "description": "Sample",
                "read_csv_options": {"separator": ","},
            }
        ],
    }
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(yaml.safe_dump(config))

    monkeypatch.setenv("CSV_SOURCES_CONFIG_PATH", str(config_path))
    app_settings.CSV_SOURCES_CONFIG_PATH = config_path

    server = FastMCP("test")
    async with app_lifespan(server) as ctx:
        assert "sample" in ctx["dataframes"]
        df = ctx["dataframes"]["sample"]
        assert df.shape == (2, 2)
    assert lifespan_context._initialized_successfully is True
    assert lifespan_context._global_lifespan_data_cache is not None

    # Second call should reuse cache
    async with app_lifespan(server) as ctx2:
        assert ctx2 is lifespan_context._global_lifespan_data_cache

