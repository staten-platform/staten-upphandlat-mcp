from __future__ import annotations
# ruff: noqa: I001

import sys
from pathlib import Path
import asyncio
import os
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamable_http_client
except ModuleNotFoundError:
    pytest.skip("mcp not installed", allow_module_level=True)

try:
    import yaml
except ModuleNotFoundError:
    pytest.skip("pyyaml not installed", allow_module_level=True)


@pytest.fixture()
def sample_config(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("name;value\nAlice;1\nBob;2\n")
    config = {
        "toolbox_title": "Test",
        "toolbox_description": "Test",
        "sources": [
            {
                "name": "sample",
                "url": str(csv_path),
                "description": "Sample dataset",
                "read_csv_options": {"separator": ";"},
            }
        ],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    return config_path


async def _call_list(sample_session):
    tools = await sample_session.list_tools()
    assert any(t.name == "list_available_dataframes" for t in tools.tools)
    result = await sample_session.call_tool("list_available_dataframes", arguments={})
    assert result.content


@pytest.mark.asyncio
async def test_server_stdio(sample_config, monkeypatch):
    monkeypatch.setenv("CSV_SOURCES_CONFIG_PATH", str(sample_config))
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "upphandlat_mcp"],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _call_list(session)


@pytest.mark.asyncio
async def test_server_streamable_http(sample_config, monkeypatch):
    monkeypatch.setenv("CSV_SOURCES_CONFIG_PATH", str(sample_config))
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    env = os.environ.copy()
    env.update({
        "CSV_SOURCES_CONFIG_PATH": str(sample_config),
        "MCP_TRANSPORT": "streamable-http",
    })
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "upphandlat_mcp",
        env=env,
    )
    try:
        client = await streamable_http_client("http://127.0.0.1:8000/mcp")
        async with client as session:
            await session.initialize()
            await _call_list(session)
    finally:
        proc.terminate()
        await proc.wait()

