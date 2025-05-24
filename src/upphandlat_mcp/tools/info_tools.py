import logging
from typing import Any

import polars as pl
from mcp.server.fastmcp import Context
from polars.exceptions import ColumnNotFoundError
from rapidfuzz import fuzz, process, utils
from upphandlat_mcp.core.config import CsvSourcesConfig
from upphandlat_mcp.lifespan.context import LifespanContext
from upphandlat_mcp.utils.dataframe_ops import (
    get_column_names_from_df,
    get_schema_from_df,
)

logger = logging.getLogger(__name__)


async def list_available_dataframes(
    ctx: Context,
) -> list[dict[str, str]] | dict[str, str]:
    """
    Retrieves the list of names and descriptions for all loaded DataFrames.

    Use this tool to find out which data sources are available for querying.
    Each name can then be used as the 'dataframe_name' parameter in other tools.

    Args:
        ctx: The MCP context.

    Returns:
        A list of dictionaries, where each dictionary has "name" and "description" keys.
        Returns an error dictionary if DataFrames or configuration are not available.
    """
    try:
        lifespan_ctx: LifespanContext = ctx.request_context.lifespan_context
        dataframes_dict = lifespan_ctx["dataframes"]
        csv_sources_config: CsvSourcesConfig = lifespan_ctx["csv_sources_config"]

        descriptions_map: dict[str, str | None] = {}
        if csv_sources_config and csv_sources_config.sources:
            descriptions_map = {
                source.name: source.description for source in csv_sources_config.sources
            }

        result_list: list[dict[str, str]] = []
        for name in dataframes_dict.keys():
            description = descriptions_map.get(name)
            description_to_use = (
                description if description else "No description available."
            )

            if name not in descriptions_map:
                logger.warning(
                    f"DataFrame '{name}' is loaded but has no corresponding entry "
                    f"in CsvSourcesConfig. Description will be default."
                )

            result_list.append({"name": name, "description": description_to_use})

        if not result_list and not dataframes_dict:
            logger.info("No dataframes available in the context.")
        elif not result_list and dataframes_dict:
            logger.warning(
                "Dataframes dictionary has keys but result list is empty. Check logic."
            )

        return result_list

    except KeyError as e:
        missing_key = e.args[0] if e.args else "Unknown key"
        error_msg = (
            f"Required key '{missing_key}' not found in lifespan context. "
            "Was data loading successful and context properly configured?"
        )
        await ctx.error(error_msg)
        logger.error(error_msg)
        return {
            "error": f"Context key '{missing_key}' missing. Server may be misconfigured or data failed to load."
        }
    except Exception as e:
        error_msg = f"An unexpected error occurred in list_available_dataframes: {e}"
        await ctx.error(error_msg, exc_info=True)
        logger.error(error_msg, exc_info=True)
        return {"error": f"An unexpected error occurred: {str(e)}"}


async def list_columns(ctx: Context, dataframe_name: str) -> list[str] | dict[str, str]:
    """
    Retrieves the list of column names from the specified DataFrame.

    Args:
        ctx: The MCP context.
        dataframe_name: The name of the DataFrame to inspect (from list_available_dataframes).

    Returns:
        A list of column name strings.
        Returns an error dictionary if the DataFrame is not available or name is invalid.
    """
    try:
        lifespan_ctx: LifespanContext = ctx.request_context.lifespan_context
        df_dict = lifespan_ctx["dataframes"]
        if dataframe_name not in df_dict:
            await ctx.error(
                f"DataFrame '{dataframe_name}' not found. Available: {list(df_dict.keys())}"
            )
            return {
                "error": f"DataFrame '{dataframe_name}' not found. Use list_available_dataframes() to see options."
            }
        df: pl.DataFrame = df_dict[dataframe_name]
        return get_column_names_from_df(df)
    except KeyError:
        await ctx.error(
            "DataFrame dictionary 'dataframes' not found in lifespan context."
        )
        return {"error": "DataFrames not available. Server may be misconfigured."}
    except Exception as e:
        await ctx.error(
            f"An unexpected error occurred in list_columns for '{dataframe_name}': {e}",
            exc_info=True,
        )
        return {"error": f"An unexpected error occurred: {str(e)}"}


async def fuzzy_search_column_values(
    ctx: Context,
    dataframe_name: str,
    column_name: str,
    search_term: str,
    limit: int = 5,
    score_cutoff: float = 70.0,
) -> list[dict[str, Any]] | dict[str, str]:
    """
    Performs a fuzzy search for a term in a specified column of a DataFrame.
    The search is case-insensitive and handles variations in wording.

    Args:
        ctx: The MCP context.
        dataframe_name: The name of the DataFrame to query.
        column_name: The name of the column to search within.
        search_term: The term to search for.
        limit: Optional. Maximum number of distinct values to return (default 5).
        score_cutoff: Optional. Minimum similarity score (0-100) for a match (default 70.0).

    Returns:
        A list of dictionaries, each with "value" and "score",
        or an error dictionary.
    """
    if not search_term or search_term.isspace():
        return {"error": "Search term cannot be empty or whitespace."}
    if limit <= 0:
        return {"error": "Limit must be a positive integer."}
    if not (0 <= score_cutoff <= 100):
        return {"error": "Score cutoff must be between 0 and 100."}

    try:
        lifespan_ctx: LifespanContext = ctx.request_context.lifespan_context
        df_dict = lifespan_ctx["dataframes"]
        if dataframe_name not in df_dict:
            await ctx.error(
                f"DataFrame '{dataframe_name}' not found. Available: {list(df_dict.keys())}"
            )
            return {
                "error": f"DataFrame '{dataframe_name}' not found. Use list_available_dataframes() to see options."
            }
        df: pl.DataFrame = df_dict[dataframe_name]
    except KeyError:
        await ctx.error(
            "DataFrame dictionary 'dataframes' not found in lifespan context."
        )
        return {"error": "DataFrames not available. Server may be misconfigured."}

    try:
        if column_name not in df.columns:
            raise ColumnNotFoundError(
                f"Column '{column_name}' not found in DataFrame '{dataframe_name}'. Available columns: {df.columns}"
            )

        unique_values_series: pl.Series
        if df[column_name].dtype != pl.Utf8 and df[column_name].dtype != pl.Categorical:
            await ctx.warning(
                f"Column '{column_name}' in DataFrame '{dataframe_name}' is not of type Utf8 or Categorical. "
                f"Fuzzy search works best on text. Current type: {df[column_name].dtype}. Attempting to cast to Utf8."
            )
            try:
                unique_values_series = df[column_name].unique().cast(pl.Utf8)
            except pl.PolarsError as cast_error:
                await ctx.error(
                    f"Failed to cast column '{column_name}' to Utf8 for fuzzy search: {cast_error}"
                )
                return {
                    "error": f"Column '{column_name}' could not be cast to a string type for fuzzy search."
                }
        else:
            unique_values_series = df[column_name].unique()

        unique_values_series = unique_values_series.drop_nulls()
        choices = unique_values_series.to_list()

        if not choices:
            return []

        matches = process.extract(
            search_term,
            choices,
            scorer=fuzz.WRatio,
            processor=utils.default_process,
            limit=limit,
            score_cutoff=score_cutoff,
        )

        results = [
            {"value": match[0], "score": round(match[1], 2)} for match in matches
        ]
        return results

    except ColumnNotFoundError as e:
        logger.warning(f"ColumnNotFoundError in fuzzy_search_column_values: {e}")
        await ctx.error(f"Configuration error: {str(e)}")
        return {"error": f"Configuration error: {str(e)}"}
    except ValueError as ve:
        logger.warning(f"ValueError in fuzzy_search_column_values: {ve}")
        await ctx.error(f"Invalid input: {str(ve)}")
        return {"error": f"Invalid input: {str(ve)}"}
    except Exception as e:
        logger.error(
            f"An unexpected error occurred in fuzzy_search_column_values for '{dataframe_name}' and column '{column_name}': {e}",
            exc_info=True,
        )
        await ctx.error(
            f"An unexpected server error occurred while searching in '{dataframe_name}', column '{column_name}'.",
            exc_info=True,
        )
        return {"error": f"An unexpected server error occurred."}


async def get_schema(
    ctx: Context, dataframe_name: str
) -> dict[str, str] | dict[str, Any]:
    """
    Retrieves the schema of the specified DataFrame.

    Args:
        ctx: The MCP context.
        dataframe_name: The name of the DataFrame to inspect.

    Returns:
        A dictionary mapping column names to their Polars data types.
    """
    try:
        lifespan_ctx: LifespanContext = ctx.request_context.lifespan_context
        df_dict = lifespan_ctx["dataframes"]
        if dataframe_name not in df_dict:
            await ctx.error(
                f"DataFrame '{dataframe_name}' not found. Available: {list(df_dict.keys())}"
            )
            return {
                "error": f"DataFrame '{dataframe_name}' not found. Use list_available_dataframes() to see options."
            }
        df: pl.DataFrame = df_dict[dataframe_name]
        return get_schema_from_df(df)
    except KeyError:
        await ctx.error(
            "DataFrame dictionary 'dataframes' not found in lifespan context."
        )
        return {"error": "DataFrames not available. Server may be misconfigured."}
    except Exception as e:
        await ctx.error(
            f"An unexpected error occurred in get_schema for '{dataframe_name}': {e}",
            exc_info=True,
        )
        return {"error": f"An unexpected error occurred: {str(e)}"}


async def get_distinct_column_values(
    ctx: Context,
    dataframe_name: str,
    column_name: str,
    sort_by_column: str | None = None,
    sort_descending: bool = False,
    limit: int | None = None,
) -> list[Any] | dict[str, str]:
    """
    Retrieves all distinct values from a specified column in a given DataFrame.

    Args:
        ctx: The MCP context.
        dataframe_name: The name of the DataFrame to query.
        column_name: The name of the column to get distinct values from.
        sort_by_column: Optional. Column to sort by for ordering distinct values.
        sort_descending: Optional. Sort in descending order.
        limit: Optional. Maximum number of distinct values.

    Returns:
        A list of distinct values or an error dictionary.
    """
    try:
        lifespan_ctx: LifespanContext = ctx.request_context.lifespan_context
        df_dict = lifespan_ctx["dataframes"]
        if dataframe_name not in df_dict:
            await ctx.error(
                f"DataFrame '{dataframe_name}' not found. Available: {list(df_dict.keys())}"
            )
            return {
                "error": f"DataFrame '{dataframe_name}' not found. Use list_available_dataframes() to see options."
            }
        df: pl.DataFrame = df_dict[dataframe_name]
    except KeyError:
        await ctx.error(
            "DataFrame dictionary 'dataframes' not found in lifespan context."
        )
        return {"error": "DataFrames not available. Server may be misconfigured."}

    try:
        if column_name not in df.columns:
            raise ColumnNotFoundError(
                f"Column '{column_name}' not found in DataFrame '{dataframe_name}'. Available columns: {df.columns}"
            )

        result_series: pl.Series

        if sort_by_column:
            if sort_by_column not in df.columns:
                raise ColumnNotFoundError(
                    f"Sort column '{sort_by_column}' not found in DataFrame '{dataframe_name}'. Available columns: {df.columns}"
                )
            result_series = df.sort(sort_by_column, descending=sort_descending)[
                column_name
            ].unique(maintain_order=True)
        else:
            result_series = (
                df[column_name]
                .unique(maintain_order=False)
                .sort(descending=sort_descending)
            )

        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise ValueError("Limit must be a non-negative integer.")
            result_series = result_series.head(limit)

        return result_series.to_list()

    except ColumnNotFoundError as e:
        error_msg = str(e)
        await ctx.error(f"Column not found: {error_msg}")
        return {"error": f"Configuration error: {error_msg}"}
    except ValueError as ve:
        error_msg = str(ve)
        await ctx.error(f"Invalid input value: {error_msg}")
        return {"error": f"Invalid input: {error_msg}"}
    except pl.PolarsError as pe:
        await ctx.error(
            f"Polars error during distinct value retrieval for '{dataframe_name}': {pe}",
            exc_info=True,
        )
        return {"error": f"Data processing error with Polars: {str(pe)}"}
    except Exception as e:
        await ctx.error(
            f"An unexpected error occurred in get_distinct_column_values for '{dataframe_name}': {e}",
            exc_info=True,
        )
        return {"error": f"An unexpected error occurred: {str(e)}"}
