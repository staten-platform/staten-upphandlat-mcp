"""Example server mounting the upphandlat MCP application."""

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route

from upphandlat_mcp.debug_server import mcp


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


async def serve_index(request) -> FileResponse:
    """Return the static chat client."""
    html_path = Path(__file__).with_name("chat_client.html")
    return FileResponse(html_path)


app = Starlette(
    routes=[Route("/", serve_index), Mount("/mcp", app=mcp.streamable_http_app())],
    lifespan=lifespan,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
