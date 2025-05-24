import contextlib
from collections.abc import AsyncIterator

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route

mcp = FastMCP("SimpleChat", stateless_http=True, json_response=True)


@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back to the caller."""
    return f"You said: {message}"


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


def serve_index(request):
    return FileResponse("chat_client.html")


app = Starlette(
    routes=[Route("/", serve_index), Mount("/mcp", app=mcp.streamable_http_app())],
    lifespan=lifespan,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
