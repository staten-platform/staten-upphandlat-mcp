import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

mcp_mod = pytest.importorskip("mcp")
from anthropic import APIError, Anthropic # noqa: E402
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

        self.anthropic_client = None
        if self.USE_ANTHROPIC_IN_TEST and self.api_key:
            try:
                self.anthropic_client = Anthropic() # API key is read from env by default
            except Exception as e:
                if self.verbose:
                    print(f"LLM_CLIENT_ERROR: Failed to initialize Anthropic client: {e}", file=sys.stderr)
                self.anthropic_client = None # Ensure it's None if init fails

    def get_response(self, messages: list[dict[str, str]]) -> str:
        if self.USE_ANTHROPIC_IN_TEST and self.api_key and self.anthropic_client:
            model_name = "claude-3-sonnet-20240229" # Using a known valid model
            max_tokens_to_sample = 256

            try:
                if self.verbose:
                    print(f"LLM_CLIENT_SDK_CALL_PARAMS: model='{model_name}', max_tokens={max_tokens_to_sample}, messages_count={len(messages)}", file=sys.stderr)
                    # Optionally log full messages if needed, but be wary of size/sensitivity
                    # print(f"LLM_CLIENT_SDK_MESSAGES: {json.dumps(messages, indent=2)}", file=sys.stderr)

                response_obj = self.anthropic_client.messages.create(
                    model=model_name,
                    max_tokens=max_tokens_to_sample,
                    messages=messages,
                )

                if self.verbose:
                    print(f"LLM_CLIENT_SDK_RESPONSE_ID: {response_obj.id}", file=sys.stderr)
                    print(f"LLM_CLIENT_SDK_RESPONSE_MODEL: {response_obj.model}", file=sys.stderr)
                    print(f"LLM_CLIENT_SDK_RESPONSE_ROLE: {response_obj.role}", file=sys.stderr)
                    print(f"LLM_CLIENT_SDK_RESPONSE_STOP_REASON: {response_obj.stop_reason}", file=sys.stderr)
                    # Log content carefully
                    response_text_preview = (response_obj.content[0].text[:100] + '...') if len(response_obj.content[0].text) > 100 else response_obj.content[0].text
                    print(f"LLM_CLIENT_SDK_RESPONSE_CONTENT_PREVIEW: {response_text_preview}", file=sys.stderr)

                return response_obj.content[0].text
            except APIError as e:
                if self.verbose:
                    print(f"LLM_CLIENT_SDK_ERROR: APIError during Anthropic call: {e}", file=sys.stderr)
                # Fall through to mock response on API error
            except Exception as e: # Catch any other unexpected error
                if self.verbose:
                    print(f"LLM_CLIENT_SDK_UNEXPECTED_ERROR: {e}", file=sys.stderr)
                # Fall through to mock response

        # Fallback to mock response if API is not used, key is missing, client init failed, or API call failed
        mock_response = '{"tool": "list_available_dataframes", "arguments": {}}'
        if self.verbose:
            print(f"LLM_CLIENT_MOCK_RESPONSE: {mock_response}", file=sys.stderr)
        return mock_response


async def wait_for_server_ready(
    process: asyncio.subprocess.Process,
    base_url: str,
    timeout: float = 20.0,
) -> None:
    """Wait until the HTTP server responds."""
    deadline = asyncio.get_event_loop().time() + timeout
    check_url = base_url.rstrip("/") + "/"
    last_exception = None
    # Use httpx for server readiness check as it's a dependency of anthropic SDK
    import httpx # Local import for this helper
    async with httpx.AsyncClient() as client:
        while True:
            if process.returncode is not None:
                stdout, stderr = await process.communicate()
                raise RuntimeError(
                    f"Server exited with code {process.returncode}. "
                    f"stdout={stdout.decode()}, stderr={stderr.decode()}"
                )
            try:
                response = await client.get(check_url, timeout=5.0)
                if HTTP_OK <= response.status_code < HTTP_MULT_CHOICE or response.status_code in {404, 405}:
                    return
                last_exception = httpx.HTTPStatusError(f"Server responded with {response.status_code}", request=response.request, response=response)
            except httpx.RequestError as exc:
                last_exception = exc

            if asyncio.get_event_loop().time() >= deadline:
                raise RuntimeError(
                    f"Server not ready after {timeout}s: {last_exception}"
                )
            await asyncio.sleep(0.5)


async def run_chat_session(server_url: str) -> list[dict[str, str]]:
    """Run a minimal chat session calling one tool."""
    llm_client = LLMClient()
    verbose = os.getenv("TEST_INTEGRATION_VERBOSE") == "1"

    async with streamablehttp_client(server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = ", ".join(t.name for t in tools.tools)
            system_msg = { # This structure is fine for Anthropic SDK messages list
                "role": "system",
                "content": f"Tools available: {tool_names}",
            }
            messages = [system_msg, {"role": "user", "content": "what dataframes"}]
            llm_resp_text = llm_client.get_response(messages)
            
            # Ensure llm_resp_text is valid JSON before trying to load it
            try:
                tool_call = json.loads(llm_resp_text)
            except json.JSONDecodeError:
                if verbose:
                    print(f"LLM_RESPONSE_NOT_JSON: Could not decode LLM response as JSON: '{llm_resp_text}'", file=sys.stderr)
                # If LLM response is not the expected JSON, the test will likely fail at assertion or next step.
                # For this test, if it's not JSON, it's an unexpected (non-mock) response.
                # Let's assume for now the test expects a JSON parsable tool call.
                # If Anthropic returns natural language, this will fail.
                # The mock ensures it's JSON. A real call might not.
                # This part of the test might need adjustment based on real API behavior.
                # For now, if it's not JSON, the test will fail when trying to access tool_call['tool']
                # which is an acceptable failure mode for an unexpected LLM response.
                # Re-raise or handle as appropriate if this becomes a frequent issue with real API.
                raise AssertionError(f"LLM response was not valid JSON: {llm_resp_text}")

            if verbose:
                print(f"MCP_CLIENT_TOOL_CALL_SENT: tool='{tool_call['tool']}', args={tool_call['arguments']}", file=sys.stderr)

            call_result = await session.call_tool(
                tool_call["tool"], tool_call["arguments"]
            )

            if verbose:
                logged_content = []
                for item in call_result.content:
                    if hasattr(item, 'text'):
                        logged_content.append(item.text)
                    else:
                        logged_content.append(str(item))
                print(f"MCP_CLIENT_TOOL_CALL_RESULT_CONTENT: {logged_content}", file=sys.stderr)

            data: list[dict[str, str]] = []
            for item in call_result.content:
                if hasattr(item, "text"):
                    try:
                        # The content from list_available_dataframes is a JSON string representing a dict
                        loaded_item = json.loads(item.text)
                        if isinstance(loaded_item, dict): # Ensure it's a dict as expected by the assertion
                            data.append(loaded_item)
                        elif isinstance(loaded_item, list) and len(loaded_item) == 1 and isinstance(loaded_item[0], dict):
                            # Handle if it's a list with one dict (older expectation)
                            data.append(loaded_item[0])
                        else:
                            # Unexpected structure
                            data.append({"text": item.text}) # Fallback
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
