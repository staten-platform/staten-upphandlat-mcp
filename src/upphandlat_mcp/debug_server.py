"""Example server mounting the upphandlat MCP application with debugging."""

import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.requests import Request

from upphandlat_mcp.server import mcp

# Set up more detailed logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


async def serve_index(request) -> FileResponse:
    """Return the static chat client."""
    html_path = Path(__file__).with_name("chat_client.html")
    return FileResponse(html_path)


async def debug_endpoint(request: Request):
    """Debug endpoint to see what's happening."""
    logger.info(f"Debug endpoint hit: {request.method} {request.url}")
    logger.info(f"Headers: {dict(request.headers)}")
    
    if request.method == "POST":
        try:
            body = await request.body()
            logger.info(f"Body: {body}")
        except Exception as e:
            logger.error(f"Error reading body: {e}")
    
    return JSONResponse({
        "message": "Debug endpoint",
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path
    })


# Create the MCP HTTP app
mcp_http_app = mcp.streamable_http_app()

# Log the MCP app details
logger.info(f"MCP app type: {type(mcp_http_app)}")
logger.info(f"MCP app attributes: {dir(mcp_http_app)}")

app = Starlette(
    routes=[
        Route("/", serve_index), 
        Route("/debug", debug_endpoint, methods=["GET", "POST"]),
        Mount("/mcp", app=mcp_http_app)
    ],
    lifespan=lifespan,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="debug")