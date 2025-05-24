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
    monkeypatch.setenv("POLARS_MAX_THREADS", "1") # Control Polars threading

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "upphandlat_mcp"],
        env=os.environ.copy(), # Ensure subprocess inherits env including monkeypatched vars
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
            "POLARS_MAX_THREADS": "1", # Control Polars threading
        }
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "upphandlat_mcp",
        env=env,
        # stdout=DEVNULL, # Ensure these are commented out for visibility
        # stderr=DEVNULL, # Ensure these are commented out for visibility
    )

    # Improved wait_for_server_ready
    async def wait_for_server_ready(proc: asyncio.subprocess.Process, url: str, timeout: float = 10.0): # Increased timeout
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            if proc.returncode is not None:
                # Attempt to read any final output if process exited
                stdout, stderr = await proc.communicate()
                print(f"WAIT_FOR_SERVER_DEBUG: Server process stdout: {stdout.decode(errors='ignore') if stdout else 'None'}", file=sys.stderr, flush=True)
                print(f"WAIT_FOR_SERVER_DEBUG: Server process stderr: {stderr.decode(errors='ignore') if stderr else 'None'}", file=sys.stderr, flush=True)
                raise RuntimeError(f"Server process exited prematurely with code {proc.returncode}")

            try:
                # Attempt to establish a full session to confirm server readiness
                async with streamablehttp_client(url) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                print(f"WAIT_FOR_SERVER_DEBUG: Server at {url} is ready.", file=sys.stderr, flush=True)
                return  # Server is ready
            except ConnectionRefusedError:
                # This is expected initially, so don't make it too noisy unless debugging deep
                if asyncio.get_event_loop().time() < deadline - (timeout * 0.8): # Only print for first 20% of attempts
                    print(f"WAIT_FOR_SERVER_DEBUG: Connection to {url} refused. Retrying...", file=sys.stderr, flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"WAIT_FOR_SERVER_DEBUG: Error connecting to {url}: {type(e).__name__} - {e}. Retrying...", file=sys.stderr, flush=True)

                if asyncio.get_event_loop().time() >= deadline:
                    print(f"WAIT_FOR_SERVER_DEBUG: Timeout waiting for server at {url}. Process alive: {proc.returncode is None}", file=sys.stderr, flush=True)
                    # Try to get more info from the process if it's still running on timeout
                    if proc.returncode is None: # Check if still running before communicate
                        proc.terminate() # Terminate the process
                        try:
                            # Wait for a short period for termination and capture output
                            s_out, s_err = await asyncio.wait_for(proc.communicate(), timeout=2.0)
                            print(f"WAIT_FOR_SERVER_DEBUG: Server stdout on forced terminate: {s_out.decode(errors='ignore') if s_out else 'None'}", file=sys.stderr, flush=True)
                            print(f"WAIT_FOR_SERVER_DEBUG: Server stderr on forced terminate: {s_err.decode(errors='ignore') if s_err else 'None'}", file=sys.stderr, flush=True)
                        except asyncio.TimeoutError:
                            print("WAIT_FOR_SERVER_DEBUG: Timeout during communicate after terminate.", file=sys.stderr, flush=True)
                        except Exception as comm_exc: # pylint: disable=broad-except
                            print(f"WAIT_FOR_SERVER_DEBUG: Error during communicate after terminate: {comm_exc}", file=sys.stderr, flush=True)
                    raise RuntimeError(f"Server at {url} did not become ready in time (timeout: {timeout}s) due to: {e}")
                await asyncio.sleep(0.2) # Slightly longer sleep

    try:
        server_url = "http://127.0.0.1:8000/mcp"
        await wait_for_server_ready(proc, server_url) # Pass proc and wait

        # Connect to the server using the SDK's recommended pattern
        async with streamablehttp_client(server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await _call_list(session)
    finally:
        proc.terminate()
        await proc.wait()

