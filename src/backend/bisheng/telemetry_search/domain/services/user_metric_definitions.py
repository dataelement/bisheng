from ..models.dashboard_dataset import MetricConfig
from ..schemas.query_builder import AggregationExpression, AggsTypeEnum, FilterExpression, TermOp

USER_STAT_DATASETS = {"mid_user_increment", "mid_active_user", "mid_user_daily_participation"}


def active_user_metric() -> MetricConfig:
    """活跃人数与参与度分子只统计期间成功登录的去重人员."""
    return MetricConfig(
        field="active_user_count",
        name="活跃用户数",
        is_virtual=True,
        filter=FilterExpression(
            bool_operator="must",
            filters=[
                TermOp(field="metric_source", value="participation"),
                TermOp(field="logged_in", value=True),
            ],
        ),
        aggregations=[AggregationExpression(name="active_user_count", type=AggsTypeEnum.CARDINALITY, field="user_id")],
    )
