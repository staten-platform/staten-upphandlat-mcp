"""Very small chat interface with naive tool selection."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import streamlit as st
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp/")


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
            return [item.text if hasattr(item, "text") else str(item) for item in result.content]


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
