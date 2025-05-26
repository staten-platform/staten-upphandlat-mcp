"""Streamlit chat interface using an LLM to call MCP tools."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import streamlit as st
from anthropic import Anthropic
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp/")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_NAME = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "512"))


def _choose_tool_llm(message: str) -> tuple[str, dict[str, Any]] | None:
    """Use Anthropic to decide which tool to call for the message."""
    if not ANTHROPIC_KEY:
        return None

    tools_def = [
        {
            "name": "list_available_dataframes",
            "description": "Get available dataframes",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_columns",
            "description": "Get column names of a dataframe",
            "input_schema": {
                "type": "object",
                "properties": {"dataframe_name": {"type": "string"}},
            },
        },
        {
            "name": "get_schema",
            "description": "Get dataframe schema",
            "input_schema": {
                "type": "object",
                "properties": {"dataframe_name": {"type": "string"}},
            },
        },
        {
            "name": "aggregate_data",
            "description": "Aggregate dataframe with filters",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]

    client = Anthropic()
    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system=(
                "Decide which tool to call based on the user's request "
                "and return only the tool call."
            ),
            messages=[{"role": "user", "content": message}],
            tools=tools_def,
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Anthropic call failed: {exc}")
        return None

    if response.stop_reason == "tool_use":
        for block in response.content:
            if block.type == "tool_use":
                return block.name, block.input
    return None


def select_tool(message: str) -> tuple[str, dict[str, Any]] | None:
    """Select a tool for the given chat message."""
    tool = _choose_tool_llm(message)
    if tool is not None:
        return tool
    if "dataframe" in message.lower():
        return ("list_available_dataframes", {})
    return None


async def call_tool(tool: str, args: dict[str, Any]) -> list[str]:
    """Execute the selected tool and return text outputs."""
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return [
                item.text if hasattr(item, "text") else str(item)
                for item in result.content
            ]


st.title("Upphandlat MCP Chatbot")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if user_input := st.chat_input("Ask something about the data..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)
    tool_call = select_tool(user_input)
    if tool_call is None:
        reply = "Sorry, I don't understand."
    else:
        output = asyncio.run(call_tool(*tool_call))
        reply = "\n".join(output)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").write(reply)

