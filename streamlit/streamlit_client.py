"""Manual Streamlit client for the Upphandlat MCP server."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import streamlit as st
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_URL", "http://localhost:8000/mcp/")

TOOL_EXAMPLES = {
    "list_available_dataframes": [
        {
            "name": "List all data sources",
            "args": {}
        }
    ],
    "list_columns": [
        {
            "name": "List columns for first dataframe",
            "args": {"dataframe_name": "sample_data"}
        }
    ],
    "get_schema": [
        {
            "name": "Get schema for dataframe",
            "args": {"dataframe_name": "sample_data"}
        }
    ],
    "get_distinct_column_values": [
        {
            "name": "Get distinct values from a column",
            "args": {
                "dataframe_name": "sample_data",
                "column_name": "category",
                "limit": 10
            }
        },
        {
            "name": "Get sorted distinct values",
            "args": {
                "dataframe_name": "sample_data",
                "column_name": "amount",
                "sort_by_column": "amount",
                "sort_descending": True,
                "limit": 5
            }
        }
    ],
    "fuzzy_search_column_values": [
        {
            "name": "Search for similar text values",
            "args": {
                "dataframe_name": "sample_data",
                "column_name": "description",
                "search_term": "office",
                "limit": 5,
                "score_cutoff": 70.0
            }
        }
    ],
    "aggregate_data": [
        {
            "name": "Basic grouping and sum",
            "args": {
                "dataframe_name": "sample_data",
                "request": {
                    "group_by_columns": ["category"],
                    "aggregations": [
                        {
                            "column": "amount",
                            "functions": ["sum", "count"]
                        }
                    ]
                }
            }
        },
        {
            "name": "Filtered aggregation with calculations",
            "args": {
                "dataframe_name": "sample_data",
                "request": {
                    "group_by_columns": ["category"],
                    "filters": [
                        {
                            "column": "amount",
                            "operator": "greater_than",
                            "value": 100
                        }
                    ],
                    "aggregations": [
                        {
                            "column": "amount",
                            "functions": ["sum", "mean"]
                        }
                    ],
                    "calculated_fields": [
                        {
                            "calculation_type": "percentage_of_column",
                            "value_column": "amount_sum",
                            "total_reference_column": "amount_sum",
                            "output_column_name": "percentage_of_total",
                            "scale_factor": 100
                        }
                    ],
                    "summary_settings": {
                        "enabled": True,
                        "first_group_by_column_label": "TOTAL"
                    }
                }
            }
        }
    ]
}


def fetch_tools() -> list[str]:
    """Fetch tool names from the server."""

    async def _get() -> list[str]:
        async with streamablehttp_client(MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]

    return asyncio.run(_get())


def execute_tool(name: str, args: dict[str, Any]) -> list[str]:
    """Execute a tool on the server and return text outputs."""

    async def _call() -> list[str]:
        async with streamablehttp_client(MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
                outputs: list[str] = []
                for item in result.content:
                    outputs.append(item.text if hasattr(item, "text") else str(item))  # type: ignore
                return outputs

    return asyncio.run(_call())


st.title("Upphandlat MCP Streamlit Client")

tool_names = fetch_tools()
selected_tool = st.selectbox("Tool", tool_names)

# Example queries section
if selected_tool and selected_tool in TOOL_EXAMPLES:
    st.subheader("Example Queries")
    examples = TOOL_EXAMPLES[selected_tool]
    
    col1, col2 = st.columns([3, 1])
    with col1:
        example_names = [ex["name"] for ex in examples]
        selected_example = st.selectbox("Choose an example:", [""] + example_names)
    
    with col2:
        if st.button("Load Example") and selected_example:
            example_args = next(ex["args"] for ex in examples if ex["name"] == selected_example)
            st.session_state.args_json = json.dumps(example_args, indent=2)

# Arguments input
args_json = st.text_area(
    "Arguments (JSON)", 
    value=st.session_state.get("args_json", "{}"),
    height=200
)

if st.button("Run"):
    try:
        arguments = json.loads(args_json) if args_json.strip() else {}
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
    else:
        results = execute_tool(selected_tool, arguments)
        st.write("Result:")
        for block in results:
            st.write(block)
