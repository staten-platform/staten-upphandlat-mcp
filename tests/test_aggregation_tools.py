import sys
import types
from unittest.mock import AsyncMock
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from upphandlat_mcp.models.mcp_models import (
    AggFunc,
    Aggregation,
    AggregationRequest,
    ArithmeticOperationType,
    FilterCondition,
    FilterOperator,
    PercentageOfColumnConfig,
    SummaryRowSettings,
    TwoColumnArithmeticConfig,
)
from upphandlat_mcp.tools.aggregation import aggregate_data
from statens_mima import MCPSharedCache, CacheStats 
pl = pytest.importorskip("polars")

EXPECTED_PROFIT_A = 12
EXPECTED_TOTAL_VALUE = 35
EXPECTED_VALUE_SUM_A = 30
EXPECTED_VALUE_MEAN_A = 15
EXPECTED_RATIO_A = 230.769


class DummyCtx:
    def __init__(self, lifespan_context: dict[str, object]):
        self.request_context = types.SimpleNamespace(lifespan_context=lifespan_context)
        self.server = types.SimpleNamespace(name="test_server") 

    async def info(self, *args, **kwargs):
        pass

    async def error(self, *args, **kwargs):
        pass

    async def warning(self, *args, **kwargs):
        pass

    async def report_progress(self, *args, **kwargs):
        pass


@pytest.fixture()
def sample_agg_context(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("category;value;cost\nA;10;5\nA;20;8\nB;5;4\nB;15;16\n")
    df = pl.read_csv(csv_path, separator=";")

    mock_shared_cache = AsyncMock(spec=MCPSharedCache)
    async def get_df_side_effect(tool_name, server_name, params, **kwargs):
        if params.get("source_name") == "sample":
            return df
        return None
    mock_shared_cache.get_dataframe.side_effect = get_df_side_effect
    mock_shared_cache.health_check.return_value = CacheStats(status="healthy")

    lifespan = {
        "shared_cache": mock_shared_cache,
        "available_dataframe_names": ["sample"],
        "settings": None,
        "csv_sources_config": None,
    }
    return lifespan


@pytest.mark.asyncio
async def test_basic_aggregation(sample_agg_context):
    ctx = DummyCtx(sample_agg_context)
    req = AggregationRequest(
        group_by_columns=["category"],
        aggregations=[Aggregation(column="value", functions=[AggFunc.SUM])],
    )
    result = await aggregate_data(ctx, "sample", req)
    expected = [
        {"category": "A", "value_sum": 30},
        {"category": "B", "value_sum": 20},
    ]
    assert result == expected


@pytest.mark.asyncio
async def test_filter_and_calculation(sample_agg_context):
    ctx = DummyCtx(sample_agg_context)
    req = AggregationRequest(
        filters=[
            FilterCondition(
                column="cost",
                operator=FilterOperator.GREATER_THAN,
                value=5,
            )
        ],
        group_by_columns=["category"],
        aggregations=[
            Aggregation(
                column="value",
                functions=[AggFunc.SUM],
                rename={"sum": "value_sum"},
            ),
            Aggregation(
                column="cost",
                functions=[AggFunc.SUM],
                rename={"sum": "cost_sum"},
            ),
        ],
        calculated_fields=[
            TwoColumnArithmeticConfig(
                output_column_name="profit",
                column_a="value_sum",
                column_b="cost_sum",
                operation=ArithmeticOperationType.SUBTRACT,
            )
        ],
        summary_settings=SummaryRowSettings(enabled=True),
    )
    result = await aggregate_data(ctx, "sample", req)
    assert result[0]["category"] == "A"
    assert result[0]["profit"] == EXPECTED_PROFIT_A  # 20 - 8
    assert result[1]["category"] == "B"
    assert result[1]["profit"] == -1  # 15 - 16
    summary = result[-1]
    assert summary["category"] == "Total"
    assert summary["value_sum"] == EXPECTED_TOTAL_VALUE


@pytest.mark.asyncio
async def test_multi_aggregations_with_percentage(sample_agg_context):
    ctx = DummyCtx(sample_agg_context)
    req = AggregationRequest(
        group_by_columns=["category"],
        aggregations=[
            Aggregation(column="value", functions=[AggFunc.SUM, AggFunc.MEAN]),
            Aggregation(column="cost", functions=[AggFunc.SUM]),
        ],
        calculated_fields=[
            PercentageOfColumnConfig(
                output_column_name="value_cost_ratio",
                value_column="value_sum",
                total_reference_column="cost_sum",
                scale_factor=100.0,
                on_division_by_zero="null",
            )
        ],
    )
    result = await aggregate_data(ctx, "sample", req)
    assert result[0]["value_sum"] == EXPECTED_VALUE_SUM_A
    assert result[0]["value_mean"] == EXPECTED_VALUE_MEAN_A
    assert result[0]["value_cost_ratio"] == pytest.approx(EXPECTED_RATIO_A, rel=1e-3)

