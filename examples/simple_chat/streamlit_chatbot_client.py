import json
import os
from typing import Any

import httpx
import streamlit as st

try:
    from anthropic import Anthropic, APIError
except Exception:  # pragma: no cover - anthropic might not be installed
    Anthropic = None  # type: ignore
    APIError = Exception  # type: ignore


class LLMClient:
    """Simple LLM client that can use Anthropic if configured."""

    def __init__(self) -> None:
        self.use_anthropic = (
            os.getenv("USE_ANTHROPIC_IN_TEST") == "1" and os.getenv("ANTHROPIC_API_KEY")
        )
        self.client = Anthropic() if self.use_anthropic and Anthropic else None

    def get_response(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        if self.client:
            system = next(
                (m["content"] for m in messages if m["role"] == "system"),
                None,
            )
            chat_messages = [m for m in messages if m["role"] != "system"]
            try:
                resp = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    messages=chat_messages,
                    system=system,
                    tools=tools if tools is not None else None,
                )
                if resp.stop_reason == "tool_use":
                    for block in resp.content:
                        if block.type == "tool_use":
                            return json.dumps(
                                {
                                    "tool": block.name,
                                    "arguments": block.input,
                                }
                            )
                if resp.content and resp.content[0].type == "text":
                    return resp.content[0].text
            except APIError:
                pass
            except Exception:
                pass
        return json.dumps({"tool": "list_available_dataframes", "arguments": {}})


MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp")

st.title("Upphandlat MCP Chatbot Client")

if "tool_names" not in st.session_state:
    try:
        res = httpx.post(
            MCP_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "list_tools"},
            timeout=10.0,
        )
        tool_data = res.json()["result"]["tools"]
        st.session_state.tool_names = [t["name"] for t in tool_data]
    except Exception as exc:
        st.error(f"Failed to fetch tools from MCP server: {exc}")
        st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

prompt = st.chat_input("Ask about the data")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    llm_client = LLMClient()
    system_msg = {
        "role": "system",
        "content": f"Tools available: {', '.join(st.session_state.tool_names)}",
    }
    tools_param = [
        {"name": name, "input_schema": {"type": "object", "properties": {}}}
        for name in st.session_state.tool_names
    ]
    resp_text = llm_client.get_response(
        [system_msg, {"role": "user", "content": prompt}], tools=tools_param
    )
    try:
        tool_call = json.loads(resp_text)
    except json.JSONDecodeError:
        tool_call = {}

    if tool_call.get("tool"):
        with st.spinner(f"Calling {tool_call['tool']}..."):
            try:
                call_res = httpx.post(
                    MCP_URL,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "call_tool",
                        "params": {
                            "name": tool_call["tool"],
                            "arguments": tool_call.get("arguments", {}),
                        },
                    },
                    timeout=30.0,
                )
                assistant_msg = call_res.json().get("result")
            except Exception as exc:
                assistant_msg = f"Tool call failed: {exc}"
    else:
        assistant_msg = f"LLM did not return a tool call: {resp_text}"

    st.session_state.messages.append(
        {"role": "assistant", "content": str(assistant_msg)}
    )
    with st.chat_message("assistant"):
        st.write(assistant_msg)
    st.rerun()
