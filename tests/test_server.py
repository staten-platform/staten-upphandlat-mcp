import asyncio
import os
import sys
from asyncio.subprocess import DEVNULL

import pytest

yaml = pytest.importorskip("yaml")  # noqa: E402

mcp_mod = pytest.importorskip("mcp")  # noqa: E402

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client


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
                "url": csv_path.as_uri(),
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
    env.update(
        {
            "CSV_SOURCES_CONFIG_PATH": str(sample_config),
            "MCP_TRANSPORT": "streamable-http",
        }
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "upphandlat_mcp",
        env=env,
        stdout=DEVNULL,
        stderr=DEVNULL,
    )

    # Renamed and redefined wait_for_server
    async def wait_for_server_ready(url: str, timeout: float = 5.0):
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            try:
                # Attempt to establish a full session to confirm server readiness
                async with streamablehttp_client(url) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                return  # Server is ready
            except Exception:  # noqa: BLE001
                if asyncio.get_event_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.1)

    try:
        server_url = "http://127.0.0.1:8000/mcp"
        await wait_for_server_ready(server_url) # Wait for the server to be fully operational

        # Connect to the server using the SDK's recommended pattern
        async with streamablehttp_client(server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await _call_list(session)
    finally:
        proc.terminate()
        await proc.wait()

