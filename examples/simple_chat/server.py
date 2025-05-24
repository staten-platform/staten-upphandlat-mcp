"""Minimal Streamable HTTP server for chatting with Streamlit."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SimpleChat", stateless_http=True, json_response=True)


@mcp.tool()
def echo(message: str) -> str:
    """Return the given message prefixed with ``"You said:"``."""

    return f"You said: {message}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
