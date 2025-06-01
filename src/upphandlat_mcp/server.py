"""MCP server configuration and startup."""

import logging
import os
from typing import Literal

from upphandlat_mcp.core.config import settings as app_settings

# Set multiple port-related environment variables before importing FastMCP
# This ensures FastMCP reads the correct port at instantiation time
port_str = str(app_settings.MCP_PORT)
os.environ["PORT"] = port_str
os.environ["UVICORN_PORT"] = port_str
os.environ["HOST"] = "127.0.0.1"
os.environ["UVICORN_HOST"] = "127.0.0.1"

from mcp.server.fastmcp import FastMCP
from upphandlat_mcp.lifespan.context import app_lifespan
from upphandlat_mcp.tools.aggregation_tools import aggregate_data
from upphandlat_mcp.tools.info_tools import (
    fuzzy_search_column_values,
    get_distinct_column_values,
    get_schema,
    list_available_dataframes,
    list_columns,
)

logger = logging.getLogger(__name__)

# Log port configuration at module level to help debug FastMCP instantiation
logger.info(
    f"[SERVER.PY TOP LEVEL] os.environ['PORT'] before FastMCP instantiation: {os.getenv('PORT')}"
)
logger.info(
    f"[SERVER.PY TOP LEVEL] os.environ['UVICORN_PORT'] before FastMCP instantiation: {os.getenv('UVICORN_PORT')}"
)
logger.info(
    f"[SERVER.PY TOP LEVEL] app_settings.MCP_PORT before FastMCP instantiation: {app_settings.MCP_PORT}"
)

mcp = FastMCP(
    name="UpphandlatMultiCSV_MCP",
    description=(
        "A server for querying and aggregating data from multiple CSV files "
        "(loaded via URLs) using Polars."
    ),
    lifespan=app_lifespan,
    json_response=True,
    stateless_http=True,
)

mcp.tool()(list_available_dataframes)
mcp.tool()(list_columns)
mcp.tool()(get_schema)
mcp.tool()(get_distinct_column_values)
mcp.tool()(fuzzy_search_column_values)
mcp.tool()(aggregate_data)


def run_mcp() -> None:
    """Run the MCP server using the configured transport."""

    transport_str: str = app_settings.MCP_TRANSPORT
    
    # Type-safe transport validation
    valid_transports = {"stdio", "sse", "streamable-http"}
    if transport_str not in valid_transports:
        err_msg = f"Invalid transport '{transport_str}'. Must be one of: {valid_transports}"
        logger.critical(err_msg)
        raise ValueError(err_msg)

    transport: Literal["stdio", "sse", "streamable-http"] = transport_str  # type: ignore[assignment]

    logger.info(f"Starting MCP server '{mcp.name}' on {transport}...")
    
    # Log current environment state for PORT before deciding how to run
    logger.info(f"[run_mcp PRE-RUN] os.environ['PORT'] from env: {os.getenv('PORT')}")
    logger.info(f"[run_mcp PRE-RUN] app_settings.MCP_PORT from config: {app_settings.MCP_PORT}")

    try:
        if transport == "streamable-http":
            logger.info(f"Using {transport} transport on port {app_settings.MCP_PORT}")
            # PORT environment variable was already set at module level before FastMCP instantiation
            mcp.run(transport=transport)
        else:
            # For stdio or other transports, host/port are not typically passed to run()
            logger.info(f"Using {transport} transport (no port needed)")
            mcp.run(transport=transport)
        
        logger.info(f"MCP server '{mcp.name}' finished running.")  # This logs on graceful shutdown
    except Exception as e:  # noqa: BLE001
        logger.critical(
            f"MCP server '{mcp.name}' crashed: {e}",
            exc_info=True,
        )
        raise
