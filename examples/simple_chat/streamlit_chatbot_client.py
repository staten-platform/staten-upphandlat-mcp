"""Minimal Streamlit chat client for the Upphandlat MCP server.

This example connects to the MCP server via Streamable HTTP and allows a user
to chat with the data tools. If the environment variable ``ANTHROPIC_API_KEY``
is set, the client uses Anthropic's MCP connector to automatically choose the
appropriate tool based on the user input. Otherwise it falls back to a simple
heuristic implemented in :func:`select_tool`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import anthropic
import streamlit as st
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp/")
API_KEY = os.getenv("ANTHROPIC_API_KEY")
anthropic_client = anthropic.Anthropic(api_key=API_KEY) if API_KEY else None


def select_tool(message: str) -> tuple[str, dict[str, Any]] | None:
    """Choose a tool based on the message."""
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


def ask_claude(query: str) -> list[str] | None:
    """Send the user query to Anthropic using the MCP connector."""

    if anthropic_client is None:
        return None

    try:
        response = anthropic_client.beta.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": query}],
            mcp_servers=[{
                "type": "url",
                "url": MCP_URL,
                "name": "upphandlat-mcp",
            }],
            betas=["mcp-client-2025-04-04"],
        )
    except anthropic.APIError as exc:  # noqa: BLE001
        return [f"Anthropic API error: {exc}"]

    outputs: list[str] = []
    for block in response.content:
        if block.type == "text":
            outputs.append(block.text)
        elif block.type == "mcp_tool_result":
            for content in block.content:
                if content.type == "text":
                    outputs.append(content.text)
    return outputs


st.title("Upphandlat MCP Chatbot")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if user_input := st.chat_input("Ask something about the data..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)

    output = ask_claude(user_input)
    if output is None:
        tool_call = select_tool(user_input)
        if tool_call is None:
            reply = "Sorry, I don't understand."
        else:
            output = asyncio.run(call_tool(*tool_call))
            reply = "\n".join(output)
    else:
        reply = "\n".join(output)

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").write(reply)
