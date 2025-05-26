"""Manual Streamlit client for the Upphandlat MCP server."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import streamlit as st
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp/")


def fetch_tools() -> list[str]:
    """Fetch tool names from the server."""

    async def _get() -> list[str]:
        async with streamablehttp_client(MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]

    return asyncio.run(_get())


def execute_tool(name: str, args: dict[str, Any]) -> list[str]:
    """Execute a tool on the server and return text outputs."""

    async def _call() -> list[str]:
        async with streamablehttp_client(MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
                outputs: list[str] = []
                for item in result.content:
                    outputs.append(item.text if hasattr(item, "text") else str(item))
                return outputs

    return asyncio.run(_call())


st.title("Upphandlat MCP Streamlit Client")

tool_names = fetch_tools()
selected_tool = st.selectbox("Tool", tool_names)
args_json = st.text_area("Arguments (JSON)", "{}")
if st.button("Run"):
    try:
        arguments = json.loads(args_json) if args_json.strip() else {}
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
    else:
        results = execute_tool(selected_tool, arguments)
        st.write("Result:")
        for block in results:
            st.write(block)
