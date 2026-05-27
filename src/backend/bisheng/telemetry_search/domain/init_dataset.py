from bisheng.core.database import get_async_db_session, get_database_connection
from bisheng.database.models.group import DefaultGroup
from bisheng.database.models.group_resource import GroupResourceDao, GroupResource, ResourceTypeEnum
from bisheng.telemetry_search.domain.models.dashboard import DashboardType
from bisheng.telemetry_search.domain.models.dashboard_dao import DashboardDao
from bisheng.telemetry_search.domain.models.dashboard_dataset import DashboardDataset, SchemaConfig, MetricConfig, \
    DimensionConfig, FormulaEnum
from bisheng.telemetry_search.domain.repositories.implementations.dataset_repository_impl import \
    DashboardDatasetRepositoryImpl
from bisheng.telemetry_search.domain.schemas.query_builder import AggregationExpression, AggsTypeEnum, PipelineTypeEnum, \
    FilterExpression, TermOp, \
    MatchAllOp

DASHBOARD_DATASET = [
    DashboardDataset(
        dataset_name="用户行为指标表",
        dataset_code="mid_user_increment",
        es_index_name="mid_user_increment",
        description="用户行为指标数据表",
        is_commercial_only=False,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="total_user_count",
                    name="总用户数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="user_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="user_id"
                        ),
                        AggregationExpression(
                            name="total_user_count",
                            type=PipelineTypeEnum.CUMULATIVE_SUM,
                            field="user_count"
                        )
                    ],
                    index=1,
                    sum_field="user_id"
                ),
                MetricConfig(
                    field="new_user_count",
                    is_virtual=True,
                    name="新增用户数",
                    aggregations=[
                        AggregationExpression(
                            name="new_user_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="user_id"
                        )
                    ]
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="活跃用户表",
        dataset_code="mid_active_user",
        es_index_name="mid_active_user",
        description="活跃用户数据表",
        is_commercial_only=True,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="active_user_count",
                    name="活跃用户数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="active_user_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="user_id"
                        )
                    ]
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="应用数量表",
        dataset_code="mid_app_increment",
        es_index_name="mid_app_increment",
        description="应用数量数据表",
        is_commercial_only=False,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="total_app_count",
                    name="总应用数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="app_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="app_id"
                        ),
                        AggregationExpression(
                            name="total_app_count",
                            type=PipelineTypeEnum.CUMULATIVE_SUM,
                            field="app_count"
                        )
                    ],
                    index=1,
                    sum_field="app_id"
                ),
                MetricConfig(
                    field="new_app_count",
                    name="新增应用数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="new_app_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="app_id"
                        )
                    ]
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id",
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name",
                ),
                DimensionConfig(
                    name="应用类型",
                    field="app_type"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="会话数量表",
        dataset_code="mid_sessions_increment",
        es_index_name="mid_sessions_increment",
        description="会话数量数据表",
        is_commercial_only=True,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="session_count",
                    name="会话次数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="session_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="session_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="platform_user_count",
                    name="使用人数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="source", value="platform")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="platform_user_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="user_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="api_call_count",
                    name="API调用次数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="source", value="api")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="api_call_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="session_id"
                        )
                    ]
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                ),
                DimensionConfig(
                    name="应用ID",
                    field="app_id"
                ),
                DimensionConfig(
                    name="应用名称",
                    field="app_name"
                ),
                DimensionConfig(
                    name="来源类型（平台/API）",
                    field="source"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="会话运行时长表",
        dataset_code="mid_session_run_dtl",
        es_index_name="mid_session_run_dtl",
        description="会话运行时长数据表",
        is_commercial_only=True,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="duration_seconds",
                    name="会话运行时长",
                    is_virtual=False,
                    filter=FilterExpression(bool_operator="must_not", filters=[
                        TermOp(field="duration_seconds", value=0)
                    ])
                ),
                MetricConfig(
                    field="max_concurrent_sessions",
                    name="最大同时在线会话数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="duration_seconds", value=0)
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="per_minute",
                            type=AggsTypeEnum.DATE_HISTOGRAM,
                            field="minute_ts",
                            custom_params={
                                "fixed_interval": "1m",
                                "min_doc_count": 1
                            },
                            aggs=[
                                AggregationExpression(
                                    name="online",
                                    type=AggsTypeEnum.CARDINALITY,
                                    field="event_id"
                                )
                            ]
                        ),
                        AggregationExpression(
                            name="max_online",
                            type=PipelineTypeEnum.MAX_BUCKET,
                            field="per_minute>online"
                        )
                    ],
                    index=1
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day", "hour"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                ),
                DimensionConfig(
                    name="应用ID",
                    field="app_id"
                ),
                DimensionConfig(
                    name="应用名称",
                    field="app_name"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="工具调用时长表",
        dataset_code="mid_tool_call_dtl",
        es_index_name="mid_tool_call_dtl",
        description="工具调用时长数据表",
        is_commercial_only=True,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="tool_call_count",
                    name="工具调用次数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="tool_call_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="tool_call_success_count",
                    name="工具调用成功次数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="status", value="success")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="tool_call_success_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="tool_call_success_rate",
                    name="工具调用成功率",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must",
                                            filters=[TermOp(field="status", value="success"), MatchAllOp(field="")]),
                    aggregations=[
                        AggregationExpression(
                            name="tool_call_success_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        ), AggregationExpression(
                            name="tool_call_total_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ],
                    formula=FormulaEnum.DIVIDE
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),

                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                ),
                DimensionConfig(
                    name="工具名称",
                    field="tool_name"
                ),
                DimensionConfig(
                    name="工具ID",
                    field="tool_id"
                ),
                DimensionConfig(
                    name="工具类型",
                    field="tool_type"
                ),
                DimensionConfig(
                    name="应用名称",
                    field="app_type"
                ),
                DimensionConfig(
                    name="应用ID",
                    field="app_id"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="知识库存量表",
        dataset_code="mid_knowledge_increment",
        es_index_name="mid_knowledge_increment",
        description="知识库存量数据表",
        is_commercial_only=False,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="total_document_knowledge_base_count",
                    name="总文档知识库数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="knowledge_type", value=0)
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="document_knowledge_base_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="knowledge_id"
                        ),
                        AggregationExpression(
                            name="total_document_knowledge_base_count",
                            type=PipelineTypeEnum.CUMULATIVE_SUM,
                            field="document_knowledge_base_count"
                        )
                    ],
                    index=1,
                    sum_field="knowledge_id"
                ),
                MetricConfig(
                    field="total_qa_knowledge_base_count",
                    name="总QA知识库数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="knowledge_type", value=1)
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="qa_knowledge_base_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="knowledge_id"
                        ),
                        AggregationExpression(
                            name="total_qa_knowledge_base_count",
                            type=PipelineTypeEnum.CUMULATIVE_SUM,
                            field="qa_knowledge_base_count"
                        )
                    ],
                    index=1,
                    sum_field="knowledge_id"
                ),
                MetricConfig(
                    field="new_document_knowledge_base_count",
                    name="新增文档知识库数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="knowledge_type", value=0)
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="new_document_knowledge_base_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="knowledge_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="new_qa_knowledge_base_count",
                    name="新增QA知识库数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="knowledge_type", value=1)
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="new_qa_knowledge_base_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="knowledge_id"
                        )
                    ]
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="知识库文件存量表",
        dataset_code="mid_knowledge_file_increment",
        es_index_name="mid_knowledge_file_increment",
        description="知识库文件存量数据表",
        is_commercial_only=True,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="total_file_count",
                    name="总文件数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="knowledge_base_type", value="文档知识库")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="file_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="file_id"
                        ),
                        AggregationExpression(
                            name="total_file_count",
                            type=PipelineTypeEnum.CUMULATIVE_SUM,
                            field="file_count"
                        )
                    ],
                    index=1,
                    sum_field="file_id"
                ),
                MetricConfig(
                    field="total_qa_count",
                    name="总QA对数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="knowledge_base_type", value="QA知识库")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="qa_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="file_id"
                        ),
                        AggregationExpression(
                            name="total_qa_count",
                            type=PipelineTypeEnum.CUMULATIVE_SUM,
                            field="qa_count"
                        )
                    ],
                    index=1,
                    sum_field="file_id"
                ),
                MetricConfig(
                    field="file_size",
                    name="文件大小",
                    is_virtual=False,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="knowledge_base_type", value="文档知识库")
                    ])
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="文件解析事件表",
        dataset_code="mid_doc_parse_dtl",
        es_index_name="mid_doc_parse_dtl",
        description="文件解析事件数据表",
        is_commercial_only=True,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="doc_parse_count",
                    name="文档上传次数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="doc_parse_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="doc_parse_success_count",
                    name="文档入库成功次数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="status", value="success")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="doc_parse_success_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="doc_parse_success_rate",
                    name="文档入库成功率",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="status", value="success"),
                        MatchAllOp(field="")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="doc_parse_success_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        ),
                        AggregationExpression(
                            name="doc_parse_total_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ],
                    formula=FormulaEnum.DIVIDE
                ),
                MetricConfig(
                    field="etl_parse_count",
                    name="ETL处理次数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="parse_type", value="etl4lm")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="etl_parse_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]

                ),
                MetricConfig(
                    field="etl_parse_success_count",
                    name="ETL处理成功次数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="parse_type", value="etl4lm"),
                        TermOp(field="status", value="success")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="etl_parse_success_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    name="ETL处理成功率",
                    field="etl_parse_success_rate",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        FilterExpression(bool_operator="must", filters=[
                            TermOp(field="parse_type", value="etl4lm"),
                            TermOp(field="status", value="success")
                        ]),
                        TermOp(field="parse_type", value="etl4lm"),
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="etl_parse_success_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        ),
                        AggregationExpression(
                            name="etl_parse_total_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ],
                    formula=FormulaEnum.DIVIDE
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name",
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id",
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                ),
                DimensionConfig(
                    name="解析类型",
                    field="parse_type"
                ),
                DimensionConfig(
                    name="文件最终状态",
                    field="status"
                ),
                DimensionConfig(
                    name="文件来源",
                    field="app_type"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="模型调用事件表",
        dataset_code="mid_model_call_dtl",
        es_index_name="mid_model_call_dtl",
        description="模型调用事件数据表",
        is_commercial_only=True,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="total_token",
                    name="Token消耗量",
                    is_virtual=False
                ),
                MetricConfig(
                    field="model_call_count",
                    name="模型调用次数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="model_call_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="model_call_success_rate",
                    name="模型调用成功率",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="status", value="success"),
                        MatchAllOp(field="")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="model_call_success_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="event_id"
                        ),
                        AggregationExpression(
                            name="model_call_total_count",
                            type=AggsTypeEnum.CARDINALITY,
                            field="event_id"
                        )
                    ],
                    formula=FormulaEnum.DIVIDE
                ),
                MetricConfig(
                    field="max_concurrent_llm_sessions",
                    name="最大LLM并发数",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="per_minute",
                            type=AggsTypeEnum.DATE_HISTOGRAM,
                            field="minute_ts",
                            custom_params={
                                "fixed_interval": "1m",
                                "min_doc_count": 1
                            },
                            aggs=[
                                AggregationExpression(
                                    name="online",
                                    type=AggsTypeEnum.CARDINALITY,
                                    field="event_id"
                                )
                            ]
                        ),
                        AggregationExpression(
                            name="max_concurrent_llm_sessions",
                            type=PipelineTypeEnum.MAX_BUCKET,
                            field="per_minute>online"
                        )
                    ],
                    index=1
                ),
                MetricConfig(
                    field="avg_first_token_cost_time",
                    name="平均首Token响应延迟",
                    is_virtual=True,
                    aggregations=[
                        AggregationExpression(
                            name="first_token_cost_time",
                            type=AggsTypeEnum.AVG,
                            field="first_token_cost_time"
                        )
                    ]
                )
            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day", "hour"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                ),
                DimensionConfig(
                    name="角色ID",
                    field="user_role_infos.role_id"
                ),
                DimensionConfig(
                    name="角色名称",
                    field="user_role_infos.role_name"
                ),
                DimensionConfig(
                    name="应用ID",
                    field="app_id"
                ),
                DimensionConfig(
                    name="应用名称",
                    field="app_name"
                ),
                DimensionConfig(
                    name="模型ID",
                    field="model_id"
                ),
                DimensionConfig(
                    name="模型类型",
                    field="model_type"
                ),
                DimensionConfig(
                    name="模型名称",
                    field="model_name"
                ),
                DimensionConfig(
                    name="服务方ID",
                    field="model_server_id"
                ),
                DimensionConfig(
                    name="服务方名称",
                    field="model_server_name"
                )
            ]
        ).model_dump()
    ),
    DashboardDataset(
        dataset_name="用户反馈指标表",
        dataset_code="mid_user_interact_dtl",
        es_index_name="mid_user_interact_dtl",
        description="用户反馈指标数据表",
        is_commercial_only=False,
        schema_config=SchemaConfig(
            metrics=[
                MetricConfig(
                    field="like_count",
                    name="点赞次数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="interact_type", value="like")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="like_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    name="点踩次数",
                    field="dislike_count",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="interact_type", value="dislike")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="dislike_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                ),
                MetricConfig(
                    field="copy_count",
                    name="复制次数",
                    is_virtual=True,
                    filter=FilterExpression(bool_operator="must", filters=[
                        TermOp(field="interact_type", value="copy")
                    ]),
                    aggregations=[
                        AggregationExpression(
                            name="copy_count",
                            type=AggsTypeEnum.VALUE_COUNT,
                            field="event_id"
                        )
                    ]
                )

            ],
            dimensions=[
                DimensionConfig(
                    name="时间",
                    field="timestamp",
                    time_granularitys=["year", "month", "week", "day"],
                    field_type="date"
                ),
                DimensionConfig(
                    name="用户ID",
                    field="user_id"
                ),
                DimensionConfig(
                    name="用户名称",
                    field="user_name"
                ),
                DimensionConfig(
                    name="用户组ID",
                    field="user_group_infos.user_group_id"
                ),
                DimensionConfig(
                    name="用户组名称",
                    field="user_group_infos.user_group_name"
                ),
                DimensionConfig(
                    name="部门ID",
                    field="user_department_infos.department_id"
                ),
                DimensionConfig(
                    name="部门名称",
                    field="user_department_infos.department_name"
                ),
                DimensionConfig(
                    name="应用ID",
                    field="app_id"
                ),
                DimensionConfig(
                    name="应用名称",
                    field="app_name"
                )
            ]
        ).model_dump()
    )
]

preset_oss_dashboard_sql = """
INSERT INTO dashboard (title, description, status, dashboard_type, layout_config, style_config, user_id, id) VALUES ('统计看板', '', 'published', 'preset_oss', '{"layouts": [{"h": 8, "i": "0c7ed6d5556249b18675400aeb83d6fb", "w": 12, "x": 12, "y": 13, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 3, "i": "136ef227d31749a3bc36ab2129d6fa48", "w": 5, "x": 15, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 3, "i": "1c6c4d30b7964c93810814feb966b0b8", "w": 5, "x": 5, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 8, "i": "6e383953d2104888aa3bfa4bd2c84a15", "w": 12, "x": 0, "y": 13, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 8, "i": "83690982e64d490798f4d350f3c429a4", "w": 12, "x": 0, "y": 5, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 2, "i": "94408421c2514745b7eeeb4ed007ff8d", "w": 24, "x": 0, "y": 0, "maxH": 24, "maxW": 24, "minH": 2, "minW": 7, "static": false}, {"h": 3, "i": "9f08afec754a44749ad410893055c472", "w": 4, "x": 20, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 8, "i": "ce4949a29c77479eb7d9a46654ebb972", "w": 12, "x": 12, "y": 5, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 3, "i": "dfe10a4967c5428d8d5eb23130689c73", "w": 5, "x": 10, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 3, "i": "2dc1af", "w": 5, "x": 0, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}]}', '{"theme": "light"}', 1, 10);

INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '总QA知识库数', 'metric', 'mid_knowledge_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_qa_knowledge_base_count", "fieldName": "总QA知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总QA知识库数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_qa_knowledge_base_count", "fieldType": "metric", "displayName": "总QA知识库数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总QA知识库数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "left", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": true, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 16, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '136ef227d31749a3bc36ab2129d6fa48');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '总应用数', 'metric', 'mid_app_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_app_count", "fieldName": "总应用数", "isVirtual": true, "aggregation": "sum", "displayName": "总应用数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_app_count", "fieldType": "metric", "displayName": "总应用数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总应用数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "1111", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "left", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": true, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 16, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '1c6c4d30b7964c93810814feb966b0b8');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '总文档知识库数', 'metric', 'mid_knowledge_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_document_knowledge_base_count", "fieldName": "总文档知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总文档知识库数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_document_knowledge_base_count", "fieldType": "metric", "displayName": "总文档知识库数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总文档知识库数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "left", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": true, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 16, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', 'dfe10a4967c5428d8d5eb23130689c73');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '总用户数', 'metric', 'mid_user_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_user_count", "isDivide": null, "fieldName": "总用户数", "isVirtual": true, "aggregation": "sum", "displayName": "总用户数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_user_count", "fieldType": "metric", "displayName": "总用户数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总用户数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "1111", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "left", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": true, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 16, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '2dc1af');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '总知识库数', 'stacked-bar', 'mid_knowledge_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_qa_knowledge_base_count", "fieldName": "总QA知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总QA知识库数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": false}}, {"sort": null, "fieldId": "total_document_knowledge_base_count", "fieldName": "总文档知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总文档知识库数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": false}}], "dimensions": [{"sort": null, "fieldId": "timestamp", "fieldName": "时间(月)", "displayName": "时间(月)", "timeGranularity": "month"}], "fieldOrder": [{"fieldId": "timestamp", "fieldType": "dimension", "displayName": "时间(月)"}, {"fieldId": "total_qa_knowledge_base_count", "fieldType": "metric", "displayName": "总QA知识库数"}, {"fieldId": "total_document_knowledge_base_count", "fieldType": "metric", "displayName": "总文档知识库数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总知识库数", "bgColor": "", "showAxis": true, "showGrid": false, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#666666", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#666666", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "#000000", "titleFontSize": 16, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '6e383953d2104888aa3bfa4bd2c84a15');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '新增应用数', 'area', 'mid_app_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "new_app_count", "fieldName": "新增应用数", "isVirtual": true, "aggregation": "sum", "displayName": "新增应用数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "timestamp", "fieldName": "时间(月)", "displayName": "时间(月)", "timeGranularity": "month"}], "fieldOrder": [{"fieldId": "timestamp", "fieldType": "dimension", "displayName": "时间(月)"}, {"fieldId": "new_app_count", "fieldType": "metric", "displayName": "新增应用数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "新增应用数", "bgColor": "", "showAxis": true, "showGrid": false, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": false, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#666666", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#666666", "yAxisTitle": "", "legendAlign": "left", "legendColor": "#999999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "#000000", "titleFontSize": 16, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', 'ce4949a29c77479eb7d9a46654ebb972');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '新增用户数', 'area', 'mid_user_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "new_user_count", "fieldName": "新增用户数", "isVirtual": true, "aggregation": "sum", "displayName": "新增用户数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": false}}], "dimensions": [{"sort": null, "fieldId": "timestamp", "fieldName": "时间(月)", "displayName": "时间(月)", "timeGranularity": "month"}], "fieldOrder": [{"fieldId": "timestamp", "fieldType": "dimension", "displayName": "时间(月)"}, {"fieldId": "new_user_count", "fieldType": "metric", "displayName": "新增用户数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "新增用户数", "bgColor": "", "showAxis": true, "showGrid": false, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": false, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#666666", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#666666", "yAxisTitle": "", "legendAlign": "left", "legendColor": "#999999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "#000000", "titleFontSize": 16, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '83690982e64d490798f4d350f3c429a4');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '点赞次数', 'grouped-bar', 'mid_user_interact_dtl', '{"filters": [], "metrics": [{"sort": null, "fieldId": "like_count", "fieldName": "点赞次数", "isVirtual": true, "aggregation": "sum", "displayName": "点赞次数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}, {"sort": null, "fieldId": "dislike_count", "fieldName": "点踩次数", "isVirtual": true, "aggregation": "sum", "displayName": "点踩次数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "app_name", "fieldName": "应用名称", "displayName": "应用名称", "timeGranularity": null}], "fieldOrder": [{"fieldId": "like_count", "fieldType": "metric", "displayName": "点赞次数"}, {"fieldId": "app_name", "fieldType": "dimension", "displayName": "应用名称"}, {"fieldId": "dislike_count", "fieldType": "metric", "displayName": "点踩次数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "点赞次数", "bgColor": "", "showAxis": true, "showGrid": false, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#666666", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#666666", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "#000000", "titleFontSize": 16, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '0c7ed6d5556249b18675400aeb83d6fb');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '点赞次数', 'metric', 'mid_user_interact_dtl', '{"filters": [], "metrics": [{"sort": null, "fieldId": "like_count", "isDivide": null, "fieldName": "点赞次数", "isVirtual": true, "aggregation": "sum", "displayName": "点赞次数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "like_count", "fieldType": "metric", "displayName": "点赞次数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "点赞次数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "1111", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "left", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": true, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 16, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '9f08afec754a44749ad410893055c472');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (10, '选择日期', 'query', '', '{"queryConditions": {"id": "32d5", "displayType": "range", "defaultValue": {"mode": "dynamic", "type": "recent_days", "endDate": 1769529599, "startDate": 1753891200, "recentDays": 180, "shortcutKey": 180}, "hasDefaultValue": true, "timeGranularity": "year_month_day"}, "linkedComponentIds": ["83690982e64d490798f4d350f3c429a4", "0c7ed6d5556249b18675400aeb83d6fb", "136ef227d31749a3bc36ab2129d6fa48", "6e383953d2104888aa3bfa4bd2c84a15", "dfe10a4967c5428d8d5eb23130689c73", "ce4949a29c77479eb7d9a46654ebb972", "9f08afec754a44749ad410893055c472", "1c6c4d30b7964c93810814feb966b0b8", "f6c896a87d554f21a30d0f1cd5b569d7"]}', '{"titleColor": ""}', '94408421c2514745b7eeeb4ed007ff8d');
"""

preset_commercial_dashboard_sql = """
INSERT INTO dashboard (title, description, status, dashboard_type, layout_config, style_config, user_id, id) VALUES ('统计看板', '', 'published', 'preset_commercial', '{"layouts": [{"h": 6, "i": "3d0f5873a8bb44e2965827ec6ae31c04", "w": 8, "x": 16, "y": 17, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 12, "i": "48b66fdec7df4348b8d30e2c67517ed1", "w": 8, "x": 8, "y": 5, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 6, "i": "3ef497c6820545a989d249d29d6bb5d1", "w": 8, "x": 0, "y": 5, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 3, "i": "59d11da581344a69b5e338a9d3b19145", "w": 4, "x": 4, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 6, "i": "050b2c56f1354554bf6fc968fcf12f8f", "w": 8, "x": 8, "y": 17, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 3, "i": "bb3adabcdeaa4d51a6555f0124d588af", "w": 4, "x": 12, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 3, "i": "4d76ff4edccf4fdf85034da6ffb3d7d6", "w": 4, "x": 20, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 6, "i": "2fb5ca536b3b44cb9fa9138ac7e78113", "w": 8, "x": 0, "y": 17, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 3, "i": "db44c5932fb94dca8dc6700e188d2eca", "w": 4, "x": 16, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 3, "i": "dd90c0b6ea174a9ea93b54e196e7769d", "w": 4, "x": 8, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 2, "i": "40a34e3d781e465786e9e884ebc171a6", "w": 24, "x": 0, "y": 0, "maxH": 24, "maxW": 24, "minH": 2, "minW": 7, "static": false}, {"h": 3, "i": "ce8ca127b71a4a0884dc93075db28752", "w": 4, "x": 0, "y": 2, "maxH": 24, "maxW": 24, "minH": 2, "minW": 3, "static": false}, {"h": 6, "i": "40fa4cfe8cce4320b5b9052e02df7768", "w": 8, "x": 16, "y": 5, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 6, "i": "a93edd366639478fabe8a86cefde6632", "w": 8, "x": 16, "y": 11, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}, {"h": 6, "i": "80abca18be5b47fdbd9931858b0994de", "w": 8, "x": 0, "y": 11, "maxH": 24, "maxW": 24, "minH": 5, "minW": 3, "static": false}]}', '{"theme": "light"}', 1, 11);

INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, 'Token消耗量', 'bar', 'mid_model_call_dtl', '{"filters": [{"id": "a9ca48", "value": "默认用户组1", "fieldId": "user_name", "operator": "not_equals", "fieldName": "用户名称", "fieldType": "string", "filterType": "conditional"}, {"id": "87e821", "value": "10000", "fieldId": "total_token", "operator": "greater_than", "fieldName": "Token消耗量", "fieldType": "number", "filterType": "conditional"}], "metrics": [{"sort": "desc", "fieldId": "total_token", "fieldName": "Token消耗量", "isVirtual": false, "aggregation": "sum", "displayName": "Token消耗量", "numberFormat": {"type": "number", "unit": "Thousand", "decimalPlaces": 0, "thousandSeparator": false}}], "dimensions": [{"sort": null, "fieldId": "user_group_infos.user_group_name", "fieldName": "用户组名称", "displayName": "用户组名称", "timeGranularity": null}, {"sort": null, "fieldId": "app_name", "fieldName": "应用名称", "displayName": "应用名称", "timeGranularity": null}], "fieldOrder": [{"fieldId": "total_token", "fieldType": "metric", "displayName": "Token消耗量"}, {"fieldId": "user_group_infos.user_group_name", "fieldType": "dimension", "displayName": "用户组名称"}, {"fieldId": "app_name", "fieldType": "dimension", "displayName": "应用名称"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "Token消耗量", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": false, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '2fb5ca536b3b44cb9fa9138ac7e78113');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, 'Token消耗量', 'metric', 'mid_model_call_dtl', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_token", "fieldName": "Token消耗量", "isVirtual": false, "aggregation": "sum", "displayName": "Token消耗量", "numberFormat": {"type": "number", "unit": "Thousand", "decimalPlaces": 1, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_token", "fieldType": "metric", "displayName": "Token消耗量"}], "timeFilter": {"mode": "fixed", "type": "custom", "endDate": 1769875199, "startDate": 1767196800}, "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "Token消耗量", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "26年1月", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "end", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 14, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '4d76ff4edccf4fdf85034da6ffb3d7d6');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '不同应用用户反馈情况', 'grouped-bar', 'mid_user_interact_dtl', '{"filters": [], "metrics": [{"sort": null, "fieldId": "like_count", "fieldName": "点赞次数", "isVirtual": true, "aggregation": "sum", "displayName": "点赞次数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}, {"sort": null, "fieldId": "dislike_count", "fieldCode": "点踩次数", "fieldName": "点踩次数", "isVirtual": false, "aggregation": "sum", "displayName": "点踩次数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "app_name", "fieldName": "应用名称", "displayName": "应用名称", "timeGranularity": null}], "fieldOrder": [{"fieldId": "like_count", "fieldType": "metric", "displayName": "点赞次数"}, {"fieldId": "dislike_count", "fieldType": "metric", "displayName": "点踩次数"}, {"fieldId": "app_name", "fieldType": "dimension", "displayName": "应用名称"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "不同应用用户反馈情况", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": true, "themeColor": "cool-palette", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '050b2c56f1354554bf6fc968fcf12f8f');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '会话次数', 'metric', 'mid_sessions_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "session_count", "fieldName": "会话次数", "isVirtual": true, "aggregation": "sum", "displayName": "会话次数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "session_count", "fieldType": "metric", "displayName": "会话次数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "会话次数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "全公司截至目前", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "end", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 14, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', 'dd90c0b6ea174a9ea93b54e196e7769d');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '会话次数TOP10的应用', 'grouped-horizontal-bar', 'mid_sessions_increment', '{"filters": [{"id": "2858ea", "value": "daily_chat", "fieldId": "app_name", "operator": "not_equals", "fieldName": "应用名称", "fieldType": "string", "filterType": "conditional"}], "metrics": [{"sort": "desc", "fieldId": "session_count", "fieldName": "会话次数", "isVirtual": true, "aggregation": "sum", "displayName": "会话次数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}, {"sort": null, "fieldId": "platform_user_count", "fieldCode": "使用人数", "fieldName": "使用人数", "isVirtual": false, "aggregation": "sum", "displayName": "使用人数", "numberFormat": {"type": "number", "decimalPlaces": 2, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "app_name", "fieldName": "应用名称", "displayName": "应用名称", "timeGranularity": null}], "fieldOrder": [{"fieldId": "session_count", "fieldType": "metric", "displayName": "会话次数"}, {"fieldId": "app_name", "fieldType": "dimension", "displayName": "应用名称"}, {"fieldId": "platform_user_count", "fieldType": "metric", "displayName": "使用人数"}], "resultLimit": {"limit": 10, "limitType": "limited"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "会话次数TOP10的应用", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": true, "themeColor": "cool-palette", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '48b66fdec7df4348b8d30e2c67517ed1');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '总QA对数量', 'donut', 'mid_knowledge_increment', '{"filters": [{"id": "9ae3e0", "value": "默认用户组1", "fieldId": "user_group_infos.user_group_name", "operator": "not_equals", "fieldName": "用户组名称", "fieldType": "string", "filterType": "conditional"}], "metrics": [{"sort": null, "fieldId": "total_qa_knowledge_base_count", "fieldName": "总QA知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总QA知识库数", "numberFormat": {"type": "number", "decimalPlaces": 2, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "user_group_infos.user_group_name", "fieldName": "用户组名称", "displayName": "用户组名称", "timeGranularity": null}], "fieldOrder": [{"fieldId": "user_group_infos.user_group_name", "fieldType": "dimension", "displayName": "用户组名称"}, {"fieldId": "total_qa_knowledge_base_count", "fieldType": "metric", "displayName": "总QA知识库数"}], "resultLimit": {"limit": 3, "limitType": "limited"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总QA对数量", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": true, "themeColor": "cool-palette", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '3d0f5873a8bb44e2965827ec6ae31c04');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '总应用数', 'metric', 'mid_app_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_app_count", "fieldName": "总应用数", "isVirtual": true, "aggregation": "sum", "displayName": "总应用数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_app_count", "fieldType": "metric", "displayName": "总应用数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总应用数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "全公司截至目前", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "end", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 14, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '59d11da581344a69b5e338a9d3b19145');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '总文档知识库数', 'multiple-line', 'mid_knowledge_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_document_knowledge_base_count", "fieldName": "总文档知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总文档知识库数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}, {"sort": null, "fieldId": "total_qa_knowledge_base_count", "fieldCode": "总QA知识库数", "fieldName": "总QA知识库数", "isVirtual": false, "aggregation": "sum", "displayName": "总QA知识库数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "timestamp", "fieldName": "时间(月)", "displayName": "时间(月)", "timeGranularity": "month"}], "fieldOrder": [{"fieldId": "timestamp", "fieldType": "dimension", "displayName": "时间(月)"}, {"fieldId": "total_document_knowledge_base_count", "fieldType": "metric", "displayName": "总文档知识库数"}, {"fieldId": "total_qa_knowledge_base_count", "fieldType": "metric", "displayName": "总QA知识库数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总文档知识库数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": true, "themeColor": "cool-palette", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '40fa4cfe8cce4320b5b9052e02df7768');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '总文档知识库数', 'pie', 'mid_knowledge_increment', '{"filters": [{"id": "9ae3e0", "value": "默认用户组1", "fieldId": "user_group_infos.user_group_name", "operator": "not_equals", "fieldName": "用户组名称", "fieldType": "string", "filterType": "conditional"}], "metrics": [{"sort": null, "fieldId": "total_document_knowledge_base_count", "fieldName": "总文档知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总文档知识库数", "numberFormat": {"type": "number", "decimalPlaces": 2, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "user_group_infos.user_group_name", "fieldName": "用户组名称", "displayName": "用户组名称", "timeGranularity": null}], "fieldOrder": [{"fieldId": "total_document_knowledge_base_count", "fieldType": "metric", "displayName": "总文档知识库数"}, {"fieldId": "user_group_infos.user_group_name", "fieldType": "dimension", "displayName": "用户组名称"}], "resultLimit": {"limit": 3, "limitType": "limited"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总文档知识库数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": true, "themeColor": "cool-palette", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "right", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "top", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', 'a93edd366639478fabe8a86cefde6632');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '总文档知识库数', 'metric', 'mid_knowledge_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_document_knowledge_base_count", "fieldName": "总文档知识库数", "isVirtual": true, "aggregation": "sum", "displayName": "总文档知识库数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_document_knowledge_base_count", "fieldType": "metric", "displayName": "总文档知识库数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总文档知识库数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "全公司截至目前", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "end", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 14, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', 'bb3adabcdeaa4d51a6555f0124d588af');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '总用户数', 'metric', 'mid_user_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "total_user_count", "fieldName": "总用户数", "isVirtual": true, "aggregation": "sum", "displayName": "总用户数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [], "fieldOrder": [{"fieldId": "total_user_count", "fieldType": "metric", "displayName": "总用户数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "总用户数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "全公司截至目前", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "end", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 14, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', 'ce8ca127b71a4a0884dc93075db28752');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '新增用户数', 'area', 'mid_user_increment', '{"filters": [], "metrics": [{"sort": null, "fieldId": "new_user_count", "isDivide": null, "fieldName": "新增用户数", "isVirtual": true, "aggregation": "sum", "displayName": "新增用户数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [{"sort": null, "fieldId": "timestamp", "fieldName": "时间(月)", "displayName": "时间(月)", "timeGranularity": "month"}], "fieldOrder": [{"fieldId": "timestamp", "fieldType": "dimension", "displayName": "时间(月)"}, {"fieldId": "new_user_count", "fieldType": "metric", "displayName": "新增用户数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "新增用户数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": false, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "left", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "bottom", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '3ef497c6820545a989d249d29d6bb5d1');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '最大LLM并发数', 'area', 'mid_model_call_dtl', '{"filters": [], "metrics": [{"sort": null, "fieldId": "max_concurrent_llm_sessions", "fieldName": "最大LLM并发数", "isVirtual": true, "aggregation": "sum", "displayName": "最大LLM并发数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": true}}], "dimensions": [{"sort": "asc", "fieldId": "timestamp", "fieldName": "时间(周)", "displayName": "时间(周)", "timeGranularity": "week"}], "fieldOrder": [{"fieldId": "timestamp", "fieldType": "dimension", "displayName": "时间(周)"}, {"fieldId": "max_concurrent_llm_sessions", "fieldType": "metric", "displayName": "最大LLM并发数"}], "timeFilter": {"mode": "dynamic", "type": "recent_days", "endDate": 1769443199, "startDate": 1753804800, "recentDays": "180"}, "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "最大LLM并发数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "", "titleBold": false, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": false, "showLegend": false, "themeColor": "cool-palette", "titleAlign": "left", "titleColor": "", "xAxisAlign": "center", "xAxisColor": "#000000", "xAxisTitle": "", "yAxisAlign": "center", "yAxisColor": "#000000", "yAxisTitle": "", "legendAlign": "left", "legendColor": "#999", "metricAlign": "center", "metricColor": "#000000", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": false, "subtitleBold": false, "showDataLabel": false, "subtitleAlign": "center", "subtitleColor": "", "titleFontSize": 14, "xAxisFontSize": 14, "yAxisFontSize": 14, "legendFontSize": 12, "legendPosition": "bottom", "metricFontSize": 14, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', '80abca18be5b47fdbd9931858b0994de');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '最大同时在线会话数', 'metric', 'mid_session_run_dtl', '{"filters": [], "metrics": [{"sort": null, "fieldId": "max_concurrent_sessions", "fieldName": "最大同时在线会话数", "isVirtual": true, "aggregation": "sum", "displayName": "最大同时在线会话数", "numberFormat": {"type": "number", "decimalPlaces": 0, "thousandSeparator": false}}], "dimensions": [], "fieldOrder": [{"fieldId": "max_concurrent_sessions", "fieldType": "metric", "displayName": "最大同时在线会话数"}], "resultLimit": {"limitType": "all"}, "filtersLogic": "and", "isConfigured": true}', '{"title": "最大同时在线会话数", "bgColor": "", "showAxis": true, "showGrid": true, "subtitle": "全公司截至目前", "titleBold": true, "xAxisBold": false, "yAxisBold": false, "legendBold": false, "metricBold": true, "showLegend": true, "themeColor": "professional-blue", "titleAlign": "left", "titleColor": "", "xAxisAlign": "", "xAxisColor": "", "xAxisTitle": "", "yAxisAlign": "", "yAxisColor": "", "yAxisTitle": "", "legendAlign": "", "legendColor": "", "metricAlign": "end", "metricColor": "#4882f6", "titleItalic": false, "xAxisItalic": false, "yAxisItalic": false, "legendItalic": false, "metricItalic": false, "showSubtitle": true, "subtitleBold": false, "showDataLabel": true, "subtitleAlign": "left", "subtitleColor": "#666", "titleFontSize": 14, "xAxisFontSize": 0, "yAxisFontSize": 0, "legendFontSize": 0, "legendPosition": "", "metricFontSize": 28, "subtitleItalic": false, "titleUnderline": false, "xAxisUnderline": false, "yAxisUnderline": false, "legendUnderline": false, "metricUnderline": false, "subtitleFontSize": 14, "subtitleUnderline": false, "titleStrikethrough": false, "xAxisStrikethrough": false, "yAxisStrikethrough": false, "legendStrikethrough": false, "metricStrikethrough": false, "subtitleStrikethrough": false}', 'db44c5932fb94dca8dc6700e188d2eca');
INSERT INTO dashboard_component (dashboard_id, title, type, dataset_code, data_config, style_config, id) VALUES (11, '选择日期', 'query', '', '{"queryConditions": {"id": "c833", "displayType": "range", "defaultValue": {"mode": "dynamic", "type": "recent_days", "endDate": 1769529599, "startDate": 1753891200, "recentDays": 180, "shortcutKey": 180}, "hasDefaultValue": true, "timeGranularity": "year_month_day"}, "linkedComponentIds": ["db44c5932fb94dca8dc6700e188d2eca", "ce8ca127b71a4a0884dc93075db28752", "40fa4cfe8cce4320b5b9052e02df7768", "a93edd366639478fabe8a86cefde6632", "dd90c0b6ea174a9ea93b54e196e7769d", "3d0f5873a8bb44e2965827ec6ae31c04", "80abca18be5b47fdbd9931858b0994de", "050b2c56f1354554bf6fc968fcf12f8f", "48b66fdec7df4348b8d30e2c67517ed1", "3ef497c6820545a989d249d29d6bb5d1", "2fb5ca536b3b44cb9fa9138ac7e78113", "4d76ff4edccf4fdf85034da6ffb3d7d6", "bb3adabcdeaa4d51a6555f0124d588af", "59d11da581344a69b5e338a9d3b19145"]}', '{"titleColor": ""}', '40a34e3d781e465786e9e884ebc171a6');
"""


DEPARTMENT_DIMENSIONS = [
    DimensionConfig(name="部门ID", field="user_department_infos.department_id"),
    DimensionConfig(name="部门名称", field="user_department_infos.department_name"),
]


async def _upgrade_datasets_add_department_dimensions(
    dashboard_dataset_repository: DashboardDatasetRepositoryImpl,
):
    """Upgrade existing datasets: append department dimensions if missing.

    This is idempotent — if department dimensions already exist, nothing happens.
    Runs on every startup for upgrade scenarios where datasets were created
    before department support was added (v2.4 → v2.5).
    """
    existing_datasets = await dashboard_dataset_repository.find_all()
    for dataset in existing_datasets:
        schema = dataset.schema_config
        if not isinstance(schema, dict):
            continue
        dimensions = schema.get("dimensions", [])
        # Check if department dimensions already present
        has_dept = any(
            d.get("field", "").startswith("user_department_infos.") for d in dimensions
        )
        if has_dept:
            continue
        # Find insertion point: right after user_group_infos dimensions
        insert_idx = len(dimensions)
        for i, d in enumerate(dimensions):
            if d.get("field", "").startswith("user_group_infos."):
                insert_idx = i + 1  # keep updating to land after the last one
        # Insert department dimensions
        for j, dept_dim in enumerate(DEPARTMENT_DIMENSIONS):
            dimensions.insert(insert_idx + j, dept_dim.model_dump())
        schema["dimensions"] = dimensions
        dataset.schema_config = schema
        await dashboard_dataset_repository.update(dataset)


async def init_dashboard_datasets():
    db_manager = await get_database_connection()
    await db_manager.create_db_and_tables()
    async with get_async_db_session() as session:
        dashboard_dataset_repository = DashboardDatasetRepositoryImpl(session)
        if await dashboard_dataset_repository.count() == 0:
            await dashboard_dataset_repository.bulk_save(DASHBOARD_DATASET)
        else:
            # Upgrade path: add department dimensions to existing datasets
            await _upgrade_datasets_add_department_dimensions(dashboard_dataset_repository)
    preset_dashboard = await DashboardDao.get_dashboards(dashboard_type=[DashboardType.PRESET_OSS])
    if not preset_dashboard:
        await DashboardDao.exec_sql_str(preset_oss_dashboard_sql)
        await DashboardDao.exec_sql_str(preset_commercial_dashboard_sql)
        await GroupResourceDao.ainsert_group_batch([
            GroupResource(
                group_id=DefaultGroup,
                third_id=str(10),
                type=ResourceTypeEnum.DASHBOARD.value),
            GroupResource(
                group_id=DefaultGroup,
                third_id=str(11),
                type=ResourceTypeEnum.DASHBOARD.value),
        ])


if __name__ == '__main__':
    import asyncio

    asyncio.run(init_dashboard_datasets())
