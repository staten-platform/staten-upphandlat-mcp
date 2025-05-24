# Upphandlat MCP Server

[![https://modelcontextprotocol.io](https://badge.mcpx.dev?type=server 'MCP Server')](https://modelcontextprotocol.io)

**Upphandlingsdata från Sveriges Upphandlingsmyndighet**

This MCP server is designed to analyze data on public procurement in Sweden. It provides access to information regarding the number of procurements, their value, and supplier details sourced from the Swedish National Procurement Agency (Upphandlingsmyndigheten).

It leverages Polars for high-performance data manipulation and exposes its capabilities via the Model Context Protocol (MCP).

## Overview

This MCP server allows LLMs to:
- Discover available datasets related to Swedish public procurement.
- Inspect the schema and column names of these datasets.
- Perform complex aggregations, grouping, filtering, and calculations on the data.
- Conduct fuzzy searches within text columns to find relevant information.

## Features
- Load multiple CSV datasets from specified URLs on server startup.
- Expose CSV schema and column information.
- Provide powerful aggregation capabilities, including:
    - Grouping by multiple columns.
    - Applying multiple aggregation functions (sum, mean, count, min, max).
    - Defining and applying calculated fields based on arithmetic operations or percentages.
    - Filtering data based on various conditions before aggregation.
    - Adding a configurable summary row to aggregation results.

## Configuration
The data sources and server identity are configured in `csv_sources.yaml` located in the project root. This file defines:
- `toolbox_title`: The main title for this MCP server instance.
- `toolbox_description`: A general description of the server's purpose.
- `sources`: A list of CSV data sources, each with:
    - `name`: A unique identifier for the dataset.
    - `url`: The URL from which to download the CSV.
    - `description`: A description of the dataset's content.
    - `read_csv_options`: Specific Polars `read_csv` parameters (e.g., separator, schema_overrides).

No `.env` file is strictly required for basic operation if `csv_sources.yaml` is present, but it can be used for other Pydantic settings if needed (e.g., API keys for other services, though not used by this server directly).

Example `csv_sources.yaml` snippet:
```
toolbox_title: "Upphandlingsdata från Sveriges Upphandlingsmyndighet"
toolbox_description: "Verktyg för att analysera data om offentliga upphandlingar i Sverige..."
sources:
  - name: "upphandlingsmyndigheten_antal_upphandlingar"
    url: "https://catalog.upphandlingsmyndigheten.se/store/12/resource/128"
    description: "Totalt antal upphandlingar per år och sektor."
    read_csv_options:
      separator: ";"
      # ... other options
```

## Available Tools
1.  **`list_available_dataframes()`**: Lists all loaded datasets with their names and descriptions.
2.  **`list_columns(dataframe_name: str)`**: Returns column names for a specified dataset.
3.  **`get_schema(dataframe_name: str)`**: Returns the schema (column names and data types) for a dataset.
4.  **`get_distinct_column_values(dataframe_name: str, column_name: str, ...)`**: Retrieves unique values from a column.
5.  **`fuzzy_search_column_values(dataframe_name: str, column_name: str, search_term: str, ...)`**: Performs fuzzy matching in a text column.
6.  **`aggregate_data(dataframe_name: str, request: AggregationRequest)`**: The main tool for filtering, grouping, aggregating, and calculating new fields from the data.

## Installation

It's recommended to use a virtual environment.

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```
This installs the package in editable mode.

## Running Locally for Development

Ensure your `csv_sources.yaml` file is configured in the project root.

Start the server locally:
```bash
uv run mcp dev src/upphandlat_mcp/server.py
```
Or, if `uv` is not managing the `mcp` tool itself:
```bash
mcp dev src/upphandlat_mcp/server.py
```

You can then use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) (usually at `http://localhost:5173` if you run it separately) to test and debug your MCP server.

For a more robust startup, especially if data loading is slow, you might need to increase the lifespan timeout:
```bash
uv run python -m mcp serve src/upphandlat_mcp/server.py:mcp --lifespan-timeout 120
```

## Claude Desktop Integration

Edit your `claude_desktop_config.json` to add this MCP Server. With this method, you need to have Astral UV installed globally.

Replace `[path to repo]` with the absolute path to your local repository directory:

```json
    "UpphandlatMCP": {
      "args": [
        "--directory",
        "[path to repo]", // Example: "/Users/yourname/projects/upphandlat-mcp"
        "run",
        "python", "-m", "mcp", "run", "src/upphandlat_mcp/server.py:mcp", "--transport", "stdio"
      ],
      "command": "uv"
    },
```

## Contributing
Contributions are welcome! Please open an issue or submit a pull request.
