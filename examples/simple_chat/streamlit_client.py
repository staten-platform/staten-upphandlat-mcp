"""Streamlit client for interacting with the upphandlat MCP server."""

import json
import os

import httpx
import streamlit as st

st.title("Upphandlat MCP Client")

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp/")

if "messages" not in st.session_state:
    st.session_state.messages = []

for sender, text in st.session_state.messages:
    with st.chat_message(sender):
        st.write(text)

with st.form("tool_form"):
    tool_name = st.text_input("Tool name")
    args_text = st.text_area("Arguments (JSON)", "{}")
    submitted = st.form_submit_button("Call tool")

if submitted and tool_name:
    try:
        args = json.loads(args_text or "{}")
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
    else:
        user_msg = f"call_tool {tool_name} {args}".strip()
        st.session_state.messages.append(("user", user_msg))
        with st.chat_message("user"):
            st.write(user_msg)

        with st.spinner("Waiting for response..."):
            try:
                response = httpx.post(
                    MCP_URL,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "call_tool",
                        "params": {"name": tool_name, "arguments": args},
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                try:
                    reply = response.json().get("result")
                except json.JSONDecodeError as exc:
                    reply = (
                        f"Server returned invalid JSON: {exc}.\n"
                        f"Raw content: {response.text}"
                    )
            except httpx.HTTPError as exc:
                reply = f"Request failed: {exc}"

        st.session_state.messages.append(("server", str(reply)))
        with st.chat_message("server"):
            st.write(reply)

        st.rerun()

