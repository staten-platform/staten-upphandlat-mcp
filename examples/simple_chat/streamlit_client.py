"""Simple Streamlit client for chatting with the SimpleChat server."""

from __future__ import annotations

import httpx
import streamlit as st

API_URL = "http://localhost:8000/mcp"

st.title("Simple MCP Chat")

if "history" not in st.session_state:
    st.session_state.history = []

for speaker, text in st.session_state.history:
    st.markdown(f"**{speaker}:** {text}")

message = st.text_input("Message", key="message")

if st.button("Send") and message:
    st.session_state.history.append(("You", message))
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "call_tool",
        "params": {"name": "echo", "arguments": {"message": message}},
    }
    response = httpx.post(API_URL, json=payload, timeout=10.0)
    data = response.json()
    reply = data["result"]["content"][0]["text"]
    st.session_state.history.append(("Server", reply))
    st.experimental_rerun()
