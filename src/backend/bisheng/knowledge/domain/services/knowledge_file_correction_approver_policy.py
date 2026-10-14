"""文档纠错的审批人来源.

场景管理里只能改这一个或签节点的审批人. 上传人始终保留.
知识库所有者和库管理员按处理当时的库成员判断, 不在提交时写成任务快照.
不走通用审批门, 因此不会自动通过, 平台管理员也不能代批.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.approval.domain.models.approval_instance import (
    ApprovalInstance,
    ApprovalInstanceStatus,
    ApprovalTask,
    ApprovalTaskStatus,
)
from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.common.errcode.approval import (
    ApprovalFixedScenarioStructureLockedError,
    ApprovalScenarioDisabledError,
)
from bisheng.common.errcode.file_correction import FileCorrectionApproverConfigInvalidError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_file_correction import (
    CORRECTION_PENDING,
    FILE_CORRECTION_SCENARIO,
    FILE_CORRECTION_SCENARIO_NAME,
    KnowledgeFileCorrection,
)

FILE_UPLOADER_SOURCE = "file_uploader"
KNOWLEDGE_SPACE_OWNER_SOURCE = "knowledge_space_owner"
KNOWLEDGE_SPACE_MANAGER_SOURCE = "knowledge_space_manager"
ALLOWED_APPROVER_SOURCES = (
    FILE_UPLOADER_SOURCE,
    KNOWLEDGE_SPACE_OWNER_SOURCE,
    KNOWLEDGE_SPACE_MANAGER_SOURCE,
)
CORRECTION_FLOW_CODE = "knowledge_file_correction_flow"
CORRECTION_FLOW_NAME = "文档纠错"
CORRECTION_NODE_CODE = "file_uploader"
CORRECTION_NODE_NAME = "上传人审批"
CORRECTION_ROUTE_NAME = "文档纠错"


def default_approver_config() -> dict:
    """默认审批人来源, 只有上传人.

    Returns:
        节点上的 approver_config.
    """
    return {"sources": [{"type": FILE_UPLOADER_SOURCE}]}


def normalize_correction_nodes(nodes_payload: list[dict]) -> list[dict]:
    """校验文档纠错只能保存一个或签节点, 且上传人来源还在.

    Args:
        nodes_payload: 管理端提交的节点列表.

    Returns:
        可写入 approval_node_definition 的单个节点.

    Raises:
        ApprovalFixedScenarioStructureLockedError: 节点数量, 节点编码或会签被改掉.
        FileCorrectionApproverConfigInvalidError: 拿掉了上传人, 或加了不允许的来源.
    """
    if len(nodes_payload) != 1:
        raise ApprovalFixedScenarioStructureLockedError()
    node = nodes_payload[0]
    if not isinstance(node, dict):
        raise ApprovalFixedScenarioStructureLockedError()
    node_code = node.get("node_code")
    if node_code not in (None, "", CORRECTION_NODE_CODE):
        raise ApprovalFixedScenarioStructureLockedError()
    if str(node.get("node_mode") or "or") != "or":
        raise ApprovalFixedScenarioStructureLockedError()
    source_types = _source_types(node.get("approver_config") or {})
    node_name = str(node.get("node_name") or CORRECTION_NODE_NAME).strip() or CORRECTION_NODE_NAME
    return [
        {
            "node_code": CORRECTION_NODE_CODE,
            "node_name": node_name,
            "node_order": int(node.get("node_order") or 0),
            "node_mode": "or",
            "approver_config": {"sources": [{"type": item} for item in source_types]},
            "extra_config": {},
        }
    ]


async def ensure_default_scenario(tenant_id: int) -> None:
    """补齐当前租户的文档纠错场景. 已有节点上的审批人来源不动.

    Args:
        tenant_id: 当前租户. 新建行写入该租户.
    """
    async with get_async_db_session() as session:
        try:
            scenario = await _scenario(session)
            if scenario is None:
                scenario = ApprovalScenario(
                    tenant_id=int(tenant_id),
                    scenario_code=FILE_CORRECTION_SCENARIO,
                    scenario_name=FILE_CORRECTION_SCENARIO_NAME,
                    display_name=FILE_CORRECTION_SCENARIO_NAME,
                    enabled=True,
                )
                session.add(scenario)
                await session.flush()
            flow = await _flow(session, int(scenario.id))
            if flow is None:
                flow = ApprovalFlowDefinition(
                    tenant_id=int(tenant_id),
                    scenario_id=int(scenario.id),
                    flow_code=CORRECTION_FLOW_CODE,
                    flow_name=CORRECTION_FLOW_NAME,
                    is_active=True,
                )
                session.add(flow)
                await session.flush()
            version = await _active_version(session, int(flow.id))
            if version is None:
                version = ApprovalFlowVersion(
                    tenant_id=int(tenant_id),
                    flow_definition_id=int(flow.id),
                    version_no=1,
                    is_active=True,
                    definition_snapshot={"contract": FILE_CORRECTION_SCENARIO, "version": 1},
                )
                session.add(version)
                await session.flush()
            nodes = await _nodes(session, int(version.id))
            if not nodes:
                session.add(
                    ApprovalNodeDefinition(
                        tenant_id=int(tenant_id),
                        flow_version_id=int(version.id),
                        node_code=CORRECTION_NODE_CODE,
                        node_name=CORRECTION_NODE_NAME,
                        node_order=0,
                        node_mode="or",
                        approver_config=default_approver_config(),
                        extra_config={},
                    )
                )
            route = (
                await session.exec(
                    select(ApprovalRouteRule).where(
                        ApprovalRouteRule.scenario_id == int(scenario.id),
                        ApprovalRouteRule.route_name == CORRECTION_ROUTE_NAME,
                    )
                )
            ).first()
            if route is None:
                session.add(
                    ApprovalRouteRule(
                        tenant_id=int(tenant_id),
                        scenario_id=int(scenario.id),
                        route_name=CORRECTION_ROUTE_NAME,
                        route_type="approval",
                        sort_order=0,
                        flow_definition_id=int(flow.id),
                        match_config={},
                        enabled=True,
                    )
                )
            await session.commit()
        except IntegrityError:
            await session.rollback()


async def assert_submit_allowed(session) -> None:
    """场景被停用时拒绝新的纠错. 还没有场景行时按默认上传人继续.

    Args:
        session: 提交纠错使用的数据库会话.

    Raises:
        ApprovalScenarioDisabledError: 文档纠错场景已停用.
    """
    scenario = await _scenario(session)
    if scenario is not None and not bool(scenario.enabled):
        raise ApprovalScenarioDisabledError()


async def operator_can_handle(session, correction, operator_user_id: int) -> bool:
    """当前用户能不能处理这条未关闭的纠错.

    反馈人即使同时是库管理员也不能处理自己提交的纠错.
    上传人始终可以. 知识库所有者和库管理员只在来源已勾选, 且现在仍是该库成员时可以.

    Args:
        session: 当前事务的数据库会话.
        correction: 纠错单, 需含反馈人, 上传人, 知识库和租户.
        operator_user_id: 操作人用户 ID.

    Returns:
        可以处理时为 True.
    """
    operator_id = int(operator_user_id)
    if operator_id == int(correction.applicant_user_id):
        return False
    if operator_id == int(correction.uploader_user_id):
        return True
    sources = set(await load_source_types(session))
    owners, managers = await _space_roles(int(correction.knowledge_id))
    if KNOWLEDGE_SPACE_OWNER_SOURCE in sources and operator_id in owners:
        return True
    if KNOWLEDGE_SPACE_MANAGER_SOURCE in sources and operator_id in managers:
        return True
    return False


async def load_source_types(session) -> tuple[str, ...]:
    """读取当前生效节点上的审批人来源. 上传人始终算在里面.

    Args:
        session: 数据库会话.

    Returns:
        来源类型. 没有场景或节点损坏时只有上传人.
    """
    scenario = await _scenario(session)
    if scenario is None:
        return (FILE_UPLOADER_SOURCE,)
    flow = await _flow(session, int(scenario.id))
    if flow is None or not bool(flow.is_active):
        return (FILE_UPLOADER_SOURCE,)
    version = await _active_version(session, int(flow.id))
    if version is None:
        return (FILE_UPLOADER_SOURCE,)
    nodes = await _nodes(session, int(version.id))
    if len(nodes) != 1:
        return (FILE_UPLOADER_SOURCE,)
    try:
        return _source_types(nodes[0].approver_config or {})
    except FileCorrectionApproverConfigInvalidError:
        return (FILE_UPLOADER_SOURCE,)


async def list_live_role_tasks(tenant_id: int, operator_user_id: int) -> list[ApprovalTask]:
    """找出当前库角色能看到, 但任务行上的审批人不是他的纠错待办.

    上传人的待办已经在按审批人查询的结果里. 这里只补知识库所有者和库管理员.
    反馈人本人不补. 待处理纠错很多时, 每个知识库会查一次现任成员.

    Args:
        tenant_id: 当前租户.
        operator_user_id: 打开待办的用户 ID.

    Returns:
        需要并进待办列表的任务. 没有勾选库角色时为空.
    """
    async with get_async_db_session() as session:
        sources = set(await load_source_types(session))
        want_owner = KNOWLEDGE_SPACE_OWNER_SOURCE in sources
        want_manager = KNOWLEDGE_SPACE_MANAGER_SOURCE in sources
        if not want_owner and not want_manager:
            return []
        rows = (
            await session.exec(
                select(ApprovalTask, KnowledgeFileCorrection)
                .join(ApprovalInstance, ApprovalInstance.id == ApprovalTask.instance_id)
                .join(
                    KnowledgeFileCorrection,
                    KnowledgeFileCorrection.approval_instance_id == ApprovalInstance.id,
                )
                .where(
                    ApprovalInstance.tenant_id == int(tenant_id),
                    ApprovalInstance.scenario_code == FILE_CORRECTION_SCENARIO,
                    ApprovalInstance.status == ApprovalInstanceStatus.PENDING,
                    ApprovalTask.tenant_id == int(tenant_id),
                    ApprovalTask.status == ApprovalTaskStatus.PENDING,
                    KnowledgeFileCorrection.status == CORRECTION_PENDING,
                )
            )
        ).all()
        operator_id = int(operator_user_id)
        roles_by_space: dict[int, tuple[set[int], set[int]]] = {}
        visible: list[ApprovalTask] = []
        for task, correction in rows:
            if int(correction.applicant_user_id) == operator_id:
                continue
            if int(task.approver_user_id) == operator_id:
                continue
            space_id = int(correction.knowledge_id)
            if space_id not in roles_by_space:
                owners, managers = await _space_roles(space_id)
                roles_by_space[space_id] = (set(owners), set(managers))
            owners, managers = roles_by_space[space_id]
            matched = (want_owner and operator_id in owners) or (want_manager and operator_id in managers)
            if matched:
                visible.append(task)
        return visible


def _source_types(approver_config: dict) -> tuple[str, ...]:
    sources = approver_config.get("sources") if isinstance(approver_config, dict) else None
    if not isinstance(sources, list) or not sources:
        raise FileCorrectionApproverConfigInvalidError()
    found: list[str] = []
    for source in sources:
        if not isinstance(source, dict):
            raise FileCorrectionApproverConfigInvalidError()
        source_type = str(source.get("type") or "")
        if source_type not in ALLOWED_APPROVER_SOURCES:
            raise FileCorrectionApproverConfigInvalidError()
        if set(source) - {"type"}:
            raise FileCorrectionApproverConfigInvalidError()
        if source_type in found:
            raise FileCorrectionApproverConfigInvalidError()
        found.append(source_type)
    if FILE_UPLOADER_SOURCE not in found:
        raise FileCorrectionApproverConfigInvalidError()
    return tuple(found)


async def _scenario(session) -> ApprovalScenario | None:
    return (
        await session.exec(select(ApprovalScenario).where(ApprovalScenario.scenario_code == FILE_CORRECTION_SCENARIO))
    ).first()


async def _flow(session, scenario_id: int) -> ApprovalFlowDefinition | None:
    return (
        await session.exec(
            select(ApprovalFlowDefinition).where(
                ApprovalFlowDefinition.scenario_id == int(scenario_id),
                ApprovalFlowDefinition.flow_code == CORRECTION_FLOW_CODE,
            )
        )
    ).first()


async def _active_version(session, flow_id: int) -> ApprovalFlowVersion | None:
    return (
        await session.exec(
            select(ApprovalFlowVersion)
            .where(
                ApprovalFlowVersion.flow_definition_id == int(flow_id),
                ApprovalFlowVersion.is_active == True,  # noqa: E712
            )
            .order_by(ApprovalFlowVersion.version_no.desc(), ApprovalFlowVersion.id.desc())
        )
    ).first()


async def _nodes(session, flow_version_id: int) -> list[ApprovalNodeDefinition]:
    return list(
        (
            await session.exec(
                select(ApprovalNodeDefinition)
                .where(ApprovalNodeDefinition.flow_version_id == int(flow_version_id))
                .order_by(ApprovalNodeDefinition.node_order.asc(), ApprovalNodeDefinition.id.asc())
            )
        ).all()
    )


async def _space_roles(space_id: int) -> tuple[list[int], list[int]]:
    from bisheng.approval.domain.services.knowledge_space_subscribe_scenario_handler import (
        _resolve_space_roles_via_fga,
    )

    owners, managers = await _resolve_space_roles_via_fga(int(space_id))
    return list(owners), list(managers)
