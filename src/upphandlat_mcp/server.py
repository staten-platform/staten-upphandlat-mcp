"""MCP server configuration and startup."""

import logging
import os
from typing import Literal

from mcp.server.fastmcp import FastMCP
from upphandlat_mcp.core.config import settings as app_settings
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
            host_to_use = "127.0.0.1"  # Standard loopback address
            port_to_use = app_settings.MCP_PORT  # Should be 8001 from .env

            # Explicitly set/update PORT environment variable immediately before run.
            # This is crucial if FastMCP.run() or its internal Uvicorn call relies on it at this point.
            os.environ["PORT"] = str(port_to_use)
            logger.info(
                f"Attempting to run on host '{host_to_use}', port {port_to_use} for {transport} transport. "
                f"os.environ['PORT'] explicitly set to '{os.getenv('PORT')}'."
            )
            
            try:
                # Attempt to pass host and port directly to mcp.run()
                # This is the most explicit way if supported.
                mcp.run(transport=transport, host=host_to_use, port=port_to_use)
            except TypeError as te:
                # Handle cases where host/port kwargs are not accepted by FastMCP.run()
                if "unexpected keyword argument 'host'" in str(te) or \
                   "unexpected keyword argument 'port'" in str(te):
                    logger.warning(
                        f"FastMCP.run() does not accept host/port kwargs. Detail: {te}. "
                        f"Falling back to relying on PORT environment variable (currently: {os.getenv('PORT')})."
                    )
                    # Fallback: Rely on PORT environment variable being picked up by Uvicorn internally
                    mcp.run(transport=transport)
                else:
                    # Re-raise if TypeError is for something else not anticipated
                    logger.critical(f"MCP server '{mcp.name}' crashed with an unexpected TypeError: {te}", exc_info=True)
                    raise
        else:
            # For stdio or other transports, host/port are not typically passed to run()
            logger.info(f"Using {transport} transport (no host/port applicable for mcp.run method)")
            mcp.run(transport=transport)
        
        logger.info(f"MCP server '{mcp.name}' finished running.")  # This logs on graceful shutdown
    except Exception as e:  # noqa: BLE001
        logger.critical(
            f"MCP server '{mcp.name}' crashed: {e}",
            exc_info=True,
        )
        raise
