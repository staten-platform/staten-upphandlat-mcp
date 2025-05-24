import asyncio
import os
import sys
from asyncio.subprocess import DEVNULL
import json # <--- ADD THIS
import pytest # <--- ADD THIS

yaml = pytest.importorskip("yaml")

mcp_mod = pytest.importorskip("mcp")

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
import httpx


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
    
    # --- MODIFICATION START ---
    assert result.content, "call_tool result.content should not be empty"
    # list_available_dataframes should return a single JSON string in a single ToolContent item
    assert len(result.content) == 1, f"Expected one content item, got {len(result.content)}"
    
    content_item = result.content[0]
    assert hasattr(content_item, "text"), "Content item should have a 'text' attribute"
    
    try:
        parsed_content = json.loads(content_item.text)
    except json.JSONDecodeError as e:
        pytest.fail(f"Failed to parse content item text as JSON: '{content_item.text}'. Error: {e}")

    # Based on sample_config, this is the expected output
    expected_data = [{"name": "sample", "description": "Sample dataset"}]
    
    assert isinstance(parsed_content, list), \
        f"Expected parsed content to be a list, got {type(parsed_content).__name__}: {parsed_content}"
    assert parsed_content == expected_data, \
        f"Unexpected parsed content. Expected {expected_data}, got {parsed_content}"
    # --- MODIFICATION END ---


@pytest.mark.asyncio
async def test_server_stdio(sample_config, monkeypatch):
    monkeypatch.setenv("CSV_SOURCES_CONFIG_PATH", str(sample_config))
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("POLARS_MAX_THREADS", "1")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "upphandlat_mcp"],
        env=os.environ.copy(),
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
            "POLARS_MAX_THREADS": "1",
        }
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "upphandlat_mcp",
        env=env,
    )

    async def wait_for_server_ready(process: asyncio.subprocess.Process, base_url: str, mcp_endpoint_path: str = "/mcp/", timeout: float = 20.0):
        deadline = asyncio.get_event_loop().time() + timeout
        check_url = base_url.rstrip('/') + '/'
        
        print(f"WAIT_FOR_SERVER_DEBUG: Checking server readiness at {check_url}", file=sys.stderr, flush=True)
        last_exception = None

        async with httpx.AsyncClient() as client:
            while True:
                if process.returncode is not None:
                    stdout, stderr = await process.communicate()
                    print(f"WAIT_FOR_SERVER_DEBUG: Server process stdout: {stdout.decode(errors='ignore') if stdout else 'None'}", file=sys.stderr, flush=True)
                    print(f"WAIT_FOR_SERVER_DEBUG: Server process stderr: {stderr.decode(errors='ignore') if stderr else 'None'}", file=sys.stderr, flush=True)
                    raise RuntimeError(f"Server process exited prematurely with code {process.returncode}")

                try:
                    response = await client.get(
                        check_url,
                        timeout=5.0,
                        headers={"Accept": "*/*"},
                    )
                    if (
                        200 <= response.status_code < 300
                        or response.status_code in {404, 405}
                    ):
                        print(f"WAIT_FOR_SERVER_DEBUG: Server at {check_url} responded with {response.status_code}. Ready.", file=sys.stderr, flush=True)
                        return
                    else:
                        print(f"WAIT_FOR_SERVER_DEBUG: Server at {check_url} responded with {response.status_code}. Retrying...", file=sys.stderr, flush=True)
                        last_exception = httpx.HTTPStatusError(f"Server responded with {response.status_code}", request=response.request, response=response)

                except httpx.RequestError as e:
                    last_exception = e
                    if asyncio.get_event_loop().time() < deadline - (timeout * 0.8):
                        print(f"WAIT_FOR_SERVER_DEBUG: HTTP request to {check_url} failed: {type(e).__name__}. Retrying...", file=sys.stderr, flush=True)


                if asyncio.get_event_loop().time() >= deadline:
                    print(f"WAIT_FOR_SERVER_DEBUG: Timeout waiting for server at {check_url}. Process alive: {process.returncode is None}", file=sys.stderr, flush=True)
                    if process.returncode is None:
                        process.terminate()
                        try:
                            s_out, s_err = await asyncio.wait_for(process.communicate(), timeout=2.0)
                            print(f"WAIT_FOR_SERVER_DEBUG: Server stdout on forced terminate: {s_out.decode(errors='ignore') if s_out else 'None'}", file=sys.stderr, flush=True)
                            print(f"WAIT_FOR_SERVER_DEBUG: Server stderr on forced terminate: {s_err.decode(errors='ignore') if s_err else 'None'}", file=sys.stderr, flush=True)
                        except asyncio.TimeoutError:
                            print("WAIT_FOR_SERVER_DEBUG: Timeout during communicate after terminate.", file=sys.stderr, flush=True)
                        except Exception as comm_exc:
                            print(f"WAIT_FOR_SERVER_DEBUG: Error during communicate after terminate: {comm_exc}", file=sys.stderr, flush=True)
                    raise RuntimeError(f"Server at {check_url} did not become ready in time (timeout: {timeout}s). Last error: {last_exception if last_exception else 'N/A'}")
                await asyncio.sleep(0.5)

    try:
        mcp_server_url = "http://127.0.0.1:8000/mcp/"
        http_base_url = "http://127.0.0.1:8000"

        await wait_for_server_ready(proc, http_base_url, mcp_endpoint_path="/mcp/")

        async with streamablehttp_client(mcp_server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await _call_list(session)
    finally:
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()

