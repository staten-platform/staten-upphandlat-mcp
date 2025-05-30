from __future__ import annotations

from typing import Any

import polars as pl
from mcp.server.fastmcp import Context

from upphandlat_mcp.models.mcp_models import SummaryFunction, SummaryRowSettings


async def build_summary_row(  # noqa: PLR0912
    df: pl.DataFrame,
    settings: SummaryRowSettings,
    group_by_columns: list[str],
    ctx: Context[Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    output_columns = df.columns

    specific_configs = {
        cfg.column_name: cfg
        for cfg in (settings.column_specific_summaries or [])
        if cfg.column_name in output_columns
    }

    for idx, col in enumerate(output_columns):
        series = df[col]
        dtype = series.dtype
        cfg = specific_configs.get(col)

        if cfg:
            if cfg.summary_function == SummaryFunction.LABEL:
                summary_val = cfg.label_text
            elif cfg.summary_function == SummaryFunction.NONE:
                summary_val = None
            elif df.is_empty() and cfg.summary_function != SummaryFunction.COUNT:
                summary_val = None
            elif cfg.summary_function == SummaryFunction.COUNT:
                summary_val = series.count()
            elif dtype.is_numeric():
                summary_val = getattr(series, cfg.summary_function.value)()
            else:
                await ctx.warning(
                    "Cannot apply numeric summary "
                    f"'{cfg.summary_function.value}' to non-numeric column '{col}'."
                )
                summary_val = None
        else:
            is_first_group_by = (
                group_by_columns and col == group_by_columns[0] and idx == 0
            )
            if is_first_group_by:
                summary_val = settings.first_group_by_column_label
            elif col in group_by_columns:
                summary_val = None
            elif dtype.is_numeric():
                func = settings.default_numeric_summary_function
                if df.is_empty() and func != SummaryFunction.COUNT:
                    summary_val = None
                elif func == SummaryFunction.COUNT:
                    summary_val = series.count()
                else:
                    summary_val = getattr(series, func.value)()
            else:
                func = settings.default_string_summary_function
                if func == SummaryFunction.LABEL:
                    await ctx.warning(
                        "Default string summary is 'label' for column "
                        f"'{col}' but no specific label_text."
                    )
                    summary_val = None
                elif func == SummaryFunction.COUNT:
                    summary_val = series.count()
                else:
                    summary_val = None

        summary[col] = summary_val

    return summary
