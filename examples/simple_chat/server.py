"""Example Streamable HTTP server for Upphandlat MCP."""

from __future__ import annotations

import os

from upphandlat_mcp.server import run_mcp


if __name__ == "__main__":
    os.environ.setdefault("MCP_TRANSPORT", "streamable-http")
    run_mcp()
