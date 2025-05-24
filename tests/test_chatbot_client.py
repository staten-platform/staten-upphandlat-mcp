import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

mcp_mod = pytest.importorskip("mcp")
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

HTTP_OK = 200
HTTP_MULT_CHOICE = 300


class LLMClient:
    """Simple LLM client using Anthropic or returning mock responses."""

    def __init__(self) -> None:
        self.use_anthropic = os.getenv("USE_ANTHROPIC") == "1"
        self.api_key = os.getenv("ANTHROPIC_API_KEY")

    def get_response(self, messages: list[dict[str, str]]) -> str:
        if self.use_anthropic and self.api_key:
            url = "https://api.anthropic.com/v1/messages"
            payload = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 256,
                "messages": messages,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
            return data["content"][0]["text"]
        return '{"tool": "list_available_dataframes", "arguments": {}}'


async def wait_for_server_ready(
    process: asyncio.subprocess.Process,
    base_url: str,
    timeout: float = 20.0,
) -> None:
    """Wait until the HTTP server responds."""
    deadline = asyncio.get_event_loop().time() + timeout
    check_url = base_url.rstrip("/") + "/"
    last_exception = None
    while True:
        if process.returncode is not None:
            stdout, stderr = await process.communicate()
            raise RuntimeError(
                f"Server exited with code {process.returncode}. "
                f"stdout={stdout.decode()}, stderr={stderr.decode()}"
            )
        try:
            status = await asyncio.to_thread(
                lambda: urllib.request.urlopen(check_url, timeout=5).getcode()
            )
            if HTTP_OK <= status < HTTP_MULT_CHOICE:
                return
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            if exc.code in {404, 405}:
                return
            last_exception = exc
        except urllib.error.URLError as exc:  # noqa: PERF203
            last_exception = exc
        if asyncio.get_event_loop().time() >= deadline:
            raise RuntimeError(
                f"Server not ready after {timeout}s: {last_exception}"
            )
        await asyncio.sleep(0.5)


async def run_chat_session(server_url: str) -> list[dict[str, str]]:
    """Run a minimal chat session calling one tool."""
    llm_client = LLMClient()
    async with streamablehttp_client(server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = ", ".join(t.name for t in tools.tools)
            system_msg = {
                "role": "system",
                "content": f"Tools available: {tool_names}",
            }
            messages = [system_msg, {"role": "user", "content": "what dataframes"}]
            llm_resp = llm_client.get_response(messages)
            tool_call = json.loads(llm_resp)
            call_result = await session.call_tool(
                tool_call["tool"], tool_call["arguments"]
            )
            data: list[dict[str, str]] = []
            for item in call_result.content:
                if hasattr(item, "text"):
                    try:
                        data.append(json.loads(item.text))
                    except json.JSONDecodeError:
                        data.append({"text": item.text})
            return data


@pytest.fixture()
def sample_config(tmp_path: Path) -> Path:
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
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    return config_path


@pytest.mark.asyncio
async def test_chatbot_integration(
    sample_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    try:
        await wait_for_server_ready(proc, "http://127.0.0.1:8000")
        result = await run_chat_session("http://127.0.0.1:8000/mcp/")
        assert {"name": "sample", "description": "Sample dataset"} in result
    finally:
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()
