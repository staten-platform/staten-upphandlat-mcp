from __future__ import annotations

from collections.abc import Iterable

import polars as pl

from upphandlat_mcp.models.mcp_models import Aggregation


def build_aggregation_expression(
    agg: Aggregation,
    existing_columns: set[str],
    used_names: set[str],
) -> tuple[list[pl.Expr], set[str]]:
    if agg.column not in existing_columns:
        raise ValueError(f"Aggregation column '{agg.column}' not found in DataFrame.")

    exprs: list[pl.Expr] = []
    for func in agg.functions:
        alias = agg.rename.get(func.value, f"{agg.column}_{func.value}")
        if alias in used_names:
            raise ValueError(f"Duplicate output column name: '{alias}'.")
        used_names.add(alias)

        col_expr = getattr(pl.col(agg.column), func.value)()
        exprs.append(col_expr.alias(alias))

    return exprs, used_names


def build_polars_aggregation_expressions(
    aggregations: Iterable[Aggregation],
    group_by_columns: set[str],
    existing_columns: set[str],
) -> tuple[list[pl.Expr], set[str]]:
    """Build Polars aggregation expressions and track output column names."""
    all_names = set(group_by_columns)
    expressions: list[pl.Expr] = []

    for agg in aggregations:
        exprs, all_names = build_aggregation_expression(
            agg, existing_columns, all_names
        )
        expressions.extend(exprs)

    return expressions, all_names
