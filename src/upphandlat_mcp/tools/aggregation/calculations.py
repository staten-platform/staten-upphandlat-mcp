from __future__ import annotations

import polars as pl
from mcp.server.fastmcp import Context
from typing import Any

from upphandlat_mcp.models.mcp_models import (
    ArithmeticOperationType,
    CalculatedFieldType,
)


def _check_columns_exist(df_columns: set[str], *cols: str) -> None:
    for col in cols:
        if col not in df_columns:
            raise ValueError(
                f"Input column '{col}' for calculated field not found. "
                f"Available columns: {sorted(df_columns)}"
            )


def _two_column_expr(cfg, df_columns: set[str]) -> pl.Expr:
    _check_columns_exist(df_columns, cfg.column_a, cfg.column_b)
    a = pl.col(cfg.column_a)
    b = pl.col(cfg.column_b)
    ops = {
        ArithmeticOperationType.ADD: lambda x, y: x + y,
        ArithmeticOperationType.SUBTRACT: lambda x, y: x - y,
        ArithmeticOperationType.MULTIPLY: lambda x, y: x * y,
        ArithmeticOperationType.DIVIDE: lambda x, y: x / y,
    }
    expr = ops[cfg.operation](a, b)
    if (
        cfg.operation == ArithmeticOperationType.DIVIDE
        and cfg.on_division_by_zero != "propagate_error"
    ):
        fallback = (
            None
            if cfg.on_division_by_zero == "null"
            else pl.lit(cfg.on_division_by_zero, dtype=pl.Float64)
        )
        expr = pl.when(b != 0).then(expr).otherwise(fallback)
    return expr


def _constant_expr(cfg, df_columns: set[str]) -> pl.Expr:
    _check_columns_exist(df_columns, cfg.input_column)
    col = pl.col(cfg.input_column)
    const = pl.lit(cfg.constant_value)
    if (
        cfg.operation == ArithmeticOperationType.DIVIDE
        and cfg.on_division_by_zero != "propagate_error"
    ):
        if cfg.column_is_first_operand and cfg.constant_value == 0:
            return pl.lit(
                None
                if cfg.on_division_by_zero == "null"
                else cfg.on_division_by_zero,
                dtype=pl.Float64,
            )
        if not cfg.column_is_first_operand:
            base = const / col
            fallback = (
                None
                if cfg.on_division_by_zero == "null"
                else pl.lit(cfg.on_division_by_zero, dtype=pl.Float64)
            )
            return pl.when(col != 0).then(base).otherwise(fallback)
    ops_col_first = {
        ArithmeticOperationType.ADD: lambda c, k: c + k,
        ArithmeticOperationType.SUBTRACT: lambda c, k: c - k,
        ArithmeticOperationType.MULTIPLY: lambda c, k: c * k,
        ArithmeticOperationType.DIVIDE: lambda c, k: c / k,
    }
    ops_const_first = {
        ArithmeticOperationType.ADD: lambda k, c: k + c,
        ArithmeticOperationType.SUBTRACT: lambda k, c: k - c,
        ArithmeticOperationType.MULTIPLY: lambda k, c: k * c,
        ArithmeticOperationType.DIVIDE: lambda k, c: k / c,
    }
    if cfg.column_is_first_operand:
        return ops_col_first[cfg.operation](col, const)
    return ops_const_first[cfg.operation](const, col)


def _percentage_expr(cfg, df_columns: set[str]) -> pl.Expr:
    _check_columns_exist(df_columns, cfg.value_column, cfg.total_reference_column)
    value = pl.col(cfg.value_column)
    total = pl.col(cfg.total_reference_column)
    expr = (value / total) * cfg.scale_factor
    if cfg.on_division_by_zero != "propagate_error":
        fallback = (
            None
            if cfg.on_division_by_zero == "null"
            else pl.lit(cfg.on_division_by_zero, dtype=pl.Float64)
        )
        expr = pl.when(total != 0).then(expr).otherwise(fallback)
    return expr


def apply_calculated_fields(
    df: pl.DataFrame,
    configs: list[CalculatedFieldType] | None,
    available_columns: set[str],
    ctx: Context[Any] | None = None,
) -> pl.DataFrame:
    if not configs:
        return df

    result = df
    cols_available = set(available_columns)
    for cfg in configs:
        if cfg.output_column_name in cols_available:
            raise ValueError(

                    f"Calculated field output name '{cfg.output_column_name}' "
                    "conflicts with existing column."

            )
        if cfg.calculation_type == "two_column_arithmetic":
            expr = _two_column_expr(cfg, cols_available)
        elif cfg.calculation_type == "constant_arithmetic":
            expr = _constant_expr(cfg, cols_available)
        elif cfg.calculation_type == "percentage_of_column":
            expr = _percentage_expr(cfg, cols_available)
        else:
            raise ValueError(

                    "Unsupported calculated_field type: "
                    f"{getattr(cfg, 'calculation_type', 'Unknown')}"

            )
        result = result.with_columns(expr.alias(cfg.output_column_name))
        cols_available.add(cfg.output_column_name)
    return result
