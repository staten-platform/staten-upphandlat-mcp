from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AggFunc(str, Enum):
    """Supported aggregation functions."""

    SUM = "sum"
    MEAN = "mean"
    COUNT = "count"
    MIN = "min"
    MAX = "max"


class Aggregation(BaseModel):
    """
    Defines an aggregation operation on a single column.
    """

    column: str = Field(..., description="The column to aggregate.")
    functions: list[AggFunc] = Field(
        ..., min_length=1, description="List of aggregation functions to apply."
    )
    rename: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional mapping to rename output columns. "
            "Keys should be function names (e.g., 'sum'), "
            "values are the new names (e.g., 'total_sales'). "
            "Default is '{column}_{function}'."
        ),
    )

    @model_validator(mode="after")
    def check_rename_keys(self) -> "Aggregation":
        defined_functions = {f.value for f in self.functions}
        for key_to_rename in self.rename:
            if key_to_rename not in defined_functions:
                raise ValueError(
                    f"Rename key '{key_to_rename}' is not in the list of "
                    f"applied functions: {list(defined_functions)} for column '{self.column}'. "
                    "Rename keys must match one of the function names (sum, mean, etc.)."
                )
        return self


class SummaryFunction(str, Enum):
    """Defines the function to apply for summarizing a column in the summary row."""

    SUM = "sum"
    MEAN = "mean"
    COUNT = "count"
    MIN = "min"
    MAX = "max"
    LABEL = "label"
    NONE = "none"


class SummaryColumnConfiguration(BaseModel):
    """Configuration for summarizing a single column in the summary row."""

    column_name: str = Field(..., description="The name of the column to configure.")
    summary_function: SummaryFunction = Field(
        ..., description="The function to apply for this column's summary."
    )
    label_text: str | None = Field(
        None,
        description="The text to display if summary_function is 'label'. Required if 'label', otherwise ignored.",
    )

    @model_validator(mode="after")
    def check_label_text_for_label_function(self) -> "SummaryColumnConfiguration":
        if self.summary_function == SummaryFunction.LABEL and self.label_text is None:
            raise ValueError(
                f"label_text must be provided when summary_function is 'label' for column '{self.column_name}'."
            )
        if (
            self.summary_function != SummaryFunction.LABEL
            and self.label_text is not None
        ):
            pass
        return self


class SummaryRowSettings(BaseModel):
    """Settings for including an optional summary row at the end of the aggregation results."""

    enabled: bool = Field(
        False, description="Set to true to include a summary row in the output."
    )
    default_numeric_summary_function: SummaryFunction = Field(
        SummaryFunction.SUM,
        description="Default summary function for numeric columns not explicitly configured. Must be an aggregate type (sum, mean, etc.), not 'label' or 'none'.",
    )
    default_string_summary_function: SummaryFunction = Field(
        SummaryFunction.NONE,
        description="Default summary function for string or other non-numeric columns not explicitly configured. Typically 'none' or 'label'.",
    )
    first_group_by_column_label: str = Field(
        "Total",
        description="Default label for the first group_by column in the summary row (if not overridden by column_specific_summaries).",
    )
    column_specific_summaries: list[SummaryColumnConfiguration] | None = Field(
        None,
        description="List of specific configurations for individual columns, overriding defaults.",
    )

    @model_validator(mode="after")
    def check_default_numeric_function(self) -> "SummaryRowSettings":
        if self.default_numeric_summary_function in [
            SummaryFunction.LABEL,
            SummaryFunction.NONE,
        ]:
            raise ValueError(
                "default_numeric_summary_function must be an aggregate type (e.g., 'sum', 'mean'), not 'label' or 'none'."
            )
        return self


class FilterOperator(str, Enum):
    """Supported filter operations."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL_TO = "greater_than_or_equal_to"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL_TO = "less_than_or_equal_to"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class FilterCondition(BaseModel):
    """Defines a single filter condition to apply to a DataFrame."""

    column: str = Field(..., description="The column to filter on.")
    operator: FilterOperator = Field(..., description="The comparison operator to use.")
    value: Any | None = Field(
        None,
        description=(
            "The value to compare against. "
            "Required for most operators. For 'IN' or 'NOT_IN', this must be a list. "
            "For 'IS_NULL' or 'IS_NOT_NULL', this field is ignored and should be null."
        ),
    )
    case_sensitive: bool = Field(
        False,
        description=(
            "For string comparison operators (equals, not_equals, contains, starts_with, ends_with), "
            "specifies if the comparison should be case-sensitive. "
            "Defaults to False (case-insensitive). Set to True for case-sensitive matching. "
            "Not applicable to other operators or non-string values."
        ),
    )

    @model_validator(mode="after")
    def check_value_for_operator(self) -> "FilterCondition":
        if self.operator in [FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL]:
            if self.value is not None:
                self.value = None
        elif self.operator in [FilterOperator.IN, FilterOperator.NOT_IN]:
            if not isinstance(self.value, list):
                raise ValueError(
                    f"For operator '{self.operator.value}', 'value' must be a list. Got: {type(self.value)}"
                )
            if not self.value:
                raise ValueError(
                    f"For operator '{self.operator.value}', 'value' list cannot be empty."
                )
        elif self.value is None:
            raise ValueError(
                f"Operator '{self.operator.value}' requires a 'value', but it was not provided or is null."
            )

        return self


class BaseCalculatedField(BaseModel):
    """
    Base settings for a calculated field.
    """

    output_column_name: str = Field(
        ...,
        description="The name for the new calculated column.",
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
    )

    @field_validator("output_column_name")
    @classmethod
    def no_reserved_output_name(cls, name: str) -> str:
        return name


class ArithmeticOperationType(str, Enum):
    """Type of arithmetic operation."""

    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"


class TwoColumnArithmeticConfig(BaseCalculatedField):
    """Configuration for arithmetic operation between two existing columns."""

    calculation_type: Literal["two_column_arithmetic"] = Field(
        "two_column_arithmetic", description="Type of calculation."
    )
    column_a: str = Field(..., description="The first column operand (e.g., 'sales').")
    column_b: str = Field(..., description="The second column operand (e.g., 'cost').")
    operation: ArithmeticOperationType = Field(
        ...,
        description="The arithmetic operation to perform (e.g., 'subtract' for A - B).",
    )
    on_division_by_zero: float | Literal["null", "propagate_error"] = Field(
        "propagate_error",
        description="Behavior for division by zero: a specific float, 'null', or 'propagate_error' (Polars default, may result in inf/NaN).",
    )


class ConstantArithmeticConfig(BaseCalculatedField):
    """Configuration for arithmetic operation between a column and a constant."""

    calculation_type: Literal["constant_arithmetic"] = Field(
        "constant_arithmetic", description="Type of calculation."
    )
    input_column: str = Field(..., description="The column to operate on.")
    constant_value: float = Field(
        ..., description="The constant value for the operation."
    )
    operation: ArithmeticOperationType = Field(
        ..., description="The arithmetic operation."
    )
    column_is_first_operand: bool = Field(
        True,
        description="If true, operation is 'input_column op constant'; else 'constant op input_column'.",
    )
    on_division_by_zero: float | Literal["null", "propagate_error"] = Field(
        "propagate_error", description="Behavior for division by zero (if applicable)."
    )


class PercentageOfColumnConfig(BaseCalculatedField):
    """Configuration for calculating one column as a percentage of another."""

    calculation_type: Literal["percentage_of_column"] = Field(
        "percentage_of_column", description="Type of calculation."
    )
    value_column: str = Field(
        ..., description="The column representing the part/value (numerator)."
    )
    total_reference_column: str = Field(
        ..., description="The column representing the total/base (denominator)."
    )
    scale_factor: float = Field(
        100.0,
        description="Factor to multiply the ratio by (e.g., 100.0 for percentage).",
    )
    on_division_by_zero: float | Literal["null", "propagate_error"] = Field(
        "propagate_error",
        description="Behavior for division by zero in 'value_column / total_reference_column'.",
    )


CalculatedFieldType = (
    TwoColumnArithmeticConfig | ConstantArithmeticConfig | PercentageOfColumnConfig
)


class AggregationRequest(BaseModel):
    """
    Defines the request payload for the aggregation tool.
    It specifies how to filter data, how to group it, what aggregations to perform,
    any additional calculated fields, and optional summary row settings.
    """

    filters: list[FilterCondition] | None = Field(
        None,
        description="Optional list of conditions to filter the DataFrame before grouping and aggregation. Conditions are applied with AND logic.",
    )
    group_by_columns: list[str] = Field(
        ...,
        min_length=1,
        description="List of column names to group the data by.",
    )
    aggregations: list[Aggregation] | None = Field(
        None,
        description="List of aggregation operations to perform. Can be empty or None if only applying calculated fields to original grouped columns.",
    )
    calculated_fields: list[CalculatedFieldType] | None = Field(
        None,
        description="Optional list of calculated fields to derive. If aggregations are empty/None, these apply to original grouped columns, otherwise to aggregated columns.",
    )
    summary_settings: SummaryRowSettings | None = Field(
        None,
        description="Optional settings for adding a summary row at the end of the results.",
    )

    @model_validator(mode="after")
    def check_column_name_conflicts(self) -> "AggregationRequest":
        """
        Validate that output column names from aggregations and calculated fields
        do not conflict with each other or with group_by_columns.
        Also ensures that if aggregations is None/empty, calculated_fields refer
        to original columns (this part is implicitly handled by _apply_calculated_fields'
        column checking against `available_columns_during_calculation`).
        """
        all_output_names: set[str] = set(self.group_by_columns)

        if self.aggregations:
            for agg in self.aggregations:
                for func in agg.functions:
                    alias = agg.rename.get(func.value, f"{agg.column}_{func.value}")
                    if alias in all_output_names:
                        raise ValueError(
                            f"Duplicate output column name '{alias}' from aggregation conflicts with group_by or another aggregation."
                        )
                    all_output_names.add(alias)

        if self.calculated_fields:
            temp_available_cols = set(all_output_names)

            for calc_field_config in self.calculated_fields:
                output_name = calc_field_config.output_column_name
                if output_name in temp_available_cols:
                    raise ValueError(
                        f"Calculated field output name '{output_name}' conflicts with group_by, aggregation, or prior calculated columns."
                    )
                temp_available_cols.add(output_name)

        if self.summary_settings and self.summary_settings.column_specific_summaries:
            pass

        return self
