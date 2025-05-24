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
        self.USE_ANTHROPIC_IN_TEST = os.getenv("USE_ANTHROPIC_IN_TEST") == "1"
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        # --- MODIFICATION START ---
        raw_env_val = os.getenv("TEST_INTEGRATION_VERBOSE")
        print(f"DEBUG: TEST_INTEGRATION_VERBOSE raw: '{raw_env_val}'", file=sys.stderr)
        self.verbose = raw_env_val == "1"
        print(f"DEBUG: self.verbose is: {self.verbose}", file=sys.stderr)
        # --- MODIFICATION END ---

    def get_response(self, messages: list[dict[str, str]]) -> str:
        if self.USE_ANTHROPIC_IN_TEST and self.api_key:
            url = "https://api.anthropic.com/v1/messages"
            payload = {
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 256,
                "messages": messages,
            }
            # --- MODIFICATION START ---
            if self.verbose:
                print(f"LLM_CLIENT_REQUEST_URL: {url}", file=sys.stderr)
                print(f"LLM_CLIENT_REQUEST_PAYLOAD: {json.dumps(payload, indent=2)}", file=sys.stderr)
            # --- MODIFICATION END ---
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
                response_body = resp.read().decode() # Read body once
                # --- MODIFICATION START ---
                if self.verbose:
                    print(f"LLM_CLIENT_RESPONSE_STATUS: {resp.status}", file=sys.stderr)
                    print(f"LLM_CLIENT_RESPONSE_HEADERS: {resp.headers}", file=sys.stderr)
                    try:
                        # Try to pretty-print if it's JSON, otherwise print as is
                        parsed_response_body = json.loads(response_body)
                        print(f"LLM_CLIENT_RESPONSE_BODY: {json.dumps(parsed_response_body, indent=2)}", file=sys.stderr)
                    except json.JSONDecodeError:
                        print(f"LLM_CLIENT_RESPONSE_BODY: {response_body}", file=sys.stderr)
                # --- MODIFICATION END ---
                data = json.loads(response_body) # Use the already read body
            return data["content"][0]["text"]
        # --- MODIFICATION START ---
        mock_response = '{"tool": "list_available_dataframes", "arguments": {}}'
        if self.verbose:
            print(f"LLM_CLIENT_MOCK_RESPONSE: {mock_response}", file=sys.stderr)
        return mock_response
        # --- MODIFICATION END ---


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
    # --- MODIFICATION START ---
    verbose = os.getenv("TEST_INTEGRATION_VERBOSE") == "1"
    # --- MODIFICATION END ---

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

            # --- MODIFICATION START ---
            if verbose:
                print(f"MCP_CLIENT_TOOL_CALL_SENT: tool='{tool_call['tool']}', args={tool_call['arguments']}", file=sys.stderr)
            # --- MODIFICATION END ---

            call_result = await session.call_tool(
                tool_call["tool"], tool_call["arguments"]
            )

            # --- MODIFICATION START ---
            if verbose:
                # Be careful with potentially large content.
                # For now, let's log the type and number of items.
                # If content items have a 'text' attribute, log that.
                logged_content = []
                for item in call_result.content:
                    if hasattr(item, 'text'):
                        logged_content.append(item.text)
                    else:
                        logged_content.append(str(item)) # Fallback to string representation
                print(f"MCP_CLIENT_TOOL_CALL_RESULT_CONTENT: {logged_content}", file=sys.stderr)
            # --- MODIFICATION END ---

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
    # Set environment variables for LLMClient and run_chat_session
    # Ensure verbose logging is enabled for this test
    monkeypatch.setenv("TEST_INTEGRATION_VERBOSE", "1")

    # Propagate USE_ANTHROPIC_IN_TEST from the pytest runner's environment
    # If not set in the runner's env, LLMClient will see it as None, and USE_ANTHROPIC_IN_TEST == "1" will be false.
    use_anthropic_env = os.environ.get("USE_ANTHROPIC_IN_TEST")
    if use_anthropic_env is not None:
        monkeypatch.setenv("USE_ANTHROPIC_IN_TEST", use_anthropic_env)
    else:
        # If you want to default to "0" or "1" if not set, you can do it here.
        # For now, if it's not in the parent env, it won't be set in the test env,
        # and LLMClient's os.getenv("USE_ANTHROPIC_IN_TEST") == "1" will be False.
        # Alternatively, to ensure it's explicitly "0" if not "1":
        # monkeypatch.setenv("USE_ANTHROPIC_IN_TEST", "1" if use_anthropic_env == "1" else "0")
        pass # Let it be unset if not in parent env, LLMClient handles None

    # Propagate ANTHROPIC_API_KEY from the pytest runner's environment
    # If not set in the runner's env, LLMClient will see self.api_key as None.
    anthropic_api_key_env = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_api_key_env is not None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", anthropic_api_key_env)
    else:
        # If ANTHROPIC_API_KEY is not in the parent env, it will not be set in the test env.
        # LLMClient's self.api_key will be None.
        pass

    # Set environment variables for the subprocess (upphandlat_mcp server)
    monkeypatch.setenv("CSV_SOURCES_CONFIG_PATH", str(sample_config))
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http") # This is for the test's direct MCP interaction if any, also for subprocess.

    # Environment for the subprocess
    env = os.environ.copy() # Start with current pytest process env (which now includes monkeypatched vars)
    env.update(
        {
            # These are specifically for the subprocess
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
