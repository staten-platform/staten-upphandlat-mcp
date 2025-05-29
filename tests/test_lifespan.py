import pytest
import yaml
from unittest.mock import AsyncMock, MagicMock

pl = pytest.importorskip("polars")  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

from upphandlat_mcp.core.config import settings as app_settings  # noqa: E402
from statens_mima import MCPSharedCache, CacheStats 
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
    
    mock_cache_inst = AsyncMock(spec=MCPSharedCache)
    mock_cache_inst.health_check.return_value = CacheStats(status="healthy") 
    monkeypatch.setattr("upphandlat_mcp.lifespan.context.create_cache", lambda *a, **kw: mock_cache_inst)

    server = FastMCP("test")
    async with app_lifespan(server) as ctx:
        assert "sample" in ctx["available_dataframe_names"]
        assert ctx["shared_cache"] is mock_cache_inst

        # Verify put_dataframe was called correctly
        found_call = False
        for call_args_mock in mock_cache_inst.put_dataframe.call_args_list:
            kwargs_from_call = call_args_mock.kwargs if hasattr(call_args_mock, 'kwargs') else call_args_mock[1]
            
            if kwargs_from_call.get('params', {}).get('source_name') == 'sample':
                found_call = True
                df_put = kwargs_from_call['df']
                assert isinstance(df_put, pl.DataFrame)
                assert df_put.shape == (2,2)
                break
        assert found_call, "put_dataframe not called for 'sample' source"

    assert lifespan_context._initialized_successfully is True
    assert lifespan_context._global_lifespan_data_cache is not None

    # Second call should reuse cache
    async with app_lifespan(server) as ctx2:
        assert ctx2 is lifespan_context._global_lifespan_data_cache

