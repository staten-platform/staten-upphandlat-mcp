import asyncio
import logging
from typing import Any

from mcp.server.fastmcp import Context
from statens_response import statens_dataframe_response
from upphandlat_mcp.lifespan.context import LifespanContext, get_or_reload_dataframe
from upphandlat_mcp.models.mcp_models import AggregationRequest

from .aggregations import build_polars_aggregation_expressions
from .calculations import apply_calculated_fields
from .filters import apply_filters
from .summary import build_summary_row

logger = logging.getLogger(__name__)


@statens_dataframe_response()
async def aggregate_data(  # noqa: PLR0912
    ctx: Context[Any, Any],
    dataframe_name: str,
    request: AggregationRequest,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Filter, aggregate and calculate data for a given DataFrame."""

    try:
        lifespan_ctx: LifespanContext = ctx.request_context.lifespan_context

        source_df = await get_or_reload_dataframe(lifespan_ctx, dataframe_name)
        if source_df is None:
            await ctx.error(f"DataFrame '{dataframe_name}' not found in cache.")
            return {
                "error": f"DataFrame '{dataframe_name}' not found in cache. It might not have loaded correctly."
            }
    except KeyError as e:  # Catch specific KeyError if shared_cache itself is missing
        await ctx.error(f"DataFrame '{dataframe_name}' not found.")
        return {"error": f"DataFrame '{dataframe_name}' not found."}

    df_columns = set(source_df.columns)

    try:
        filtered_df = await apply_filters(source_df, request.filters, ctx)

        for col in request.group_by_columns:
            if col not in df_columns:
                raise ValueError(
                    f"Invalid group_by_column '{col}'. Available: {list(df_columns)}"
                )

        if request.aggregations:
            agg_exprs, out_cols = build_polars_aggregation_expressions(
                request.aggregations,
                set(request.group_by_columns),
                df_columns,
            )
            grouped = filtered_df.group_by(
                request.group_by_columns,
                maintain_order=True,
            )
            intermediate_df = grouped.agg(agg_exprs)
        else:
            intermediate_df = filtered_df.select(request.group_by_columns).unique(
                maintain_order=True,
            )
            out_cols = set(request.group_by_columns)

        cols_for_calc = out_cols if request.aggregations else df_columns
        final_df = await asyncio.to_thread(
            apply_calculated_fields,
            intermediate_df,
            request.calculated_fields,
            cols_for_calc,
        )
    except ValueError as ve:
        await ctx.error(str(ve))
        return {"error": str(ve)}

    columns = list(request.group_by_columns)
    if request.aggregations:
        columns.extend([c for c in out_cols if c not in columns])
    if request.calculated_fields:
        columns.extend(
            [
                cf.output_column_name
                for cf in request.calculated_fields
                if cf.output_column_name not in columns
            ]
        )

    present_cols = [c for c in columns if c in final_df.columns]
    if not present_cols:
        return []

    final_df = final_df.select(present_cols)

    if not request.aggregations:
        if final_df.height > 0 and final_df.columns:
            final_df = final_df.unique(
                subset=final_df.columns,
                maintain_order=True,
            )

    sortable_cols = [c for c in request.group_by_columns if c in final_df.columns]
    if sortable_cols:
        final_df = final_df.sort(sortable_cols)

    result = final_df.to_dicts()

    if request.summary_settings and request.summary_settings.enabled:
        summary_row = await build_summary_row(
            final_df,
            request.summary_settings,
            request.group_by_columns,
            ctx,
        )
        result.append(summary_row)

    return result
