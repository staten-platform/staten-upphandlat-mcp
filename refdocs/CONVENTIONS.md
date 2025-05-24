# MCP Python Server Conventions - Streamable HTTP Transport

This document provides style and design conventions for writing Python MCP servers using the **streamable HTTP transport protocol** with the latest MCP Python SDK.

----

## Table of Contents

1. [Environment](#environment)  
2. [General Principles](#general-principles)  
3. [Design Principles for MCP Servers](#design-principles-for-mcp-servers)  
4. [Coding Standards](#coding-standards)  
   - [Type Hints](#type-hints)  
   - [Docstrings](#docstrings)  
   - [Naming Conventions](#naming-conventions)  
5. [MCP Server Structure](#mcp-server-structure)  
   - [Server Initialization](#server-initialization)  
   - [Tools](#tools)  
   - [Resources](#resources)  
   - [Prompts](#prompts)  
   - [Lifespan and Context](#lifespan-and-context)  
6. [FastMCP vs Low-Level Servers](#fastmcp-vs-low-level-servers)
7. [Streamable HTTP Specifics](#streamable-http-specifics)
8. [Async Concurrency](#async-concurrency)  
9. [Testing and Quality](#testing-and-quality)  
10. [Logging and Observability](#logging-and-observability)  
11. [Security and Validation](#security-and-validation)  
12. [Deployment and CLI Integration](#deployment-and-cli-integration)
13. [Additional Tips](#additional-tips)  

----

## 1. Environment

- **Python Version**: Target Python **3.10+** (3.13 recommended)
- **Required Libraries**:  
  - [`mcp` Python SDK](https://modelcontextprotocol.io/) with CLI support: `pip install "mcp[cli]"`
- **Recommended Package Manager**: [`uv`](https://docs.astral.sh/uv/) for dependency management
- **Optional Libraries**:  
  - [`pydantic`](https://docs.pydantic.dev/) (Version **2.x**) for data validation
  - [`starlette`](https://www.starlette.io/) for custom ASGI applications
  - [`uvicorn`](https://www.uvicorn.org/) for production ASGI serving

**Setup with uv**:
```bash
uv init my-mcp-server
cd my-mcp-server
uv add "mcp[cli]"
uv add pydantic  # Optional for validation
```

**Setup with pip**:
```bash
pip install "mcp[cli]" pydantic
```

----

## 2. General Principles

1. **Keep it Simple**: MCP servers should be easily discoverable by LLMs and straightforward to use
2. **Follow PEP 8**: Use standard Python style for readability and consistency  
3. **Leverage Async**: Streamable HTTP is inherently asynchronous - embrace `async/await`
4. **Stateless First**: Design for stateless operation to maximize streamable HTTP scalability benefits
5. **Use FastMCP by Default**: Start with FastMCP for rapid development, use low-level servers only when needed
6. **Document Thoroughly**: Write clear docstrings - LLMs rely on these for understanding
7. **CLI-First Development**: Use `mcp dev` and `mcp install` for development and deployment

----

## 3. Design Principles for MCP Servers

### 3.1 Favor Composition Over Inheritance

- Use FastMCP decorators (`@mcp.tool()`, `@mcp.resource()`) rather than complex inheritance
- Create small, composable utility functions and classes
- Leverage dependency injection through lifespan context

### 3.2 High Cohesion, Low Coupling

- Each tool, resource, or prompt should handle a single responsibility
- Use typed context objects to share state between components
- Separate business logic from MCP protocol concerns

### 3.3 Start with the Data (When Needed)

- Use Pydantic models for complex argument validation
- Leverage Python's type system for automatic validation in FastMCP

### 3.4 Depend on Abstractions

- Use lifespan context for shared resources (databases, HTTP clients)
- Define Protocol interfaces for external dependencies
- Keep tools pure and testable

### 3.5 Separate Creation from Use

- Initialize resources in lifespan managers
- Inject dependencies through context
- Maintain clean separation between setup and execution

----

## 4. Coding Standards

### 4.1 Type Hints

1. **Use built-in generics**: `list[str]`, `dict[str, float]`, `tuple[int, str]`
2. **Import from `typing`** for Protocols, Callable, TypeVar, etc.
3. **Use `|` for union types**: `str | None`
4. **Annotate all function parameters and return types**
5. **Use Context type hints** for FastMCP context access

<details>
<summary>Example</summary>

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from mcp.server.fastmcp import FastMCP, Context

@dataclass
class AppContext:
    api_key: str
    base_url: str

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Initialize application context."""
    yield AppContext(api_key="key", base_url="https://api.example.com")

mcp = FastMCP("My Server", lifespan=app_lifespan)

@mcp.tool()
async def fetch_data(query: str, ctx: Context) -> str:
    """Fetch data from external API."""
    app_ctx = ctx.request_context.lifespan_context
    # Use app_ctx.api_key and app_ctx.base_url
    return f"Data for {query}"
```
</details>

### 4.2 Docstrings

- Use [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings) consistently
- For **Tools** and **Resources**, docstrings are critical for LLM understanding
- Include parameter descriptions and usage examples

<details>
<summary>Example</summary>

```python
@mcp.tool()
async def calculate_bmi(weight_kg: float, height_m: float) -> float:
    """
    Calculate Body Mass Index from weight and height.
    
    This tool computes BMI using the standard formula: weight (kg) / height (m)².
    The result helps assess whether a person has a healthy body weight.

    Args:
        weight_kg: Weight in kilograms (e.g., 70.5)
        height_m: Height in meters (e.g., 1.75)

    Returns:
        BMI value as a float (e.g., 22.9)
        
    Example:
        BMI for 70kg, 1.75m person = 22.86
    """
    return weight_kg / (height_m ** 2)
```
</details>

### 4.3 Naming Conventions

- **Modules**: `snake_case` (e.g., `weather_tools.py`, `db_resources.py`)
- **Classes**: `PascalCase` (e.g., `WeatherService`, `AppContext`)
- **Functions**: `snake_case` (e.g., `fetch_weather`, `calculate_total`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`, `API_BASE_URL`)
- **MCP Entities**:  
  - Tools: `snake_case` with `@mcp.tool()` decorator
  - Resources: descriptive URIs like `weather://current/{city}`
  - Prompts: `snake_case` with `@mcp.prompt()` decorator

----

## 5. MCP Server Structure

### Recommended Streamable HTTP Project Structure

```
my_mcp_server/
├── pyproject.toml           # Project configuration with MCP dependencies
├── server.py                # Main FastMCP server entry point
├── tools/                   # Each tool as its own module
│   ├── __init__.py
│   ├── get_weather.py       # Individual tool: get_weather
│   ├── calculate_bmi.py     # Individual tool: calculate_bmi
│   ├── fetch_data.py        # Individual tool: fetch_data
│   └── search_web.py        # Individual tool: search_web
├── resources/               # Each resource as its own module
│   ├── __init__.py
│   ├── server_config.py     # Individual resource: config://server
│   ├── user_profile.py      # Individual resource: user://{id}/profile
│   └── system_stats.py      # Individual resource: stats://current
├── prompts/                 # Each prompt as its own module
│   ├── __init__.py
│   ├── code_review.py       # Individual prompt: code_review
│   ├── debug_session.py     # Individual prompt: debug_session
│   └── api_documentation.py # Individual prompt: api_documentation
├── services/                # Business logic and external integrations
│   ├── __init__.py
│   ├── weather_service.py   # Weather API integration
│   ├── database_service.py  # Database operations
│   ├── http_service.py      # HTTP client operations
│   └── auth_service.py      # Authentication logic
└── tests/
    ├── __init__.py
    ├── test_tools/
    │   ├── test_get_weather.py
    │   └── test_calculate_bmi.py
    ├── test_resources/
    │   └── test_server_config.py
    ├── test_services/
    │   ├── test_weather_service.py
    │   └── test_database_service.py
    └── test_server.py
```

### 5.1 Server Initialization

**FastMCP (Recommended)**:

<details>
<summary>Simple Server Example</summary>

```python
# server.py
from mcp.server.fastmcp import FastMCP

# Create server with dependencies declared for CLI tools
mcp = FastMCP("Weather Server", dependencies=["httpx", "pydantic"])

@mcp.tool()
def get_temperature(city: str, unit: str = "celsius") -> str:
    """Get current temperature for a city."""
    # Mock implementation
    temp = 22 if unit == "celsius" else 72
    return f"Temperature in {city}: {temp}°{'C' if unit == 'celsius' else 'F'}"

@mcp.resource("weather://{city}")
def weather_data(city: str) -> str:
    """Get weather data for a city."""
    return f"Weather data for {city}: sunny, 22°C"

# CLI integration: run with `mcp dev server.py`
if __name__ == "__main__":
    mcp.run()
```
</details>

**FastMCP with Modular Registration**:

<details>
<summary>Server with Modular Components</summary>

```python
# server.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import httpx
from mcp.server.fastmcp import FastMCP, Context

# Import modular components
from tools import get_weather, calculate_bmi, fetch_data
from resources import server_config, user_profile, system_stats
from prompts import code_review, debug_session, api_documentation
from services.database_service import DatabaseService

@dataclass
class AppContext:
    """Application context with shared resources."""
    http_client: httpx.AsyncClient
    database: DatabaseService
    api_key: str

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle."""
    # Startup
    http_client = httpx.AsyncClient(timeout=30.0)
    database = DatabaseService()
    await database.connect()
    
    try:
        yield AppContext(
            http_client=http_client,
            database=database,
            api_key="your-api-key"
        )
    finally:
        # Shutdown
        await http_client.aclose()
        await database.disconnect()

# Create FastMCP server
mcp = FastMCP("Modular Weather Server", lifespan=app_lifespan)

# Register tools (each from its own module)
mcp.tool()(get_weather)
mcp.tool()(calculate_bmi)
mcp.tool()(fetch_data)

# Register resources (each from its own module)
mcp.resource("config://server")(server_config)
mcp.resource("user://{user_id}/profile")(user_profile)
mcp.resource("stats://current")(system_stats)

# Register prompts (each from its own module)
mcp.prompt()(code_review)
mcp.prompt()(debug_session)
mcp.prompt()(api_documentation)

# CLI integration
if __name__ == "__main__":
    mcp.run()
```
</details>

**Service Layer Example**:

<details>
<summary>Service Module Structure</summary>

```python
# services/weather_service.py
import httpx
from typing import Dict, Any

class WeatherService:
    """Service for weather API integration."""
    
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client
        self.base_url = "https://api.weather.com/v1"
    
    async def get_current_weather(self, city: str, units: str = "metric") -> Dict[str, Any]:
        """Get current weather for a city."""
        params = {
            "city": city,
            "units": units,
            "appid": "your-api-key"
        }
        
        response = await self.http_client.get(
            f"{self.base_url}/current",
            params=params
        )
        response.raise_for_status()
        
        data = response.json()
        return {
            "city": data["name"],
            "temperature": data["main"]["temp"],
            "description": data["weather"][0]["description"],
            "humidity": data["main"]["humidity"],
            "wind_speed": data["wind"]["speed"]
        }
```

```python
# services/database_service.py
import asyncpg
from typing import Dict, Any, Optional

class DatabaseService:
    """Service for database operations."""
    
    def __init__(self):
        self.connection = None
    
    async def connect(self):
        """Connect to the database."""
        self.connection = await asyncpg.connect("postgresql://localhost/mydb")
    
    async def disconnect(self):
        """Disconnect from the database."""
        if self.connection:
            await self.connection.close()
    
    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile by ID."""
        query = "SELECT * FROM users WHERE id = $1"
        row = await self.connection.fetchrow(query, user_id)
        
        if row:
            return dict(row)
        return None
```

```python
# services/__init__.py
"""Service module exports."""

from .weather_service import WeatherService
from .database_service import DatabaseService

__all__ = ["WeatherService", "DatabaseService"]
```
</details>

### 5.2 Tools

Each tool should be in its own module for better organization and testability:

<details>
<summary>Tool Module Examples</summary>

```python
# tools/get_weather.py
from mcp.server.fastmcp import Context
from ..services.weather_service import WeatherService

async def get_weather(city: str, units: str = "metric", ctx: Context) -> str:
    """
    Get current weather conditions for a city.
    
    Fetches real-time weather data including temperature, humidity,
    wind speed, and general conditions.
    
    Args:
        city: City name (e.g., "London", "New York")
        units: "metric" for Celsius, "imperial" for Fahrenheit
        
    Returns:
        Formatted weather information
    """
    ctx.info(f"Fetching weather for {city}")
    
    weather_service = WeatherService(ctx.request_context.lifespan_context.http_client)
    
    try:
        weather_data = await weather_service.get_current_weather(city, units)
        
        return f"""Weather in {weather_data['city']}:
Temperature: {weather_data['temperature']}°{'C' if units == 'metric' else 'F'}
Conditions: {weather_data['description']}
Humidity: {weather_data['humidity']}%
Wind: {weather_data['wind_speed']} {'m/s' if units == 'metric' else 'mph'}"""
        
    except Exception as e:
        ctx.error(f"Failed to fetch weather for {city}: {e}")
        return f"Error fetching weather: {str(e)}"
```

```python
# tools/calculate_bmi.py
def calculate_bmi(weight_kg: float, height_m: float) -> float:
    """
    Calculate Body Mass Index from weight and height.
    
    This tool computes BMI using the standard formula: weight (kg) / height (m)².
    The result helps assess whether a person has a healthy body weight.

    Args:
        weight_kg: Weight in kilograms (e.g., 70.5)
        height_m: Height in meters (e.g., 1.75)

    Returns:
        BMI value as a float (e.g., 22.9)
        
    Example:
        BMI for 70kg, 1.75m person = 22.86
    """
    if weight_kg <= 0 or height_m <= 0:
        raise ValueError("Weight and height must be positive numbers")
    
    return weight_kg / (height_m ** 2)
```

```python
# tools/fetch_data.py
from mcp.server.fastmcp import Context
import httpx
from pydantic import BaseModel, HttpUrl

class FetchRequest(BaseModel):
    """Request model for data fetching."""
    url: HttpUrl
    timeout: int = 30

async def fetch_data(request: FetchRequest, ctx: Context) -> str:
    """
    Fetch data from an external URL with validation and error handling.
    
    Args:
        request: FetchRequest containing URL and optional timeout
        
    Returns:
        Response data or error message
    """
    ctx.info(f"Fetching data from {request.url}")
    
    http_client = ctx.request_context.lifespan_context.http_client
    
    try:
        response = await http_client.get(str(request.url), timeout=request.timeout)
        response.raise_for_status()
        
        ctx.info(f"Successfully fetched {len(response.content)} bytes")
        return f"Status: {response.status_code}\nContent-Type: {response.headers.get('content-type', 'unknown')}\nSize: {len(response.content)} bytes"
        
    except httpx.TimeoutException:
        ctx.error(f"Timeout fetching {request.url}")
        return "Error: Request timed out"
    except httpx.HTTPStatusError as e:
        ctx.error(f"HTTP error {e.response.status_code} for {request.url}")
        return f"Error: HTTP {e.response.status_code}"
    except Exception as e:
        ctx.error(f"Unexpected error fetching {request.url}: {e}")
        return f"Error: {str(e)}"
```

```python
# tools/__init__.py
"""Tool module exports for easy registration."""

from .get_weather import get_weather
from .calculate_bmi import calculate_bmi
from .fetch_data import fetch_data

__all__ = ["get_weather", "calculate_bmi", "fetch_data"]
```
</details>

### 5.3 Resources

Each resource should be in its own module following the same pattern:

<details>
<summary>Resource Module Examples</summary>

```python
# resources/server_config.py
import json
from ..services.config_service import ConfigService

def server_config() -> str:
    """
    Server configuration information.
    
    Returns:
        JSON-formatted server configuration
    """
    config = {
        "name": "My MCP Server",
        "version": "1.0.0",
        "transport": "streamable-http",
        "features": ["tools", "resources", "prompts"],
        "endpoints": {
            "mcp": "/mcp",
            "health": "/health"
        }
    }
    return json.dumps(config, indent=2)
```

```python
# resources/user_profile.py
import json
from mcp.server.fastmcp import Context
from ..services.database_service import DatabaseService

async def user_profile(user_id: str, ctx: Context) -> str:
    """
    Get user profile information.
    
    Args:
        user_id: Unique identifier for the user
        
    Returns:
        JSON-formatted user profile data
    """
    ctx.info(f"Fetching profile for user {user_id}")
    
    db_service = DatabaseService(ctx.request_context.lifespan_context.database)
    
    try:
        profile_data = await db_service.get_user_profile(user_id)
        
        if not profile_data:
            return json.dumps({"error": f"User {user_id} not found"})
        
        return json.dumps(profile_data, indent=2)
        
    except Exception as e:
        ctx.error(f"Failed to fetch profile for user {user_id}: {e}")
        return json.dumps({"error": "Failed to fetch user profile"})
```

```python
# resources/system_stats.py
import json
import psutil
from datetime import datetime
from mcp.server.fastmcp import Context

async def system_stats(ctx: Context) -> str:
    """
    Get current system statistics.
    
    Returns:
        JSON-formatted system statistics
    """
    ctx.info("Collecting system statistics")
    
    stats = {
        "timestamp": datetime.utcnow().isoformat(),
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        },
        "server": {
            "active_connections": 1,  # Would track real connections
            "requests_served": 100,   # Would track real metrics
            "uptime": "unknown"       # Would calculate real uptime
        }
    }
    
    return json.dumps(stats, indent=2)
```

```python
# resources/__init__.py
"""Resource module exports for easy registration."""

from .server_config import server_config
from .user_profile import user_profile
from .system_stats import system_stats

__all__ = ["server_config", "user_profile", "system_stats"]
```
</details>

### 5.4 Prompts

Each prompt should be in its own module for reusability:

<details>
<summary>Prompt Module Examples</summary>

```python
# prompts/code_review.py
def code_review(code: str, language: str = "python") -> str:
    """
    Generate a comprehensive code review prompt.
    
    Args:
        code: The code to review
        language: Programming language (default: python)
        
    Returns:
        Formatted code review prompt
    """
    return f"""Please perform a thorough code review of this {language} code.

Focus on these areas:
- **Code Quality**: Style, readability, and maintainability
- **Potential Issues**: Bugs, edge cases, and error handling
- **Performance**: Efficiency and optimization opportunities
- **Security**: Potential vulnerabilities or unsafe practices
- **Best Practices**: Adherence to {language} conventions

Code to review:
```{language}
{code}
```

Please provide:
1. Overall assessment and rating
2. Specific issues found with line references
3. Improvement suggestions
4. Positive aspects worth highlighting"""
```

```python
# prompts/debug_session.py
from mcp.server.fastmcp.prompts import base

def debug_session(error_message: str, code_context: str, environment: str = "unknown") -> list[base.Message]:
    """
    Create a structured debugging conversation prompt.
    
    Args:
        error_message: The error encountered
        code_context: Relevant code that caused the error
        environment: Runtime environment details
        
    Returns:
        List of structured conversation messages
    """
    return [
        base.UserMessage(f"I'm encountering this error in my {environment} environment:"),
        base.UserMessage(f"**Error:** {error_message}"),
        base.UserMessage(f"**Code context:**\n```\n{code_context}\n```"),
        base.AssistantMessage("I'll help you debug this issue. Let me analyze the error and code context."),
        base.UserMessage("What could be causing this problem and how can I fix it?")
    ]
```

```python
# prompts/api_documentation.py
def api_documentation(
    endpoint: str, 
    method: str = "GET", 
    include_examples: bool = True,
    include_authentication: bool = True
) -> str:
    """
    Generate comprehensive API documentation prompt.
    
    Args:
        endpoint: API endpoint path
        method: HTTP method
        include_examples: Whether to include usage examples
        include_authentication: Whether to include auth details
        
    Returns:
        Formatted API documentation prompt
    """
    prompt = f"""Please provide comprehensive documentation for this API endpoint:

**Endpoint:** `{method} {endpoint}`

Please document:

## Overview
- Purpose and functionality
- When to use this endpoint

## Request Format
- Required and optional parameters
- Parameter types and validation rules
- Request body schema (if applicable)

## Response Format
- Success response structure
- Data types and field descriptions
- Possible response variations

## Error Handling
- Common error codes and meanings
- Error response format
- Troubleshooting guidance"""

    if include_authentication:
        prompt += "\n\n## Authentication\n- Required authentication method\n- Required permissions or scopes\n- Header format and examples"

    if include_examples:
        prompt += f"\n\n## Examples\n- Sample {method} request with realistic data\n- Sample successful response\n- Sample error responses"

    prompt += "\n\n## Additional Notes\n- Rate limiting information\n- Best practices for usage\n- Related endpoints or workflows"

    return prompt
```

```python
# prompts/__init__.py
"""Prompt module exports for easy registration."""

from .code_review import code_review
from .debug_session import debug_session
from .api_documentation import api_documentation

__all__ = ["code_review", "debug_session", "api_documentation"]
```
</details>

### 5.5 Lifespan and Context

Manage application lifecycle and share resources:

<details>
<summary>Advanced Lifespan Example</summary>

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import httpx
import asyncio
from mcp.server.fastmcp import FastMCP, Context

@dataclass
class DatabaseConnection:
    """Mock database connection."""
    host: str
    connected: bool = False
    
    async def connect(self):
        """Connect to database."""
        await asyncio.sleep(0.1)  # Mock connection time
        self.connected = True
    
    async def disconnect(self):
        """Disconnect from database."""
        self.connected = False

@dataclass
class AppContext:
    """Application context with all shared resources."""
    http_client: httpx.AsyncClient
    database: DatabaseConnection
    config: dict[str, str]

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage complete application lifecycle."""
    # Startup: initialize all resources
    http_client = httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_connections=100)
    )
    
    database = DatabaseConnection(host="localhost:5432")
    await database.connect()
    
    config = {
        "api_version": "v1",
        "max_retries": "3",
        "cache_ttl": "300"
    }
    
    try:
        yield AppContext(
            http_client=http_client,
            database=database,
            config=config
        )
    finally:
        # Shutdown: clean up all resources
        await http_client.aclose()
        await database.disconnect()

mcp = FastMCP("Advanced Server", lifespan=app_lifespan)

@mcp.tool()
async def query_data(sql: str, ctx: Context) -> str:
    """Execute database query."""
    app_ctx = ctx.request_context.lifespan_context
    
    if not app_ctx.database.connected:
        return "Database not connected"
    
    # Mock query execution
    ctx.info(f"Executing SQL: {sql}")
    return f"Query result for: {sql}"

@mcp.tool()
async def fetch_external_data(url: str, ctx: Context) -> str:
    """Fetch data from external service."""
    app_ctx = ctx.request_context.lifespan_context
    
    try:
        response = await app_ctx.http_client.get(url)
        return f"Fetched {len(response.content)} bytes from {url}"
    except Exception as e:
        ctx.error(f"Failed to fetch {url}: {e}")
        return f"Error: {e}"
```
</details>

----

## 6. FastMCP vs Low-Level Servers

### When to Use FastMCP (Recommended)

- **Simple to moderate complexity** servers
- **Rapid prototyping** and development
- **Standard use cases** (tools, resources, prompts)
- **CLI integration** with `mcp dev` and `mcp install`
- **Automatic type validation** and documentation

### When to Use Low-Level Servers

- **Advanced protocol control** needed
- **Custom transport implementations**
- **Complex session management** requirements
- **Event streaming** and resumability features
- **Integration with existing ASGI applications**

<details>
<summary>Low-Level Server Example</summary>

```python
# Advanced server with custom session management
import contextlib
from collections.abc import AsyncIterator
import logging
import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

logger = logging.getLogger(__name__)

# Create low-level MCP server
app = Server("advanced-mcp-server")

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Handle tool calls with custom logic."""
    ctx = app.request_context
    
    if name == "stream_notifications":
        count = arguments.get("count", 5)
        interval = arguments.get("interval", 1.0)
        
        # Send real-time notifications
        for i in range(count):
            await ctx.session.send_log_message(
                level="info",
                data=f"Notification {i+1}/{count}",
                logger="notification_stream",
                related_request_id=ctx.request_id
            )
            if i < count - 1:
                await anyio.sleep(interval)
        
        return [types.TextContent(
            type="text",
            text=f"Sent {count} notifications"
        )]
    
    raise ValueError(f"Unknown tool: {name}")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="stream_notifications",
            description="Send a stream of real-time notifications",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "default": 5},
                    "interval": {"type": "number", "default": 1.0}
                }
            }
        )
    ]

# Create session manager with resumability
from .event_store import InMemoryEventStore

session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=InMemoryEventStore(),  # Enable resumability
    json_response=False  # Use SSE streaming
)

@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    """Manage session manager lifecycle."""
    async with session_manager.run():
        logger.info("Advanced MCP server started")
        yield

# Create ASGI application
starlette_app = Starlette(
    routes=[Mount("/mcp", app=session_manager.handle_request)],
    lifespan=lifespan
)
```
</details>

----

## 7. Streamable HTTP Specifics

### Stateful vs Stateless Operation

**Stateless (Recommended for Scale)**:
```python
# Stateless server - better for horizontal scaling
mcp = FastMCP("StatelessServer", stateless_http=True)

@mcp.tool()
def pure_calculation(a: int, b: int) -> int:
    """Stateless calculation - no session state."""
    return a + b
```

**Stateful (When Session State Needed)**:
```python
# Stateful server - maintains session context
mcp = FastMCP("StatefulServer")

@mcp.tool()
def remember_value(key: str, value: str, ctx: Context) -> str:
    """Store value in session state."""
    # Access session-specific storage
    return f"Stored {key}={value}"
```

### Response Formats

**SSE Streaming (Default)**:
```python
mcp = FastMCP("SSE Server")  # Default: SSE streaming responses
```

**JSON Responses (Better for Simple Clients)**:
```python
mcp = FastMCP("JSON Server", json_response=True)  # Pure JSON responses
```

### Mounting Multiple Servers

<details>
<summary>Multiple Server Example</summary>

```python
# weather.py
from mcp.server.fastmcp import FastMCP

weather_mcp = FastMCP("Weather", stateless_http=True)

@weather_mcp.tool()
def get_weather(city: str) -> str:
    """Get weather for city."""
    return f"Weather in {city}: sunny"

# math.py  
from mcp.server.fastmcp import FastMCP

math_mcp = FastMCP("Math", stateless_http=True)

@math_mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

# main.py - Combined application
import contextlib
from fastapi import FastAPI
from weather import weather_mcp
from math import math_mcp

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage multiple session managers."""
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(weather_mcp.session_manager.run())
        await stack.enter_async_context(math_mcp.session_manager.run())
        yield

app = FastAPI(lifespan=lifespan)
app.mount("/weather", weather_mcp.streamable_http_app())
app.mount("/math", math_mcp.streamable_http_app())
```
</details>

----

## 8. Async Concurrency

Streamable HTTP servers should embrace async patterns:

<details>
<summary>Concurrency Examples</summary>

```python
import asyncio
import httpx
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("Async Examples")

# Concurrent operations
@mcp.tool()
async def fetch_multiple_urls(urls: list[str], ctx: Context) -> str:
    """Fetch multiple URLs concurrently."""
    async with httpx.AsyncClient() as client:
        tasks = [client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for i, response in enumerate(responses):
            if isinstance(response, Exception):
                results.append(f"URL {i+1}: Error - {response}")
            else:
                results.append(f"URL {i+1}: {response.status_code} ({len(response.content)} bytes)")
        
        return "\n".join(results)

# Rate-limited operations
@mcp.tool() 
async def process_items_with_rate_limit(items: list[str], ctx: Context) -> str:
    """Process items with rate limiting."""
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent operations
    
    async def process_item(item: str) -> str:
        async with semaphore:
            ctx.info(f"Processing {item}")
            await asyncio.sleep(0.1)  # Mock processing
            return f"Processed {item}"
    
    tasks = [process_item(item) for item in items]
    results = await asyncio.gather(*tasks)
    
    return f"Completed {len(results)} items"

# Progress reporting
@mcp.tool()
async def long_running_task(duration: float, ctx: Context) -> str:
    """Demonstrate progress reporting."""
    steps = 10
    step_duration = duration / steps
    
    for i in range(steps):
        await asyncio.sleep(step_duration)
        await ctx.report_progress(i + 1, steps)
        ctx.info(f"Step {i+1}/{steps} completed")
    
    return f"Task completed in {duration} seconds"
```
</details>

----

## 9. Testing and Quality

### Testing FastMCP Servers

<details>
<summary>Testing Examples</summary>

```python
# tests/test_server.py
import pytest
from mcp.server.fastmcp import FastMCP

# Create test server
test_mcp = FastMCP("Test Server")

@test_mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two numbers for testing."""
    return a + b

@test_mcp.resource("test://data")
def test_data() -> str:
    """Test resource."""
    return "test data"

class TestMCPServer:
    """Test suite for MCP server."""
    
    def test_tool_registration(self):
        """Test that tools are properly registered."""
        tools = test_mcp._tools
        assert "add_numbers" in tools
        
    def test_resource_registration(self):
        """Test that resources are properly registered."""
        resources = test_mcp._resources
        assert any("test://data" in str(r) for r in resources)
    
    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Test tool execution."""
        # Mock context for testing
        class MockContext:
            def __init__(self):
                self.request_context = None
        
        # Test tool function directly
        result = add_numbers(5, 3)
        assert result == 8
    
    @pytest.mark.asyncio
    async def test_resource_access(self):
        """Test resource access."""
        result = test_data()
        assert result == "test data"

# tests/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_context():
    """Create mock context for testing."""
    context = MagicMock()
    context.info = MagicMock()
    context.error = MagicMock()
    context.report_progress = AsyncMock()
    return context

@pytest.fixture
def mock_http_client():
    """Create mock HTTP client."""
    client = AsyncMock()
    client.get.return_value.status_code = 200
    client.get.return_value.content = b"mock response"
    return client
```
</details>

### Integration Testing

<details>
<summary>Integration Test Example</summary>

```python
# tests/test_integration.py
import pytest
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

@pytest.mark.asyncio
async def test_full_server_integration():
    """Test complete server integration."""
    # Set up server parameters
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"]
    )
    
    # Test client-server interaction
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize connection
            await session.initialize()
            
            # Test tool listing
            tools = await session.list_tools()
            assert len(tools.tools) > 0
            
            # Test tool execution
            result = await session.call_tool(
                "add_numbers",
                arguments={"a": 5, "b": 3}
            )
            assert result.content[0].text == "8"
            
            # Test resource access
            resources = await session.list_resources()
            assert len(resources.resources) > 0
```
</details>

----

## 10. Logging and Observability

### Using Context Logging

<details>
<summary>Logging Examples</summary>

```python
from mcp.server.fastmcp import FastMCP, Context
import logging

# Configure standard logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("Logging Server")

@mcp.tool()
async def process_data(data: str, ctx: Context) -> str:
    """Process data with comprehensive logging."""
    # Use context logging (sent to MCP client)
    ctx.info(f"Starting to process data: {len(data)} characters")
    
    try:
        # Simulate processing
        if not data.strip():
            ctx.warning("Empty data provided")
            return "No data to process"
        
        # Process data
        result = data.upper()
        ctx.info(f"Successfully processed data: {len(result)} characters")
        
        return result
        
    except Exception as e:
        # Error logging
        ctx.error(f"Failed to process data: {e}")
        logger.exception("Data processing failed")  # Server-side logging
        return f"Error: {e}"

@mcp.tool()
async def long_operation(items: list[str], ctx: Context) -> str:
    """Long operation with progress tracking."""
    ctx.info(f"Starting processing of {len(items)} items")
    
    for i, item in enumerate(items):
        # Progress reporting
        await ctx.report_progress(i, len(items))
        ctx.info(f"Processing item {i+1}: {item}")
        
        # Mock processing
        await asyncio.sleep(0.1)
    
    ctx.info("Processing completed successfully")
    return f"Processed {len(items)} items"

# Server-side structured logging
import structlog

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.dev.ConsoleRenderer()
    ]
)

struct_logger = structlog.get_logger()

@mcp.tool()
async def structured_logging_example(operation: str, ctx: Context) -> str:
    """Example of structured logging."""
    # Context logging (to MCP client)
    ctx.info(f"Executing operation: {operation}")
    
    # Structured server logging
    struct_logger.info(
        "Tool execution started",
        tool="structured_logging_example",
        operation=operation,
        client_id=getattr(ctx.request_context, 'client_id', 'unknown')
    )
    
    return f"Executed {operation}"
```
</details>

----

## 11. Security and Validation

### Input Validation and Security

<details>
<summary>Security Examples</summary>

```python
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, validator
import re
import os

mcp = FastMCP("Secure Server")

# Input validation with Pydantic
class FileRequest(BaseModel):
    """Secure file request model."""
    path: str = Field(..., min_length=1, max_length=255)
    operation: str = Field(..., regex="^(read|write|delete)$")
    
    @validator('path')
    def validate_path(cls, v):
        """Validate file path for security."""
        # Prevent path traversal
        if ".." in v or v.startswith("/") or "\\" in v:
            raise ValueError("Invalid file path: path traversal detected")
        
        # Only allow certain extensions
        allowed_extensions = {'.txt', '.json', '.csv', '.md'}
        if not any(v.endswith(ext) for ext in allowed_extensions):
            raise ValueError("File type not allowed")
        
        return v

@mcp.tool()
async def secure_file_operation(request: FileRequest, ctx: Context) -> str:
    """Secure file operations with validation."""
    ctx.info(f"File operation: {request.operation} on {request.path}")
    
    # Additional security checks
    if request.operation == "delete":
        ctx.warning("Delete operation requested - requires confirmation")
        return "Delete operations are restricted"
    
    # Sanitize for logging
    safe_path = re.sub(r'[^\w\-_\.]', '_', request.path)
    ctx.info(f"Processing sanitized path: {safe_path}")
    
    return f"Executed {request.operation} on {request.path}"

# Environment-based configuration
class SecureConfig(BaseModel):
    """Secure configuration from environment."""
    api_key: str = Field(..., min_length=10)
    base_url: str = Field(..., regex=r'^https?://')
    max_retries: int = Field(default=3, ge=1, le=10)
    
    @classmethod
    def from_env(cls) -> 'SecureConfig':
        """Load configuration from environment variables."""
        return cls(
            api_key=os.getenv("API_KEY", ""),
            base_url=os.getenv("BASE_URL", "https://api.example.com"),
            max_retries=int(os.getenv("MAX_RETRIES", "3"))
        )

# Rate limiting (conceptual)
from collections import defaultdict, deque
import time

class RateLimiter:
    """Simple rate limiter for tools."""
    
    def __init__(self, max_calls: int = 10, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.calls = defaultdict(deque)
    
    def is_allowed(self, client_id: str) -> bool:
        """Check if client is within rate limits."""
        now = time.time()
        client_calls = self.calls[client_id]
        
        # Remove old calls outside window
        while client_calls and client_calls[0] <= now - self.window_seconds:
            client_calls.popleft()
        
        # Check if under limit
        if len(client_calls) >= self.max_calls:
            return False
        
        # Record this call
        client_calls.append(now)
        return True

rate_limiter = RateLimiter(max_calls=10, window_seconds=60)

@mcp.tool()
async def rate_limited_tool(data: str, ctx: Context) -> str:
    """Tool with rate limiting."""
    client_id = getattr(ctx.request_context, 'client_id', 'unknown')
    
    if not rate_limiter.is_allowed(client_id):
        ctx.warning(f"Rate limit exceeded for client {client_id}")
        return "Error: Rate limit exceeded. Please try again later."
    
    return f"Processed data: {len(data)} characters"
```
</details>

----

## 12. Deployment and CLI Integration

### Development Workflow

**Local Development**:
```bash
# Create and test server
uv init my-mcp-server
cd my-mcp-server
uv add "mcp[cli]"

# Edit server.py with FastMCP code

# Test with MCP Inspector
mcp dev server.py

# Test with custom dependencies
mcp dev server.py --with httpx --with pydantic

# Test with local editable installs
mcp dev server.py --with-editable .
```

**Production Deployment**:
```bash
# Install in Claude Desktop
mcp install server.py --name "My Production Server"

# With environment variables
mcp install server.py -v API_KEY=abc123 -v DEBUG=false

# From environment file
mcp install server.py -f .env
```

### Project Configuration

<details>
<summary>pyproject.toml Example</summary>

```toml
# pyproject.toml
[project]
name = "my-mcp-server"
version = "0.1.0"
description = "My MCP server with streamable HTTP"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "mcp[cli]>=1.0.0",
    "pydantic>=2.0.0",
    "httpx>=0.27.0"
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.1.0",
    "mypy>=1.7.0"
]

[project.scripts]
my-mcp-server = "server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.mypy]
python_version = "3.10"
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```
</details>

### Docker Deployment

<details>
<summary>Docker Example</summary>

```dockerfile
# Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Expose port for streamable HTTP
EXPOSE 8000

# Run server
CMD ["uv", "run", "server.py"]
```

```bash
# Build and run
docker build -t my-mcp-server .
docker run -p 8000:8000 my-mcp-server
```
</details>

----

## 13. Additional Tips

### Modular Development Best Practices

1. **One Function Per Module**: Each tool, resource, and prompt gets its own module for better organization and testing
2. **Service Layer Separation**: Keep business logic in service modules separate from MCP interface modules
3. **Clear Module Structure**: Use descriptive file names that match the function/resource names
4. **Centralized Registration**: Register all components in `server.py` for a clear overview of server capabilities
5. **Dependency Injection**: Pass shared resources through lifespan context rather than importing directly in tool modules

### Common Patterns

<details>
<summary>Registration Patterns</summary>

```python
# server.py - Centralized registration approach
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My Server", lifespan=app_lifespan)

# Import and register all tools
from tools import (
    get_weather, calculate_bmi, fetch_data, 
    search_web, process_files, create_chart
)

for tool_func in [get_weather, calculate_bmi, fetch_data, search_web, process_files, create_chart]:
    mcp.tool()(tool_func)

# Import and register all resources  
from resources import server_config, user_profile, system_stats, file_contents

resource_mappings = [
    ("config://server", server_config),
    ("user://{user_id}/profile", user_profile),
    ("stats://current", system_stats),
    ("file://{path}", file_contents),
]

for uri_pattern, resource_func in resource_mappings:
    mcp.resource(uri_pattern)(resource_func)

# Import and register all prompts
from prompts import code_review, debug_session, api_documentation

for prompt_func in [code_review, debug_session, api_documentation]:
    mcp.prompt()(prompt_func)
```

```python
# Alternative: Automatic registration using decorators in modules
# tools/get_weather.py
from server import mcp  # Import the global mcp instance

@mcp.tool()
async def get_weather(city: str, ctx: Context) -> str:
    """Get weather for a city."""
    # Implementation here
    pass

# Then in server.py, just import all modules to trigger registration
import tools.get_weather
import tools.calculate_bmi
# etc.
```
</details>

### Streamable HTTP Considerations

1. **Stateless Design**: Prefer stateless operations for better scalability
2. **Response Format**: Choose between SSE (streaming) and JSON based on client needs
3. **Error Handling**: Use proper HTTP status codes and structured error responses
4. **Session Management**: Only use stateful mode when session persistence is required

### Documentation and Discovery

1. **Rich Docstrings**: LLMs discover functionality through docstrings - make them comprehensive
2. **Descriptive Tool Names**: Use clear, action-oriented names for tools
3. **Logical Resource URIs**: Design intuitive URI schemes for resources
4. **Parameter Descriptions**: Describe all parameters clearly with examples

### Common Patterns

<details>
<summary>Minimal Production Server</summary>

```python
# server.py - Complete minimal production server
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import httpx
import os
from mcp.server.fastmcp import FastMCP, Context

@dataclass
class AppContext:
    """Application context with shared resources."""
    http_client: httpx.AsyncClient
    api_key: str

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle."""
    http_client = httpx.AsyncClient(timeout=30.0)
    try:
        yield AppContext(
            http_client=http_client,
            api_key=os.getenv("API_KEY", "demo-key")
        )
    finally:
        await http_client.aclose()

# Create server with dependencies for CLI
mcp = FastMCP(
    "Production Server",
    dependencies=["httpx", "pydantic"],
    lifespan=app_lifespan
)

@mcp.tool()
async def fetch_data(url: str, ctx: Context) -> str:
    """Fetch data from external URL."""
    if not url.startswith(("http://", "https://")):
        return "Error: Invalid URL scheme"
    
    app_ctx = ctx.request_context.lifespan_context
    ctx.info(f"Fetching data from {url}")
    
    try:
        response = await app_ctx.http_client.get(url)
        return f"Success: {response.status_code} - {len(response.content)} bytes"
    except Exception as e:
        ctx.error(f"Failed to fetch {url}: {e}")
        return f"Error: {e}"

@mcp.resource("config://server")
def server_info() -> str:
    """Server configuration and status."""
    return f"""Server: {mcp.name}
Transport: Streamable HTTP
Status: Running
Features: Tools, Resources"""

@mcp.prompt()
def api_helper(endpoint: str) -> str:
    """Generate API integration help."""
    return f"""Help me integrate with this API endpoint: {endpoint}

Please provide:
1. Authentication requirements
2. Request format and parameters  
3. Response format
4. Error handling
5. Rate limiting considerations
6. Example usage code"""

# CLI integration - enables `mcp dev server.py` and `mcp install server.py`
if __name__ == "__main__":
    mcp.run()
```
</details>

----

Following these conventions will help you build robust, scalable MCP servers that integrate seamlessly with the modern MCP ecosystem and CLI tooling. The combination of FastMCP's simplicity and streamable HTTP's scalability provides an excellent foundation for production deployments.
