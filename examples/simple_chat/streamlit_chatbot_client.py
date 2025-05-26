"""Streamlit chat client with optional Anthropic MCP integration."""

from __future__ import annotations

import asyncio
import os
from typing import Any

try:  # Anthropic SDK is optional
    from anthropic import Anthropic  # type: ignore
except Exception:  # pragma: no cover - Anthropic may not be installed
    Anthropic = None

import streamlit as st
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp/")
API_KEY = os.getenv("ANTHROPIC_API_KEY")


def fallback_select_tool(message: str) -> tuple[str, dict[str, Any]] | None:
    """Very naive tool selection used when Anthropic is not configured."""
    if "dataframe" in message.lower():
        return ("list_available_dataframes", {})
    return None


async def call_tool(tool: str, args: dict[str, Any]) -> list[str]:
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return [
                item.text if hasattr(item, "text") else str(item)
                for item in result.content
            ]


def anthropic_query(message: str) -> str | None:
    """Use Anthropic's MCP connector to answer the question."""

    if Anthropic is None or not API_KEY:
        return None
    try:
        client = Anthropic(api_key=API_KEY)
        resp = client.beta.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": message}],
            mcp_servers=[{"type": "url", "url": MCP_URL, "name": "upphandlat"}],
            betas=["mcp-client-2025-04-04"],
        )
    except Exception:  # noqa: BLE001
        return None

    outputs: list[str] = []
    for block in resp.content:
        if block.type == "mcp_tool_result":
            for item in block.content:
                if item.type == "text":
                    outputs.append(item.text)
        elif block.type == "text":
            outputs.append(block.text)
    return "\n".join(outputs) if outputs else None


st.title("Upphandlat MCP Chatbot")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if user_input := st.chat_input("Ask something about the data..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)
    reply = anthropic_query(user_input)
    if reply is None:
        tool_call = fallback_select_tool(user_input)
        if tool_call is None:
            reply = "Sorry, I don't understand."
        else:
            output = asyncio.run(call_tool(*tool_call))
            reply = "\n".join(output)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").write(reply)
