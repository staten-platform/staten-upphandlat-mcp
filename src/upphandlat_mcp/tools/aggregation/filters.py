from __future__ import annotations

from collections.abc import Iterable

import polars as pl
from mcp.server.fastmcp import Context
from typing import Any

from upphandlat_mcp.models.mcp_models import FilterCondition, FilterOperator


async def build_filter_expr(  # noqa: PLR0911,PLR0912
    condition: FilterCondition,
    ctx: Context[Any],
) -> pl.Expr:
    """Return a Polars expression for a single filter condition."""
    col_expr = pl.col(condition.column)
    value = condition.value

    if condition.operator == FilterOperator.EQUALS:
        return (
            col_expr.str.to_lowercase() == str(value).lower()
            if isinstance(value, str)
            else col_expr == value
        )

    if condition.operator == FilterOperator.NOT_EQUALS:
        return (
            col_expr.str.to_lowercase() != str(value).lower()
            if isinstance(value, str)
            else col_expr != value
        )

    if condition.operator == FilterOperator.GREATER_THAN:
        return col_expr > value
    if condition.operator == FilterOperator.GREATER_THAN_OR_EQUAL_TO:
        return col_expr >= value
    if condition.operator == FilterOperator.LESS_THAN:
        return col_expr < value
    if condition.operator == FilterOperator.LESS_THAN_OR_EQUAL_TO:
        return col_expr <= value

    if condition.operator in {FilterOperator.IN, FilterOperator.NOT_IN}:
        if not isinstance(value, list):
            raise ValueError(
                f"Operator '{condition.operator.value}' requires a list value "
                f"for column '{condition.column}'."
            )
        if not value:
            return pl.lit(condition.operator == FilterOperator.NOT_IN)
        if isinstance(value[0], str):
            lowered = [str(v).lower() for v in value if isinstance(v, str)]
            if not lowered and value:
                await ctx.warning(
                    f"{condition.operator.value} list for '{condition.column}' "
                    "contains non-string items."
                )
                expr = col_expr.is_in(value)
            else:
                expr = col_expr.str.to_lowercase().is_in(lowered)
        else:
            expr = col_expr.is_in(value)
        return ~expr if condition.operator == FilterOperator.NOT_IN else expr

    if condition.operator == FilterOperator.CONTAINS:
        if not isinstance(value, str):
            raise ValueError(
                f"Operator 'contains' requires a string value for column "
                f"'{condition.column}'."
            )
        return (
            col_expr.str.to_lowercase()
            .str.contains(str(value).lower(), literal=True)
        )

    if condition.operator == FilterOperator.STARTS_WITH:
        if not isinstance(value, str):
            raise ValueError(
                f"Operator 'starts_with' requires a string value for column "
                f"'{condition.column}'."
            )
        return col_expr.str.to_lowercase().str.starts_with(str(value).lower())

    if condition.operator == FilterOperator.ENDS_WITH:
        if not isinstance(value, str):
            raise ValueError(
                f"Operator 'ends_with' requires a string value for column "
                f"'{condition.column}'."
            )
        return col_expr.str.to_lowercase().str.ends_with(str(value).lower())

    if condition.operator == FilterOperator.IS_NULL:
        return col_expr.is_null()
    if condition.operator == FilterOperator.IS_NOT_NULL:
        return col_expr.is_not_null()

    raise ValueError(f"Unsupported filter operator: {condition.operator}")


async def apply_filters(
    df: pl.DataFrame,
    conditions: Iterable[FilterCondition] | None,
    ctx: Context[Any],
) -> pl.DataFrame:
    """Apply all filter conditions to the DataFrame."""
    if not conditions:
        return df

    exprs = []
    for cond in conditions:
        if cond.column not in df.columns:
            raise ValueError(
                f"Filter column '{cond.column}' not found in DataFrame. "
                f"Available columns: {list(df.columns)}"
            )
        exprs.append(await build_filter_expr(cond, ctx))

    combined = exprs[0]
    for expr in exprs[1:]:
        combined = combined & expr

    await ctx.info(f"Applying combined filter expression: {combined}")
    return df.filter(combined)
