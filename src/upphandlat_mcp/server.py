"""MCP server configuration and startup."""

import logging
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
        raise ValueError(
            f"Invalid transport '{transport_str}'. Must be one of: {valid_transports}"
        )

    transport: Literal["stdio", "sse", "streamable-http"] = transport_str  # type: ignore[assignment]

    if transport == "streamable-http":
        logger.info(f"Starting MCP server '{mcp.name}' on {transport} (port {app_settings.MCP_PORT})...")
        try:
            mcp.run(transport=transport, port=app_settings.MCP_PORT)
            logger.info(f"MCP server '{mcp.name}' finished running.")
        except Exception as e:  # noqa: BLE001
            logger.critical(
                f"MCP server '{mcp.name}' crashed: {e}",
                exc_info=True,
            )
            raise
    else:
        logger.info(f"Starting MCP server '{mcp.name}' on {transport}...")
        try:
            mcp.run(transport=transport)
            logger.info(f"MCP server '{mcp.name}' finished running.")
        except Exception as e:  # noqa: BLE001
            logger.critical(
                f"MCP server '{mcp.name}' crashed: {e}",
                exc_info=True,
            )
            raise
