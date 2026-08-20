import pytest

from bisheng.telemetry_search.domain.models.dashboard_dataset import DimensionConfig
from bisheng.telemetry_search.domain.schemas.component import DimensionField
from bisheng.telemetry_search.domain.schemas.query_builder import AggsTypeEnum
from bisheng.telemetry_search.domain.services.component import DataQueryService


@pytest.mark.parametrize(
    ("configured_granularity", "expected_granularity"),
    [
        ("month", "month"),
        ("day", "day"),
        (None, "day"),
    ],
)
async def test_timestamp_dimension_uses_calendar_aggregation(
    configured_granularity,
    expected_granularity,
):
    dimensions = await DataQueryService.convert_dimensions(
        [
            DimensionField(
                fieldId="timestamp",
                fieldName="时间(日)",
                timeGranularity=configured_granularity,
            )
        ],
        {
            "timestamp": DimensionConfig(
                name="时间",
                field="timestamp",
                field_type="date",
                time_granularitys=["year", "month", "week", "day"],
            )
        },
    )

    assert dimensions[0].type == AggsTypeEnum.DATE_HISTOGRAM
    assert dimensions[0].time_interval == expected_granularity
    assert (
        dimensions[0].custom_params["calendar_interval"]
        == {
            "month": "1M",
            "day": "1d",
        }[expected_granularity]
    )
