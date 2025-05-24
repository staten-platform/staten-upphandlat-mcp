import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any # Added for type hint

import pytest

mcp_mod = pytest.importorskip("mcp")
from anthropic import APIError, Anthropic # noqa: E402
from mcp import ClientSession # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client # noqa: E402
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

    def get_response(
        self,
        messages_input: list[dict[str, str]],
        tools_param: list[dict[str, Any]] | None = None, # For Anthropic tool definitions
    ) -> str:
        if self.USE_ANTHROPIC_IN_TEST and self.api_key and self.anthropic_client:
            model_name = "claude-sonnet-4-20250514" # Or "claude-3-haiku-20240307" for reliable tool use
            max_tokens_to_sample = 1024 # Increased max_tokens

            # --- MODIFICATION START: Separate system prompt from messages ---
            system_prompt_content: str | None = None
            api_messages: list[dict[str, str]] = []
            for msg in messages_input:
                if msg.get("role") == "system":
                    system_prompt_content = msg.get("content")
                else:
                    # Ensure only valid roles (like 'user', 'assistant') are passed
                    if msg.get("role") in ["user", "assistant"]: # Or be more permissive if other roles are expected
                        api_messages.append(msg)
                    elif self.verbose:
                        print(f"LLM_CLIENT_WARNING: Skipping message with unexpected role '{msg.get('role')}' for API call.", file=sys.stderr)
            
            if not api_messages:
                 # This can happen if only a system message was provided, which is invalid for the 'messages' param.
                if self.verbose:
                    print("LLM_CLIENT_ERROR: No user/assistant messages found after filtering system prompt. Cannot make API call.", file=sys.stderr)
                # Fall through to mock response
                # (Alternatively, raise an error or handle as appropriate)
                # For now, let it fall through to mock.
                pass # Will lead to mock response path if this block is entered and then try/except is skipped.
                     # To be more robust, this condition should also lead to the mock response directly.
                     # Let's adjust the if condition below or the fallback logic.
                     # For now, if api_messages is empty, the create call might fail or be non-sensical.
                     # The API likely requires at least one user message.
            # --- MODIFICATION END ---

            try:
                # --- MODIFICATION START: Adjust logging and API call ---
                if self.verbose:
                    print(f"LLM_CLIENT_SDK_CALL_PARAMS: model='{model_name}', max_tokens={max_tokens_to_sample}, messages_count={len(api_messages)}, system_prompt_present={'yes' if system_prompt_content else 'no'}, tools_present={'yes' if tools_param else 'no'}", file=sys.stderr)
                    if system_prompt_content and self.verbose: # Ensure verbose is checked for this print too
                         print(f"LLM_CLIENT_SDK_SYSTEM_PROMPT: {system_prompt_content}", file=sys.stderr)
                    if tools_param and self.verbose:
                        print(f"LLM_CLIENT_SDK_TOOLS_PARAM: {json.dumps(tools_param, indent=2)}", file=sys.stderr)

                if not api_messages: # Explicitly fall back if no valid messages for the API
                    if self.verbose:
                        print("LLM_CLIENT_INFO: No user/assistant messages to send to API, falling back to mock.", file=sys.stderr)
                    raise ValueError("No user/assistant messages to send to API.") # This will be caught by `except Exception`

                create_params = {
                    "model": model_name,
                    "max_tokens": max_tokens_to_sample,
                    "messages": api_messages,
                }
                if system_prompt_content is not None: # Pass system only if it exists
                    create_params["system"] = system_prompt_content
                if tools_param is not None:
                    create_params["tools"] = tools_param
                
                response_obj = self.anthropic_client.messages.create(**create_params)
                # --- MODIFICATION END ---

                if self.verbose:
                    print(f"LLM_CLIENT_SDK_RESPONSE_ID: {response_obj.id}", file=sys.stderr)
                    print(f"LLM_CLIENT_SDK_RESPONSE_MODEL: {response_obj.model}", file=sys.stderr)
                    print(f"LLM_CLIENT_SDK_RESPONSE_ROLE: {response_obj.role}", file=sys.stderr)
                    print(f"LLM_CLIENT_SDK_RESPONSE_STOP_REASON: {response_obj.stop_reason}", file=sys.stderr)
                    # Log content carefully
                    if response_obj.content and hasattr(response_obj.content[0], 'text'):
                        response_text_preview = (response_obj.content[0].text[:100] + '...') if len(response_obj.content[0].text) > 100 else response_obj.content[0].text
                        print(f"LLM_CLIENT_SDK_RESPONSE_CONTENT_PREVIEW: {response_text_preview}", file=sys.stderr)
                    elif response_obj.content:
                         print(f"LLM_CLIENT_SDK_RESPONSE_FIRST_CONTENT_BLOCK_TYPE: {response_obj.content[0].type}", file=sys.stderr)


                # Check for tool use
                if response_obj.stop_reason == "tool_use":
                    for content_block in response_obj.content:
                        if content_block.type == "tool_use":
                            tool_name = content_block.name
                            tool_input = content_block.input
                            if self.verbose:
                                print(f"LLM_CLIENT_SDK_TOOL_USE: name='{tool_name}', input={json.dumps(tool_input, indent=2)}", file=sys.stderr)
                            return json.dumps({"tool": tool_name, "arguments": tool_input})
                
                # If no tool use, return the text content (might be natural language)
                # This will likely cause json.loads in run_chat_session to fail if a tool call was expected.
                if response_obj.content and response_obj.content[0].type == "text":
                    return response_obj.content[0].text
                return "" # Should not happen if content[0] is not text and no tool use

            except APIError as e:
                if self.verbose:
                    print(f"LLM_CLIENT_SDK_ERROR: APIError during Anthropic call: {e}", file=sys.stderr)
                # Fall through to mock response on API error
            except Exception as e: # Catch any other unexpected error, including our ValueError
                if self.verbose:
                    print(f"LLM_CLIENT_SDK_UNEXPECTED_ERROR or PRECONDITION_FAIL: {e}", file=sys.stderr)
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


async def _execute_chatbot_tool_call(
    session: ClientSession, 
    llm_client: LLMClient, 
    verbose: bool
) -> list[dict[str, str]]:
    """Core logic for a chatbot session that calls one tool."""
    await session.initialize()
    tools = await session.list_tools()
    tool_names = ", ".join(t.name for t in tools.tools)
    system_msg = {
        "role": "system",
        "content": f"Tools available: {tool_names}",
    }
    list_df_tool_desc = "Retrieves the list of names and descriptions for all loaded DataFrames."
    anthropic_tools_param = [
        {
            "name": "list_available_dataframes",
            "description": list_df_tool_desc,
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    messages = [system_msg, {"role": "user", "content": "what dataframes"}]
    llm_resp_text = llm_client.get_response(messages, tools_param=anthropic_tools_param)

    try:
        tool_call = json.loads(llm_resp_text)
    except json.JSONDecodeError:
        if verbose:
            print(f"LLM_RESPONSE_NOT_JSON: Could not decode LLM response as JSON: '{llm_resp_text}'", file=sys.stderr)
        raise AssertionError(f"LLM response was not valid JSON: {llm_resp_text}")

    if verbose:
        print(f"MCP_CLIENT_TOOL_CALL_SENT: tool='{tool_call['tool']}', args={tool_call['arguments']}", file=sys.stderr)

    call_result = await session.call_tool(tool_call["tool"], tool_call["arguments"])

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
                loaded_item = json.loads(item.text)
                if isinstance(loaded_item, dict):
                    data.append(loaded_item)
                elif isinstance(loaded_item, list) and len(loaded_item) == 1 and isinstance(loaded_item[0], dict):
                    data.append(loaded_item[0])
                else:
                    data.append({"text": item.text}) 
            except json.JSONDecodeError:
                data.append({"text": item.text})
    return data


async def run_chat_session_http(server_url: str) -> list[dict[str, str]]:
    """Runs the chat session logic using HTTP transport."""
    llm_client = LLMClient()
    verbose = os.getenv("TEST_INTEGRATION_VERBOSE") == "1"
    async with streamablehttp_client(server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            return await _execute_chatbot_tool_call(session, llm_client, verbose)


async def run_chat_session_stdio(read_stream, write_stream) -> list[dict[str, str]]:
    """Runs the chat session logic using STDIN/STDOUT transport."""
    llm_client = LLMClient()
    verbose = os.getenv("TEST_INTEGRATION_VERBOSE") == "1"
    async with ClientSession(read_stream, write_stream) as session:
        return await _execute_chatbot_tool_call(session, llm_client, verbose)



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
    # conftest.py handles ANTHROPIC_API_KEY, USE_ANTHROPIC_IN_TEST.
    # TEST_INTEGRATION_VERBOSE is also loaded by conftest, but we explicitly set it to "1"
    # here to ensure verbosity for this specific test, overriding any .env setting.
    monkeypatch.setenv("TEST_INTEGRATION_VERBOSE", "1")
    monkeypatch.setenv("CSV_SOURCES_CONFIG_PATH", str(sample_config))
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")

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
        result = await run_chat_session_http("http://127.0.0.1:8000/mcp/")
        assert {"name": "sample", "description": "Sample dataset"} in result
    finally:
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()


@pytest.mark.asyncio
async def test_chatbot_integration_stdio(
    sample_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # conftest.py handles ANTHROPIC_API_KEY, USE_ANTHROPIC_IN_TEST.
    # TEST_INTEGRATION_VERBOSE is also loaded by conftest, but we explicitly set it to "1"
    # here to ensure verbosity for this specific test, overriding any .env setting.
    monkeypatch.setenv("TEST_INTEGRATION_VERBOSE", "1")
    monkeypatch.setenv("CSV_SOURCES_CONFIG_PATH", str(sample_config))
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")

    # StdioServerParameters will use os.environ.copy() by default if env=None,
    # or we can pass it explicitly. Since conftest and monkeypatch modify os.environ
    # for the pytest process, these will be inherited.
    stdio_env = os.environ.copy()

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "upphandlat_mcp"],
        env=stdio_env, # Pass the current environment
    )
    async with stdio_client(server_params) as (read_stream, write_stream):
        result = await run_chat_session_stdio(read_stream, write_stream)
        assert {"name": "sample", "description": "Sample dataset"} in result
