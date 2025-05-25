import asyncio
import logging
from typing import Any

import polars as pl
from mcp.server.fastmcp import Context

from upphandlat_mcp.lifespan.context import LifespanContext
from upphandlat_mcp.models.mcp_models import (
    Aggregation,
    AggregationRequest,
    ArithmeticOperationType,
    CalculatedFieldType,
    FilterCondition,
    FilterOperator,
    SummaryColumnConfiguration,
    SummaryFunction,
)

logger = logging.getLogger(__name__)


async def _apply_filters(
    df: pl.DataFrame,
    filter_conditions: list[FilterCondition],
    available_columns: set[str],
    ctx: Context,
) -> pl.DataFrame:
    """Applies a list of filter conditions to the DataFrame. String comparisons are always case-insensitive."""
    if not filter_conditions:
        return df

    combined_filter_expr: pl.Expr | None = None

    for condition in filter_conditions:
        if condition.column not in available_columns:
            raise ValueError(
                f"Filter column '{condition.column}' not found in DataFrame. Available columns: {list(available_columns)}"
            )

        col_expr = pl.col(condition.column)
        value = condition.value

        current_expr: pl.Expr

        if condition.operator == FilterOperator.EQUALS:
            if isinstance(value, str):
                current_expr = col_expr.str.to_lowercase() == str(value).lower()
            else:
                current_expr = col_expr == value
        elif condition.operator == FilterOperator.NOT_EQUALS:
            if isinstance(value, str):
                current_expr = col_expr.str.to_lowercase() != str(value).lower()
            else:
                current_expr = col_expr != value
        elif condition.operator == FilterOperator.GREATER_THAN:
            current_expr = col_expr > value
        elif condition.operator == FilterOperator.GREATER_THAN_OR_EQUAL_TO:
            current_expr = col_expr >= value
        elif condition.operator == FilterOperator.LESS_THAN:
            current_expr = col_expr < value
        elif condition.operator == FilterOperator.LESS_THAN_OR_EQUAL_TO:
            current_expr = col_expr <= value
        elif condition.operator == FilterOperator.IN:
            if not isinstance(value, list):
                raise ValueError(
                    f"Operator 'in' requires a list value for column '{condition.column}'."
                )

            if value and isinstance(value[0], str):
                lower_value_list = [str(v).lower() for v in value if isinstance(v, str)]

                if not lower_value_list and value:
                    await ctx.warning(
                        f"Operator 'in' for column '{condition.column}' received a list with non-string items when string matching was attempted. Will use original list for matching."
                    )
                    current_expr = col_expr.is_in(value)
                elif not lower_value_list:
                    current_expr = pl.lit(False)
                else:
                    current_expr = col_expr.str.to_lowercase().is_in(lower_value_list)
            else:
                if not value:
                    current_expr = pl.lit(False)
                else:
                    current_expr = col_expr.is_in(value)
        elif condition.operator == FilterOperator.NOT_IN:
            if not isinstance(value, list):
                raise ValueError(
                    f"Operator 'not_in' requires a list value for column '{condition.column}'."
                )

            if value and isinstance(value[0], str):
                lower_value_list = [str(v).lower() for v in value if isinstance(v, str)]

                if not lower_value_list and value:
                    await ctx.warning(
                        f"Operator 'not_in' for column '{condition.column}' received a list with non-string items when string matching was attempted. Will use original list for matching."
                    )
                    current_expr = ~col_expr.is_in(value)
                elif not lower_value_list:
                    current_expr = pl.lit(True)
                else:
                    current_expr = ~col_expr.str.to_lowercase().is_in(lower_value_list)
            else:
                if not value:
                    current_expr = pl.lit(True)
                else:
                    current_expr = ~col_expr.is_in(value)
        elif condition.operator == FilterOperator.CONTAINS:
            if not isinstance(value, str):
                raise ValueError(
                    f"Operator 'contains' requires a string value for column '{condition.column}'."
                )
            current_expr = col_expr.str.to_lowercase().str.contains(
                str(value).lower(), literal=True
            )
        elif condition.operator == FilterOperator.STARTS_WITH:
            if not isinstance(value, str):
                raise ValueError(
                    f"Operator 'starts_with' requires a string value for column '{condition.column}'."
                )
            current_expr = col_expr.str.to_lowercase().str.starts_with(
                str(value).lower()
            )
        elif condition.operator == FilterOperator.ENDS_WITH:
            if not isinstance(value, str):
                raise ValueError(
                    f"Operator 'ends_with' requires a string value for column '{condition.column}'."
                )
            current_expr = col_expr.str.to_lowercase().str.ends_with(str(value).lower())
        elif condition.operator == FilterOperator.IS_NULL:
            current_expr = col_expr.is_null()
        elif condition.operator == FilterOperator.IS_NOT_NULL:
            current_expr = col_expr.is_not_null()
        else:
            raise ValueError(f"Unsupported filter operator: {condition.operator}")

        if combined_filter_expr is None:
            combined_filter_expr = current_expr
        else:
            combined_filter_expr = combined_filter_expr & current_expr

    if combined_filter_expr is not None:
        await ctx.info(f"Applying combined filter expression: {combined_filter_expr}")
        return df.filter(combined_filter_expr)
    return df


async def _build_polars_aggregation_expressions(
    aggregations: list[Aggregation],
    group_by_column_names: set[str],
    existing_df_columns: set[str],
    ctx: Context,
) -> tuple[list[pl.Expr], set[str]]:
    polars_expressions: list[pl.Expr] = []
    all_output_column_names: set[str] = set(group_by_column_names)

    for agg_config in aggregations:
        if agg_config.column not in existing_df_columns:
            raise ValueError(
                f"Aggregation column '{agg_config.column}' not found in DataFrame."
            )
        for func_enum in agg_config.functions:
            function_name_str = func_enum.value
            output_alias = agg_config.rename.get(
                function_name_str, f"{agg_config.column}_{function_name_str}"
            )
            if output_alias in all_output_column_names:
                raise ValueError(f"Duplicate output column name: '{output_alias}'.")
            all_output_column_names.add(output_alias)
            try:
                column_expression = pl.col(agg_config.column)
                aggregation_function = getattr(column_expression, function_name_str)

                final_expression = aggregation_function().alias(output_alias)
                polars_expressions.append(final_expression)
            except AttributeError:
                raise ValueError(
                    f"Invalid aggregation function '{function_name_str}' for Polars on column '{agg_config.column}'."
                )
            except Exception as e:
                logger.warning(
                    f"Could not build expression for {agg_config.column}.{function_name_str}(): {e}"
                )
                raise ValueError(
                    f"Error building expression for {agg_config.column}.{function_name_str}(): {e}"
                )
    return polars_expressions, all_output_column_names


def _apply_calculated_fields(
    df: pl.DataFrame,
    calculated_field_configs: list[CalculatedFieldType],
    all_current_column_names: set[str],
    ctx: Context,
) -> pl.DataFrame:
    if not calculated_field_configs:
        return df

    available_columns_during_calculation = set(all_current_column_names)
    result_df = df

    for field_config in calculated_field_configs:
        output_col_name = field_config.output_column_name

        if output_col_name in available_columns_during_calculation:
            raise ValueError(
                f"Calculated field output name '{output_col_name}' conflicts with an existing or previously calculated column."
            )

        def _check_input_columns_exist(*cols_to_check: str) -> None:
            for col_name in cols_to_check:
                if col_name not in available_columns_during_calculation:
                    raise ValueError(
                        f"Input column '{col_name}' for calculated field '{output_col_name}' not found. "
                        f"Available columns: {sorted(list(available_columns_during_calculation))}"
                    )

        polars_expr: pl.Expr

        if field_config.calculation_type == "two_column_arithmetic":
            cfg = field_config
            _check_input_columns_exist(cfg.column_a, cfg.column_b)
            col_a_expr = pl.col(cfg.column_a)
            col_b_expr = pl.col(cfg.column_b)
            op_map = {
                ArithmeticOperationType.ADD: lambda a, b: a + b,
                ArithmeticOperationType.SUBTRACT: lambda a, b: a - b,
                ArithmeticOperationType.MULTIPLY: lambda a, b: a * b,
                ArithmeticOperationType.DIVIDE: lambda a, b: a / b,
            }
            polars_expr = op_map[cfg.operation](col_a_expr, col_b_expr)

            if (
                cfg.operation == ArithmeticOperationType.DIVIDE
                and cfg.on_division_by_zero != "propagate_error"
            ):
                otherwise_val = (
                    None
                    if cfg.on_division_by_zero == "null"
                    else pl.lit(cfg.on_division_by_zero, dtype=pl.Float64)
                )
                polars_expr = (
                    pl.when(col_b_expr != 0).then(polars_expr).otherwise(otherwise_val)
                )
        elif field_config.calculation_type == "constant_arithmetic":
            cfg = field_config
            _check_input_columns_exist(cfg.input_column)
            input_col_expr = pl.col(cfg.input_column)
            constant_expr = pl.lit(cfg.constant_value)

            # First, check if we have a division by zero scenario with the constant
            if (
                cfg.operation == ArithmeticOperationType.DIVIDE
                and cfg.on_division_by_zero != "propagate_error"
            ):

                if cfg.column_is_first_operand and cfg.constant_value == 0:
                    # column / 0 - always results in the fallback value
                    if cfg.on_division_by_zero == "null":
                        polars_expr = pl.lit(None, dtype=pl.Float64)
                    else:
                        polars_expr = pl.lit(cfg.on_division_by_zero, dtype=pl.Float64)

                elif not cfg.column_is_first_operand:
                    # constant / column - need to check column values
                    base_expr = constant_expr / input_col_expr
                    otherwise_val = (
                        None
                        if cfg.on_division_by_zero == "null"
                        else pl.lit(cfg.on_division_by_zero, dtype=pl.Float64)
                    )
                    polars_expr = (
                        pl.when(input_col_expr != 0)
                        .then(base_expr)
                        .otherwise(otherwise_val)
                    )

                else:
                    # column / non-zero constant - normal division
                    polars_expr = input_col_expr / constant_expr

            else:
                # Not division or propagate_error - just do the operation
                op_map_col_first = {
                    ArithmeticOperationType.ADD: lambda col, const: col + const,
                    ArithmeticOperationType.SUBTRACT: lambda col, const: col - const,
                    ArithmeticOperationType.MULTIPLY: lambda col, const: col * const,
                    ArithmeticOperationType.DIVIDE: lambda col, const: col / const,
                }
                op_map_const_first = {
                    ArithmeticOperationType.ADD: lambda const, col: const + col,
                    ArithmeticOperationType.SUBTRACT: lambda const, col: const - col,
                    ArithmeticOperationType.MULTIPLY: lambda const, col: const * col,
                    ArithmeticOperationType.DIVIDE: lambda const, col: const / col,
                }

                if cfg.column_is_first_operand:
                    polars_expr = op_map_col_first[cfg.operation](
                        input_col_expr, constant_expr
                    )
                else:
                    polars_expr = op_map_const_first[cfg.operation](
                        constant_expr, input_col_expr
                    )

        elif field_config.calculation_type == "percentage_of_column":
            cfg = field_config
            _check_input_columns_exist(cfg.value_column, cfg.total_reference_column)
            value_col_expr = pl.col(cfg.value_column)
            total_ref_col_expr = pl.col(cfg.total_reference_column)
            polars_expr = (value_col_expr / total_ref_col_expr) * cfg.scale_factor

            if cfg.on_division_by_zero != "propagate_error":
                otherwise_val = (
                    None
                    if cfg.on_division_by_zero == "null"
                    else pl.lit(cfg.on_division_by_zero, dtype=pl.Float64)
                )
                polars_expr = (
                    pl.when(total_ref_col_expr != 0)
                    .then(polars_expr)
                    .otherwise(otherwise_val)
                )
        else:
            w = ctx.error(
                f"Unsupported calculated_field type: {getattr(field_config, 'calculation_type', 'Unknown')}"
            )
            raise ValueError(
                f"Unsupported calculated_field type: {getattr(field_config, 'calculation_type', 'Unknown')}"
            )

        result_df = result_df.with_columns(polars_expr.alias(output_col_name))
        available_columns_during_calculation.add(output_col_name)

    return result_df


async def aggregate_data(
    ctx: Context,
    dataframe_name: str,
    request: AggregationRequest,
) -> list[dict[str, Any]] | dict[str, Any]:
    """
    Performs powerful data aggregation, grouping, and calculations on a specified dataset.


    Before using this tool, ensure you have the correct DataFrame names and valid column names
    or filter values. You can discover available DataFrames and their columns using the
    `list_available_dataframes()` tool. Discover valid values for filter conditions
    is done by using get_distinct_column_values.

    This is the primary tool for summarizing data, finding trends, calculating metrics,
    and deriving new insights from the available CSV datasets. It allows you to:
    1. Group data by one or more columns.
    2. Apply multiple aggregation functions (sum, mean, count, min, max) to different columns.
    3. Create new columns based on arithmetic operations or percentage calculations, either on
       aggregated results or on original data.
    4. Optionally, include a summary row at the end of the results with configurable aggregations.

    Args:
        ctx: The MCP context (automatically provided).
        dataframe_name (str): The name of the DataFrame to process.
            Discover available DataFrames using the `list_available_dataframes()` tool.
        request (AggregationRequest): A Pydantic model detailing the aggregation and
            calculation steps. See details below.

    Returns:
        list[dict[str, Any]]: A list of dictionaries, where each dictionary represents
            a row in the resulting aggregated and calculated table.
        dict[str, Any]: An error dictionary if an issue occurs (e.g., column not found,
            invalid request structure).

    **Structure of the `AggregationRequest` object:**

    The `request` argument must be a JSON object with the following structure:

    ```json
    {
      "filters": [
        {
          "column": "column_name_to_filter",
          "operator": "equals",
          "value": "some_value",
        }
      ],
      "group_by_columns": ["column_name1", "column_name2"],
      "aggregations": [
        {
          "column": "numeric_column_to_aggregate",
          "functions": ["sum", "mean"],
          "rename": { "sum": "total_value", "mean": "average_value" }
        }
      ],
      "calculated_fields": [
        {
          "calculation_type": "two_column_arithmetic",
          "output_column_name": "profit_margin",
          "column_a": "total_revenue_agg",
          "column_b": "total_cost_agg",
          "operation": "subtract"
        }
      ],
      "summary_settings": { // ADDED THIS SECTION
        "enabled": true,
        "first_group_by_column_label": "Grand Total",
        "default_numeric_summary_function": "sum",
        "column_specific_summaries": [
          { "column_name": "some_string_column", "summary_function": "label", "label_text": "All Items" }
        ]
      } // END ADDED SECTION
    }
    ```

    **Detailed breakdown of `AggregationRequest` fields:**

    0.  **`filters: list[FilterCondition] | None` (Optional)**
        *   A list of `FilterCondition` objects, each defining a criterion to filter the source DataFrame
            *before* any grouping or aggregation takes place.
        *   All conditions in the list are combined using AND logic.
        *   Each `FilterCondition` has: `column`, `operator`, `value`. (See prompt for details)

    1.  **`group_by_columns: list[str]` (Required)**
        *   Column names to group by. These columns will be in the output.

    2.  **`aggregations: list[Aggregation] | None` (Optional)**
        *   List of `Aggregation` objects for summarizing columns.
        *   Each `Aggregation` has: `column`, `functions` (list of `AggFunc`), `rename` (optional dict).
        *   Supported `AggFunc`: `"sum"`, `"mean"`, `"count"`, `"min"`, `"max"`.

    3.  **`calculated_fields: list[CalculatedFieldType] | None` (Optional)**
        *   List of objects to create new columns *after* aggregations.
        *   Types: `TwoColumnArithmeticConfig`, `ConstantArithmeticConfig`, `PercentageOfColumnConfig`.
        *   Each needs `output_column_name` and `calculation_type`. (See prompt for details on each type)

    4.  **`summary_settings: SummaryRowSettings | None` (Optional)** # ADDED NEW FIELD DOC
        *   Settings for including a summary row at the end of the results.
        *   If omitted or `enabled` is `false`, no summary row is added.
        *   `enabled: bool` (Default: `false`): Set to `true` to add the summary row.
        *   `default_numeric_summary_function: SummaryFunction` (Default: `"sum"`): How to summarize numeric columns
            not specifically configured in `column_specific_summaries`.
            Options: `"sum"`, `"mean"`, `"count"`, `"min"`, `"max"`.
        *   `default_string_summary_function: SummaryFunction` (Default: `"none"`): How to summarize string or other
            non-numeric columns not specifically configured.
            Options: `"label"`, `"none"`, `"count"`.
        *   `first_group_by_column_label: str` (Default: `"Total"`): Label for the first `group_by_column`
            in the summary row (if not overridden).
        *   `column_specific_summaries: list[SummaryColumnConfiguration] | None`: A list to override default
            summary behavior for specific output columns.
            *   Each `SummaryColumnConfiguration` object has:
                *   `column_name: str` (Required): The name of an output column (from group-by, aggregation, or calculated field).
                *   `summary_function: SummaryFunction` (Required): The function to apply.
                    Options: `"sum"`, `"mean"`, `"count"`, `"min"`, `"max"`, `"label"`, `"none"`.
                *   `label_text: str | None` (Required if `summary_function` is `"label"`, otherwise ignored):
                    The text to display for this column in the summary row.

    **How to Use This Tool Effectively:**
    (Refer to the main prompt for detailed steps on discovering data, planning analysis, etc.)

    **Calculated Fields with No Aggregations:**
    (Refer to the main prompt for details.)

    **Example `AggregationRequest` with Summary Row:**
    ```json
    {
      "dataframe_name": "upphandlingsmyndigheten_antal_upphandlingar",
      "request": {
        "group_by_columns": ["År", "Sektor för köpare"],
        "aggregations": [
          {
            "column": "Antal upphandlingar, Antal",
            "functions": ["sum"],
            "rename": { "sum": "Totala_Antal_Upphandlingar_Värde" }
          },
          {
            "column": "Upphandlings-ID",
            "functions": ["count"],
            "rename": { "count": "Antal_Upphandlingstillfällen" }
          }
        ],
        "calculated_fields": [
          {
            "calculation_type": "two_column_arithmetic",
            "output_column_name": "Genomsnittligt_Värde_Per_Tillfälle",
            "column_a": "Totala_Antal_Upphandlingar_Värde",
            "column_b": "Antal_Upphandlingstillfällen",
            "operation": "divide",
            "on_division_by_zero": "null"
          }
        ],
        "summary_settings": {
          "enabled": true,
          "first_group_by_column_label": "Alla År Totalt",
          "default_numeric_summary_function": "sum",
          "column_specific_summaries": [
            { "column_name": "Sektor för köpare", "summary_function": "label", "label_text": "Alla Sektorer" },
            { "column_name": "Genomsnittligt_Värde_Per_Tillfälle", "summary_function": "mean" }
          ]
        }
      }
    }
    ```
    This tool is designed to be flexible. If your query is complex, break it down into these
    components (filtering, grouping, aggregation, calculation, summary) to construct the request.
    """
    await ctx.info(
        f"Received aggregation request for DataFrame '{dataframe_name}': "
        f"Filters: {'Present' if request.filters else 'None/Empty'}, "
        f"Group by {request.group_by_columns}, "
        f"Aggregations: {'Present and non-empty' if request.aggregations and len(request.aggregations) > 0 else 'None/Empty'}, "
        f"Calculated Fields: {'Present' if request.calculated_fields else 'None/Empty'}, "
        f"Summary Row: {'Enabled' if request.summary_settings and request.summary_settings.enabled else 'Disabled'}."
    )

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
        source_df: pl.DataFrame = df_dict[dataframe_name]
    except KeyError:
        await ctx.error(
            "DataFrame dictionary 'dataframes' not found in lifespan context."
        )
        return {"error": "DataFrames not available. Server may be misconfigured."}

    df_column_names = set(source_df.columns)

    filtered_df = source_df
    if request.filters:
        try:
            await ctx.info(
                f"Applying {len(request.filters)} filter(s) to DataFrame '{dataframe_name}' before aggregation."
            )
            filtered_df = await _apply_filters(
                source_df, request.filters, df_column_names, ctx
            )
            await ctx.info(
                f"DataFrame '{dataframe_name}' shape after filtering: {filtered_df.shape}. Original shape: {source_df.shape}"
            )
            if filtered_df.is_empty():
                await ctx.warning(
                    f"DataFrame '{dataframe_name}' is empty after applying filters. No data to aggregate."
                )
                return []
        except ValueError as ve:
            await ctx.error(f"Error applying filters to '{dataframe_name}': {ve}")
            logger.error(
                f"Filter application error for '{dataframe_name}': {ve}", exc_info=True
            )
            return {"error": f"Filter error: {str(ve)}"}

    for col in request.group_by_columns:
        if col not in df_column_names:
            await ctx.error(
                f"Invalid group_by_column for DataFrame '{dataframe_name}': '{col}' not found. Available: {list(df_column_names)}"
            )
            return {
                "error": f"Invalid group_by_column: '{col}' not found in '{dataframe_name}'."
            }

    if request.aggregations:
        for agg_config in request.aggregations:
            if agg_config.column not in df_column_names:
                await ctx.error(
                    f"Invalid aggregation source column for DataFrame '{dataframe_name}': '{agg_config.column}' not found. Available: {list(df_column_names)}"
                )
                return {
                    "error": f"Invalid aggregation source column: '{agg_config.column}' not found in '{dataframe_name}'."
                }

    try:
        intermediate_df: pl.DataFrame
        columns_after_aggregation_or_grouping: set[str]

        if request.aggregations and len(request.aggregations) > 0:
            (
                polars_agg_expressions,
                aggregated_column_names,
            ) = await _build_polars_aggregation_expressions(
                request.aggregations,
                set(request.group_by_columns),
                df_column_names,
                ctx,
            )
            grouped_df = filtered_df.group_by(
                request.group_by_columns, maintain_order=True
            )
            intermediate_df = grouped_df.agg(polars_agg_expressions)
            columns_after_aggregation_or_grouping = aggregated_column_names
            await ctx.info(
                f"Performed aggregation on '{dataframe_name}'. Resulting columns: {intermediate_df.columns}"
            )
        else:
            if not request.group_by_columns:
                await ctx.error("`group_by_columns` must be provided.")
                return {
                    "error": "`group_by_columns` must be provided even if no aggregations are performed."
                }
            intermediate_df = filtered_df.select(request.group_by_columns).unique(
                maintain_order=True
            )
            columns_after_aggregation_or_grouping = set(request.group_by_columns)
            await ctx.info(
                f"No aggregations requested for '{dataframe_name}'. Initial columns for potential calculated fields: {intermediate_df.columns} (based on group_by from filtered data)."
            )

        if request.calculated_fields:
            cols_available_for_calc: set[str]
            df_for_calc: pl.DataFrame

            if request.aggregations and len(request.aggregations) > 0:
                df_for_calc = intermediate_df
                cols_available_for_calc = columns_after_aggregation_or_grouping
            else:
                df_for_calc = intermediate_df
                cols_available_for_calc = df_column_names

            final_df = await asyncio.to_thread(
                _apply_calculated_fields,
                df_for_calc,
                request.calculated_fields,
                cols_available_for_calc,
                ctx,
            )
            await ctx.info(
                f"Applied calculated fields to '{dataframe_name}'. Resulting columns: {final_df.columns}"
            )
            if not (request.aggregations and len(request.aggregations) > 0):
                temp_output_cols = list(request.group_by_columns) + [
                    cf.output_column_name for cf in request.calculated_fields
                ]
                temp_output_cols = [
                    col for col in temp_output_cols if col in final_df.columns
                ]
                if not temp_output_cols:
                    await ctx.warning(
                        f"Calculated fields on original data for '{dataframe_name}' did not produce any of the requested group_by or output columns. Returning empty."
                    )
                    return []
                final_df = final_df.select(temp_output_cols)
        else:
            final_df = intermediate_df

        columns_to_select_final = list(request.group_by_columns)

        if request.aggregations and len(request.aggregations) > 0:
            for alias in columns_after_aggregation_or_grouping:
                if alias not in columns_to_select_final:
                    columns_to_select_final.append(alias)

        if request.calculated_fields:
            for cf_item in request.calculated_fields:
                if cf_item.output_column_name not in columns_to_select_final:
                    columns_to_select_final.append(cf_item.output_column_name)

        final_columns_present_in_df = [
            col for col in columns_to_select_final if col in final_df.columns
        ]

        if not final_columns_present_in_df:
            await ctx.warning(
                f"No valid output columns to select in the final DataFrame for '{dataframe_name}'. "
                f"Requested: {columns_to_select_final}, Available in final_df: {final_df.columns}. "
            )
            if (
                all(
                    gb_col in filtered_df.columns for gb_col in request.group_by_columns
                )
                and set(final_columns_present_in_df) == set(request.group_by_columns)
                and not (request.aggregations and len(request.aggregations) > 0)
                and not request.calculated_fields
            ):
                final_df_to_return = filtered_df.select(
                    request.group_by_columns
                ).unique(maintain_order=True)
            elif not request.group_by_columns:
                return []
            else:
                valid_gb_cols = [
                    gbc for gbc in request.group_by_columns if gbc in final_df.columns
                ]
                if valid_gb_cols:
                    final_df_to_return = final_df.select(valid_gb_cols).unique(
                        maintain_order=True
                    )
                else:
                    return []
        else:
            final_df_to_return = final_df.select(final_columns_present_in_df)

        if not (request.aggregations and len(request.aggregations) > 0):
            if final_df_to_return.height > 0 and final_df_to_return.columns:
                final_df_to_return = final_df_to_return.unique(
                    subset=final_df_to_return.columns, maintain_order=True
                )

        sortable_group_by_cols = [
            gbc for gbc in request.group_by_columns if gbc in final_df_to_return.columns
        ]
        if sortable_group_by_cols:
            final_df_to_return = final_df_to_return.sort(sortable_group_by_cols)

        results_list_of_dicts = final_df_to_return.to_dicts()

        if request.summary_settings and request.summary_settings.enabled:
            if not results_list_of_dicts and not final_df_to_return.is_empty():
                pass

            summary_row_dict: dict[str, Any] = {}
            output_columns = final_df_to_return.columns

            specific_configs_map: dict[str, SummaryColumnConfiguration] = {}
            if request.summary_settings.column_specific_summaries:
                for sc_cfg in request.summary_settings.column_specific_summaries:
                    if sc_cfg.column_name not in output_columns:
                        await ctx.warning(
                            f"Summary configuration for column '{sc_cfg.column_name}' provided, but this column is not in the final output. Ignoring."
                        )
                        continue
                    specific_configs_map[sc_cfg.column_name] = sc_cfg

            for col_idx, col_name in enumerate(output_columns):
                summary_value: Any = None
                col_series = final_df_to_return[col_name]
                col_dtype = col_series.dtype

                specific_config = specific_configs_map.get(col_name)

                if specific_config:
                    if specific_config.summary_function == SummaryFunction.LABEL:
                        summary_value = specific_config.label_text
                    elif specific_config.summary_function == SummaryFunction.NONE:
                        summary_value = None
                    else:
                        try:
                            if (
                                final_df_to_return.is_empty()
                                and specific_config.summary_function
                                != SummaryFunction.COUNT
                            ):
                                summary_value = None
                            elif (
                                specific_config.summary_function
                                == SummaryFunction.COUNT
                            ):
                                summary_value = col_series.count()
                            elif col_dtype in pl.NUMERIC_DTYPES:
                                agg_method = getattr(
                                    col_series, specific_config.summary_function.value
                                )
                                summary_value = agg_method()
                            else:
                                await ctx.warning(
                                    f"Cannot apply numeric summary '{specific_config.summary_function.value}' to non-numeric column '{col_name}' (type: {col_dtype}). Setting summary to None."
                                )
                                summary_value = None
                        except Exception as e:
                            await ctx.warning(
                                f"Error applying summary function '{specific_config.summary_function.value}' to column '{col_name}': {e}. Setting to None."
                            )
                            summary_value = None
                else:
                    is_first_group_by_col = (
                        request.group_by_columns
                        and col_name == request.group_by_columns[0]
                        and col_idx == 0
                    )

                    if is_first_group_by_col:
                        summary_value = (
                            request.summary_settings.first_group_by_column_label
                        )
                    elif col_name in request.group_by_columns:
                        summary_value = None
                    elif col_dtype in pl.NUMERIC_DTYPES:
                        func_to_apply = (
                            request.summary_settings.default_numeric_summary_function
                        )
                        if (
                            final_df_to_return.is_empty()
                            and func_to_apply != SummaryFunction.COUNT
                        ):
                            summary_value = None
                        elif func_to_apply == SummaryFunction.COUNT:
                            summary_value = col_series.count()
                        else:
                            try:
                                agg_method = getattr(col_series, func_to_apply.value)
                                summary_value = agg_method()
                            except Exception as e:
                                await ctx.warning(
                                    f"Error applying default numeric summary '{func_to_apply.value}' to column '{col_name}': {e}. Setting to None."
                                )
                                summary_value = None
                    else:
                        func_to_apply = (
                            request.summary_settings.default_string_summary_function
                        )
                        if func_to_apply == SummaryFunction.LABEL:
                            await ctx.warning(
                                f"Default string summary is 'label' for column '{col_name}' but no specific label_text. Setting to None."
                            )
                            summary_value = None
                        elif func_to_apply == SummaryFunction.COUNT:
                            summary_value = col_series.count()
                        else:
                            summary_value = None

                summary_row_dict[col_name] = summary_value

            results_list_of_dicts.append(summary_row_dict)
            await ctx.info(f"Added summary row to results for '{dataframe_name}'.")

        await ctx.info(
            f"Aggregation/calculation for '{dataframe_name}' successful. Final result shape (before to_dicts, excluding summary): {final_df_to_return.shape}, Columns: {final_df_to_return.columns}"
        )
        return results_list_of_dicts

    except ValueError as ve:
        await ctx.error(
            f"ValueError during aggregation processing for '{dataframe_name}': {ve}"
        )
        logger.error(f"Detailed ValueError for '{dataframe_name}': {ve}", exc_info=True)
        return {"error": f"Configuration or processing error: {str(ve)}"}
    except pl.PolarsError as pe:
        await ctx.error(
            f"Polars error during aggregation for '{dataframe_name}': {pe}",
            exc_info=True,
        )
        return {"error": f"Data processing error with Polars: {str(pe)}"}
    except Exception as e:
        await ctx.error(
            f"An unexpected error occurred during aggregation for '{dataframe_name}': {e}",
            exc_info=True,
        )
        return {"error": f"An unexpected server error occurred: {str(e)}"}
