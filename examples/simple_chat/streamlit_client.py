import httpx
import streamlit as st

st.title("Simple MCP Chat")

# Initialize message history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous messages
for sender, text in st.session_state.messages:
    with st.chat_message(sender):
        st.write(text)

prompt = st.chat_input("Say something")
if prompt:
    # Add user message
    st.session_state.messages.append(("user", prompt))
    with st.chat_message("user"):
        st.write(prompt)

    with st.spinner("Waiting for response..."):
        res = httpx.post(
            "http://localhost:8000/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "call_tool",
                "params": {"name": "echo", "arguments": {"message": prompt}},
            },
            timeout=10.0,
        )
        data = res.json()
        reply = data["result"]["content"][0]["text"]

    # Add server message
    st.session_state.messages.append(("server", reply))
    with st.chat_message("server"):
        st.write(reply)

    st.rerun()

