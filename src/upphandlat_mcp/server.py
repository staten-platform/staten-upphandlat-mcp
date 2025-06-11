"""
Upphandlat MCP Server: Main application entry point and health checks.
"""

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
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
    description="A server for querying and aggregating data from multiple CSV files.",
    lifespan=app_lifespan,
    json_response=True,
    stateless_http=True,
)
app = mcp.streamable_http_app()


async def health_check(request: Request) -> JSONResponse:
    """A simple health check endpoint that returns a 200 OK response."""
    return JSONResponse({"status": "ready"})


app.add_route("/health/ready", health_check, methods=["GET"])

mcp.tool()(list_available_dataframes)
mcp.tool()(list_columns)
mcp.tool()(get_schema)
mcp.tool()(get_distinct_column_values)
mcp.tool()(fuzzy_search_column_values)
mcp.tool()(aggregate_data)


def main() -> None:
    """
    Main entry point, primarily for local development using `stdio` transport.

    In a production Docker environment, this function is NOT called.
    Instead, `uvicorn` is invoked directly in the Dockerfile's CMD.
    """
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()

    if transport == "stdio":
        logging.info("[Upphandlat MCP] Starting in stdio mode.")
        mcp.run(transport="stdio")
    else:
        port = os.getenv("PORT", "8005")
        print(
            f"\n[Upphandlat MCP] To run in HTTP mode, use the 'uvicorn' command:\n"
            f"uvicorn upphandlat_mcp.server:app --host 0.0.0.0 --port {port}\n",
            file=sys.stderr,
        )


def run_mcp():
    main()


if __name__ == "__main__":
    main()
