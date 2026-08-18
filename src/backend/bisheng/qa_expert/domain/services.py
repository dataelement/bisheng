# ruff: noqa: RUF001, RUF002, RUF003
"""
Expert QA Services - 业务逻辑层
核心流程：
- 专家管理：指定、更新、删除
- 提问流程：创建、邀请、发布
- 回答流程：发布、采纳
- 互动流程：评论、投票、通知
"""

import asyncio
import inspect
from datetime import datetime
from types import SimpleNamespace

from loguru import logger

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.qa_expert import (
    QaExpertAdminRequiredError,
    QaExpertAdoptLimitError,
    QaExpertAnswerDeleteNotAllowedError,
    QaExpertAnswerNotAllowedError,
    QaExpertCommentNotAllowedError,
    QaExpertContentLockedError,
    QaExpertDisabledError,
    QaExpertQuestionAccessDeniedError,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.qa_expert import (
    ANSWER_STATUS_DELETED,
    EXPERT_STATUS_ACTIVE,
    EXPERT_STATUS_DISABLED,
    Answer,
    AnswerEligibility,
    Comment,
    Expert,
    QANotification,
    Question,
    QuestionInvite,
)
from bisheng.department.domain.services.department_display_service import (
    build_department_name_projection,
)
from bisheng.dictionary.domain.repositories.implementations.system_dictionary_repository_impl import (
    SystemDictionaryRepositoryImpl,
)
from bisheng.qa_expert.domain.asset_service import QaAssetService, new_owner_stable_id
from bisheng.qa_expert.domain.capability import (
    CapabilityResolver,
    CapabilitySnapshot,
    is_expert_library_admin,
)
from bisheng.qa_expert.domain.identity import (
    IdentityService,
    copy_stored_anonymous_flags,
    persist_anonymous_choice,
)
from bisheng.qa_expert.domain.question_query import (
    MAX_INVITES,
    QUESTION_TYPE_DIRECTED,
    QUESTION_TYPE_PUBLIC,
    invite_display_names_need_hydrate,
    matches_display_status,
    normalize_list_filter,
    normalize_question_type,
    parse_invite_expert_ids,
    parse_related_doc_ref,
    parse_related_doc_tokens,
    question_display_status,
    serialize_expert_names,
    serialize_invite_ids,
    serialize_related_doc_ids,
)
from bisheng.qa_expert.domain.repositories import (
    AnswerAdoptRepository,
    AnswerEligibilityRepository,
    AnswerRepository,
    CommentRepository,
    ExpertRepository,
    NotificationRepository,
    PublishApproverRepository,
    PublishRequestRepository,
    QAExpertStatsRepository,
    QuestionInviteRepository,
    QuestionRepository,
    VoteRepository,
)
from bisheng.qa_expert.domain.rich_text import question_description_to_plain_text
from bisheng.qa_expert.domain.schemas import (
    AnswerCreateRequest,
    CommentCreateRequest,
    ExpertCreateRequest,
    ExpertUpdateRequest,
    QuestionCreateRequest,
    QuestionUpdateRequest,
)
from bisheng.telemetry.domain.mid_table.realtime_qa_question import (
    RealtimeQaQuestionFact,
)
from bisheng.user.domain.models.user import UserDao


# ==================== 错误定义 ====================
class ExpertNotFoundError(BaseErrorCode):
    """专家不存在"""

    Code = 10901
    Msg = "Expert not found"


class QuestionNotFoundError(BaseErrorCode):
    """问题不存在"""

    Code = 10902
    Msg = "Question not found"


class AnswerNotFoundError(BaseErrorCode):
    """回答不存在"""

    Code = 10903
    Msg = "Answer not found"


class InvalidInvitationError(BaseErrorCode):
    """无效的邀请"""

    Code = 10904
    Msg = "Invalid expert invitation"


class PermissionDeniedError(BaseErrorCode):
    """权限不足"""

    Code = 10905
    Msg = "Permission denied"


class AdoptLimitExceededError(QaExpertAdoptLimitError):
    """兼容旧类名；错误码 18304。"""


# 同题未删除回答中，adopted=true 的上限
MAX_ADOPTED_ANSWERS_PER_QUESTION = 3
ELIGIBILITY_SOURCE_INVITED = "invited"
ELIGIBILITY_SOURCE_PRE_ADOPT_ANSWER = "pre_adopt_answer"


class QAExpertStatsService:
    """Expert QA statistics service."""

    def __init__(self):
        self.repository = QAExpertStatsRepository()

    async def get_overview_stats(self) -> dict[str, int | float]:
        """Get Expert QA overview statistics."""
        return await self.repository.get_overview_stats()


# ==================== 专家服务 ====================
class ExpertService:
    """专家业务逻辑"""

    def __init__(self):
        self.repository = ExpertRepository()
        self.publish_service = None

    def _publish(self):
        if self.publish_service is None:
            from bisheng.qa_expert.domain.publish_service import PublishService

            self.publish_service = PublishService()
        return self.publish_service

    @staticmethod
    def _require_admin(user) -> None:
        """写专家库仅专家库管理员（Portal isPortalAdmin），不是平台超管。"""
        if not is_expert_library_admin(user):
            raise QaExpertAdminRequiredError()

    @staticmethod
    def _with_department_projection(expert: Expert, department) -> dict:
        expert_dict = expert.model_dump()
        expert_dict["department_id"] = expert.depart_ment
        if department is None:
            expert_dict["depart_ment"] = None
            expert_dict["department_short_name"] = None
            expert_dict["department_display_name"] = None
            return expert_dict
        projection = build_department_name_projection(department)
        expert_dict["depart_ment"] = projection.name
        expert_dict["department_short_name"] = projection.short_name
        expert_dict["department_display_name"] = projection.display_name
        return expert_dict

    @staticmethod
    async def _sync_wechat_user_id(user_id: int | None, wechat_user_id: str | None) -> None:
        """将企业微信用户ID同步到关联的user表。"""
        if user_id is None:
            return
        new_id = (wechat_user_id or "").strip() or None
        user = await UserDao.aget_user(user_id)
        if not user:
            return
        current_id = getattr(user, "wechat_user_id", None) or None
        if not new_id or new_id == current_id:
            return
        user.wechat_user_id = new_id
        user.update_time = datetime.now()
        await UserDao.aupdate_user(user)

    async def create_expert(self, request: ExpertCreateRequest, user=None) -> dict:
        """创建专家（专家库管理员操作）"""
        self._require_admin(user)
        # 检查是否已是专家
        existing = await self.repository.get_by_user_name(request.expert_name, request.user_id)
        if existing:
            raise InvalidInvitationError(message=f"Expert {request.expert_name} is already exists")

        expert = Expert(
            expert_name=request.expert_name,
            introduction=request.introduction,
            depart_ment=request.depart_ment,
            user_id=request.user_id,
            major=request.major,
            position=request.position,
            job_family=request.job_family,
            job_category=request.job_category,
        )
        temp_expert = await self.repository.create(expert)
        await self._sync_wechat_user_id(temp_expert.user_id, request.wechat_user_id)
        depart = await DepartmentDao.aget_by_id(temp_expert.depart_ment)
        return self._with_department_projection(temp_expert, depart)

    async def update_expert(self, expert_id: int, request: ExpertUpdateRequest, user=None) -> dict:
        """更新专家信息"""
        self._require_admin(user)
        expert = await self.repository.get_by_id(expert_id)
        if not expert:
            raise ExpertNotFoundError()

        update_data = request.dict(exclude_unset=True)
        wechat_user_id = update_data.pop("wechat_user_id", None)
        temp_expert = await self.repository.update(expert_id, **update_data)
        await self._sync_wechat_user_id(temp_expert.user_id, wechat_user_id)
        depart = await DepartmentDao.aget_by_id(temp_expert.depart_ment)
        return self._with_department_projection(temp_expert, depart)

    async def list_experts(
        self,
        keyword: str | None = None,
        department_id: str | None = None,
        job_family: str | None = None,
        job_category: str | None = None,
        position: str | None = None,
        major: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 20,
        answer_desc: bool | None = None,
        adoption_desc: bool | None = None,
        vote_desc: bool | None = None,
    ) -> tuple[list[dict], int]:
        """列表查询专家"""
        sort_by_department = sort_by == "department"
        experts, total = await self.repository.list_all(
            keyword=keyword,
            department_id=department_id,
            job_family=job_family,
            job_category=job_category,
            position=position,
            major=major,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=0 if sort_by_department else skip,
            limit=None if sort_by_department else limit,
            answer_desc=answer_desc,
            adoption_desc=adoption_desc,
            vote_desc=vote_desc,
        )
        experts_all = await self._build_expert_rows(experts)
        if sort_by_department:
            populated = [item for item in experts_all if str(item.get("department_display_name") or "").strip()]
            empty = [item for item in experts_all if not str(item.get("department_display_name") or "").strip()]
            populated.sort(
                key=lambda item: (
                    str(item.get("department_display_name") or "").casefold(),
                    str(item.get("depart_ment") or "").casefold(),
                    str(item.get("expert_name") or "").casefold(),
                    int(item.get("id") or 0),
                ),
                reverse=sort_order == "desc",
            )
            experts_all = (populated + empty)[skip : skip + limit]
        return experts_all, total

    async def list_filter_options(self) -> dict[str, object]:
        """获取专家管理页部门及四个职业维度的筛选项。"""
        options = await self.repository.list_filter_options()
        department_ids = []
        for value in options.get("department_ids", []):
            try:
                department_ids.append(int(value))
            except (TypeError, ValueError):
                continue

        departments = await DepartmentDao.aget_by_ids(department_ids)
        department_options = []
        for department in departments:
            if department.id is None or not str(department.name or "").strip():
                continue
            projection = build_department_name_projection(department)
            department_options.append(
                {
                    "id": str(department.id),
                    "name": projection.name,
                    "short_name": projection.short_name,
                    "display_name": projection.display_name,
                }
            )
        department_options = sorted(
            department_options,
            key=lambda item: (
                str(item["display_name"]).casefold(),
                str(item["name"]).casefold(),
                str(item["id"]),
            ),
        )
        # 职业维度字段对应系统字典表中的 type code
        field_to_type = {
            "job_families": "expert_job_family",
            "job_categories": "expert_job_category",
            "positions": "expert_position",
            "majors": "expert_major",
        }

        async def _build_dict_options(keys: list[str], dict_type: str) -> list[dict[str, str]]:
            """将字典键列表转换为 dict_key / dict_value 键值对列表。"""
            if not keys:
                return []
            async with get_async_db_session() as session:
                dict_repository = SystemDictionaryRepositoryImpl(session)
                dict_items = await dict_repository.find_all_for_export(dict_type=dict_type, is_enabled=True)
            key_to_value = {item.dict_key: item.dict_value for item in dict_items}
            return [{"dict_key": key, "dict_value": key_to_value.get(key, key)} for key in keys]

        return {
            "departments": department_options,
            "job_families": await _build_dict_options(options.get("job_families", []), field_to_type["job_families"]),
            "job_categories": await _build_dict_options(
                options.get("job_categories", []), field_to_type["job_categories"]
            ),
            "positions": await _build_dict_options(options.get("positions", []), field_to_type["positions"]),
            "majors": await _build_dict_options(options.get("majors", []), field_to_type["majors"]),
        }

    async def _build_dict_key_maps(self, keys_by_field: dict[str, set[str]]) -> dict[str, dict[str, str]]:
        """查询系统字典表,按字段构建 dict_key -> dict_value 映射。"""
        field_to_type = {
            "job_family": "expert_job_family",
            "job_category": "expert_job_category",
            "position": "expert_position",
            "major": "expert_major",
        }
        result: dict[str, dict[str, str]] = {}
        async with get_async_db_session() as session:
            dict_repository = SystemDictionaryRepositoryImpl(session)
            for field, keys in keys_by_field.items():
                dict_type = field_to_type.get(field)
                if not dict_type or not keys:
                    result[field] = {}
                    continue
                dict_items = await dict_repository.find_all_for_export(dict_type=dict_type, is_enabled=True)
                result[field] = {item.dict_key: item.dict_value for item in dict_items}
        return result

    async def _build_expert_rows(self, experts: list[Expert]) -> list[dict]:
        department_ids: set[int] = set()
        user_ids: list[int] = []
        job_family_keys: set[str] = set()
        job_category_keys: set[str] = set()
        position_keys: set[str] = set()
        major_keys: set[str] = set()
        for expert in experts:
            try:
                if expert.depart_ment:
                    department_ids.add(int(expert.depart_ment))
            except (TypeError, ValueError):
                pass
            if expert.user_id:
                user_ids.append(expert.user_id)
            if expert.job_family:
                job_family_keys.add(expert.job_family)
            if expert.job_category:
                job_category_keys.add(expert.job_category)
            if expert.position:
                position_keys.add(expert.position)
            if expert.major:
                major_keys.add(expert.major)

        departments = await DepartmentDao.aget_by_ids(sorted(department_ids))
        department_map = {int(department.id): department for department in departments if department.id is not None}

        users = await UserDao.aget_user_by_ids(list(set(user_ids))) or []
        wechat_user_ids = {user.user_id: user.wechat_user_id for user in users if user.user_id is not None}

        dict_key_maps = await self._build_dict_key_maps(
            {
                "job_family": job_family_keys,
                "job_category": job_category_keys,
                "position": position_keys,
                "major": major_keys,
            }
        )

        experts_all = []
        for expert in experts:
            try:
                department_id = int(expert.depart_ment) if expert.depart_ment else None
            except (TypeError, ValueError):
                department_id = None
            expert_dict = self._with_department_projection(
                expert,
                department_map.get(department_id),
            )
            expert_dict["job_family"] = dict_key_maps["job_family"].get(expert.job_family, expert.job_family)
            expert_dict["job_category"] = dict_key_maps["job_category"].get(expert.job_category, expert.job_category)
            expert_dict["position"] = dict_key_maps["position"].get(expert.position, expert.position)
            expert_dict["major"] = dict_key_maps["major"].get(expert.major, expert.major)
            expert_dict["expert_score"] = (
                int(expert.answer_count or 0) + int(expert.adoption_count or 0) * 5 + int(expert.vote_count or 0) * 2
            )
            expert_dict["wechat_user_id"] = wechat_user_ids.get(expert.user_id)
            experts_all.append(expert_dict)
        return experts_all

    async def disable_expert(self, expert_id: int, user) -> Expert:
        """停用专家：status=0；回调转公开默认同意。"""
        self._require_admin(user)
        expert = await self.repository.get_by_id(expert_id)
        if not expert:
            raise ExpertNotFoundError()
        updated = await self.repository.update(expert_id, status=EXPERT_STATUS_DISABLED)
        await self._publish().on_expert_disabled(int(expert.user_id))
        return updated or expert

    async def enable_expert(self, expert_id: int, user) -> Expert:
        """恢复专家：不加入历史已结束转公开申请。"""
        self._require_admin(user)
        expert = await self.repository.get_by_id(expert_id)
        if not expert:
            raise ExpertNotFoundError()
        updated = await self.repository.update(expert_id, status=EXPERT_STATUS_ACTIVE)
        return updated or expert

    async def delete_expert(self, expert_id: int, user=None) -> bool:
        """兼容 DELETE：映射为停用，不硬删。"""
        await self.disable_expert(expert_id, user)
        return True

    async def get_expertinfo(self, expert_name: str) -> dict | None:
        """获取专家信息"""
        expert = await self.repository.get_expertinfo(expert_name)
        if expert:
            department = DepartmentDao.get_by_id(expert.depart_ment)
            return self._with_department_projection(expert, department)
        return None

    async def get_expertinfobyid(self, user_id: int) -> bool:
        """获取专家信息"""
        return await self.repository.get_expertinfo_userid(user_id)


# ==================== 问题服务 ====================
class QuestionService:
    """问题业务逻辑"""

    def __init__(self, asset_service: QaAssetService | None = None):
        self.repository = QuestionRepository()
        self.expert_repo = ExpertRepository()
        self.invite_repo = QuestionInviteRepository()
        self.answer_repo = AnswerRepository()
        self.notification_repo = NotificationRepository()
        self.adopt_repo = AnswerAdoptRepository()
        self.eligibility_repo = AnswerEligibilityRepository()
        self.publish_request_repo = PublishRequestRepository()
        self.publish_approver_repo = PublishApproverRepository()
        self.asset_service = asset_service
        self.capability_resolver = CapabilityResolver()
        self.related_docs_access_checker = None
        self.identity_service = None

    async def _identity(self) -> IdentityService:
        """懒加载身份脱敏；单测可注入 identity_service 避免打库。"""
        if self.identity_service is None:
            self.identity_service = IdentityService()
        return self.identity_service

    async def _assets(self) -> QaAssetService:
        if self.asset_service is None:
            self.asset_service = QaAssetService(await get_minio_storage())
        return self.asset_service

    async def _resolve_question(self, question: Question) -> Question:
        values = {
            "image_url": question.image_url,
            "file_url": question.file_url,
            "attachments": question.attachments,
        }
        if not any(values.values()):
            return question
        resolved = await (await self._assets()).resolve_fields(entity_type="question", values=values)
        response_data = question.model_dump()
        response_data.update(resolved)
        return Question(**response_data)

    async def create_question(
        self,
        user_id: int,
        request: QuestionCreateRequest,
        user_name: str,
        tenant_id: int | None = None,
    ) -> Question:
        """创建问题：写 qa_question + qa_question_invite；存量默认 public。"""
        if not user_id:
            raise QaExpertQuestionAccessDeniedError()
        question_type = normalize_question_type(getattr(request, "question_type", None))
        invite_ids = parse_invite_expert_ids(
            invited_expert_ids=getattr(request, "invited_expert_ids", None),
            invited_experts=request.invited_experts,
        )
        experts = await self._validate_invites(user_id, question_type, invite_ids, request)
        related_docs = serialize_related_doc_ids(
            getattr(request, "related_doc_ids", None),
            request.related_docs,
        )
        asker_anonymous = 1 if bool(getattr(request, "asker_anonymous", False)) else 0
        reveal = getattr(request, "asker_reveal_on_public", None)
        # 未匿名时转公开姓名选项无意义，不落库，避免旧客户端误带 true/false。
        asker_reveal_on_public = None if (not asker_anonymous or reveal is None) else (1 if reveal else 0)

        asset_values = {
            "image_url": request.image_url,
            "file_url": request.file_url,
            "attachments": request.attachments,
        }
        promotion = None
        if any(asset_values.values()):
            promotion = await (await self._assets()).promote_fields(
                tenant_id=tenant_id,
                entity_type="question",
                owner_stable_id=new_owner_stable_id(),
                values=asset_values,
            )
            asset_values.update(promotion.values)
        question = Question(
            user_id=user_id,
            title=request.title,
            description=request.description,
            business_domain=request.business_domain,
            attachments=asset_values["attachments"],
            related_docs=related_docs,
            invited_experts=serialize_invite_ids(invite_ids),
            experts_names=serialize_expert_names(experts),
            image_url=asset_values["image_url"],
            file_url=asset_values["file_url"],
            file_name=request.file_name,
            created_by=user_name,
            tenant_id=tenant_id or 1,
            question_type=question_type,
            asker_anonymous=asker_anonymous,
            asker_reveal_on_public=asker_reveal_on_public,
        )

        try:
            question = await self.repository.create(question)
        except Exception:
            if promotion is not None:
                await (await self._assets()).compensate(promotion)
            raise
        if invite_ids:
            await self.invite_repo.create_many(
                [
                    QuestionInvite(
                        tenant_id=tenant_id or 1,
                        question_id=question.id,
                        expert_id=expert.id,
                        user_id=expert.user_id,
                    )
                    for expert in experts
                ]
            )
        if promotion is not None:
            await (await self._assets()).cleanup_sources(promotion)
        # 发送邀请通知
        await self._send_expert_invitation_inbox_notice(question, user_id, user_name)

        try:
            await RealtimeQaQuestionFact.record_success(
                tenant_id=tenant_id,
                user_id=user_id,
                user_name=user_name,
                question_id=question.id,
                qa_type="expert",
                scene="expert_question",
                source_app="expert_qa",
                business_domain_code=request.business_domain,
                timestamp=int(question.created_at.timestamp()),
            )
        except Exception:
            logger.exception(
                "Failed to project expert question telemetry question_id={}",
                question.id,
            )

        logger.info(f"Question created: {question.id} by user {user_id}")
        return await self._resolve_question(question)

    async def _validate_invites(
        self,
        user_id: int,
        question_type: str,
        invite_ids: list[int],
        request: QuestionCreateRequest,
    ) -> list:
        """校验邀请人数与专家有效性；定向且匿名时须预选转公开后是否公开姓名。"""
        if question_type == QUESTION_TYPE_DIRECTED:
            if (
                bool(getattr(request, "asker_anonymous", False))
                and getattr(request, "asker_reveal_on_public", None) is None
            ):
                raise InvalidInvitationError(msg="定向匿名题须选择转公开后是否公开姓名")
            if not (1 <= len(invite_ids) <= MAX_INVITES):
                raise InvalidInvitationError(msg="定向题须邀请 1–3 位有效专家")
        elif len(invite_ids) > MAX_INVITES:
            raise InvalidInvitationError(msg="公开题最多邀请 3 位专家")
        experts = []
        for expert_id in invite_ids:
            expert = await self.expert_repo.get_by_id(expert_id)
            if expert is None:
                raise InvalidInvitationError(msg="邀请的专家不存在")
            if int(getattr(expert, "status", 1) or 0) != 1:
                raise QaExpertDisabledError()
            if int(expert.user_id) == int(user_id):
                raise InvalidInvitationError(msg="不能邀请自己")
            experts.append(expert)
        return experts

    def _require_user(self, user, user_id: int | None):
        if user is not None:
            return user
        if user_id:
            return SimpleNamespace(user_id=user_id, is_admin=lambda: False, role=None, user_name="")
        raise QaExpertQuestionAccessDeniedError()

    async def _invite_map(self, questions: list) -> dict[int, set[int]]:
        ids = [int(q.id) for q in questions if getattr(q, "id", None) is not None]
        return await self.invite_repo.list_user_ids_by_question_ids(ids)

    async def _hydrate_invite_names(self, questions: list) -> None:
        """列表/详情把 invited_experts 的档案姓名填进 experts_names，避免页面展示专家 ID。"""
        need: list = []
        expert_ids: list[int] = []
        seen: set[int] = set()
        for question in questions:
            invited = getattr(question, "invited_experts", None)
            names = getattr(question, "experts_names", None)
            if not invite_display_names_need_hydrate(names, invited):
                continue
            need.append(question)
            for expert_id in parse_invite_expert_ids(invited_expert_ids=None, invited_experts=invited):
                if expert_id not in seen:
                    seen.add(expert_id)
                    expert_ids.append(expert_id)
        if not need or not expert_ids:
            return
        experts = await self.expert_repo.get_by_ids(expert_ids)
        name_by_id = {
            int(expert.id): str(getattr(expert, "expert_name", "") or "").strip()
            for expert in experts
            if getattr(expert, "id", None) is not None
        }
        for question in need:
            invited = getattr(question, "invited_experts", None)
            labels = [
                name_by_id.get(expert_id) or str(expert_id)
                for expert_id in parse_invite_expert_ids(invited_expert_ids=None, invited_experts=invited)
            ]
            filled = ";".join(label for label in labels if label)
            if filled:
                self._annotate(question, experts_names=filled)

    def _is_question_visible(self, user, question, invited_user_ids: set[int]) -> bool:
        snapshot = CapabilitySnapshot(invited_user_ids=frozenset(invited_user_ids))
        result = self.capability_resolver.resolve(user, question, snapshot)
        return bool(result.capabilities.visible)

    @staticmethod
    def _annotate(row, **fields):
        """给 ORM 行挂响应态字段（非表列）；Pydantic 禁止直接 setattr。"""
        for name, value in fields.items():
            object.__setattr__(row, name, value)
        return row

    def _attach_display_status(self, question):
        return self._annotate(question, display_status=question_display_status(question))

    async def _attach_asker(self, viewer, question, *, can_view_real_identity: bool) -> None:
        """列表/详情挂脱敏后的 asker；不改表列 created_by，避免别名被写回库。"""
        asker_view = await (await self._identity()).mask_identity(
            viewer,
            question_id=int(question.id),
            user_id=int(question.user_id),
            real_name=str(getattr(question, "created_by", "") or ""),
            anonymous=bool(int(getattr(question, "asker_anonymous", 0) or 0)),
            question_type=str(getattr(question, "question_type", "") or QUESTION_TYPE_PUBLIC),
            reveal_on_public=getattr(question, "asker_reveal_on_public", None),
            tenant_id=int(getattr(question, "tenant_id", 1) or 1),
        )
        self._annotate(
            question,
            asker=asker_view.to_dict(can_view_real_identity=can_view_real_identity),
        )

    async def _attach_latest_answers(self, viewer, questions: list, *, can_view_real_identity: bool) -> None:
        """列表卡片挂每题最新一条未删回答；一批查出，不按卡打回答接口。"""
        ids = [int(question.id) for question in questions if getattr(question, "id", None) is not None]
        if not ids:
            return
        latest_map = await self.answer_repo.list_latest_by_question_ids(ids)
        if not latest_map:
            return
        identity = await self._identity()
        for question in questions:
            answer = latest_map.get(int(question.id))
            if answer is None:
                continue
            real_name = str(getattr(answer, "expert_name", "") or "")
            anonymous = bool(int(getattr(answer, "anonymous", 0) or 0))
            user_id = int(getattr(answer, "user_id", 0) or 0)
            display_name = real_name or "专家"
            shown_anonymous = False
            if anonymous and user_id:
                view = await identity.mask_identity(
                    viewer,
                    question_id=int(question.id),
                    user_id=user_id,
                    real_name=real_name,
                    anonymous=True,
                    question_type=str(getattr(question, "question_type", "") or QUESTION_TYPE_PUBLIC),
                    reveal_on_public=getattr(answer, "reveal_on_public", None),
                    tenant_id=int(getattr(question, "tenant_id", 1) or 1),
                )
                payload = view.to_dict(can_view_real_identity=can_view_real_identity)
                display_name = str(payload.get("display_name") or "匿名同事")
                shown_anonymous = bool(payload.get("anonymous"))
            excerpt = question_description_to_plain_text(str(getattr(answer, "content", "") or ""))
            if len(excerpt) > 120:
                excerpt = f"{excerpt[:120]}..."
            self._annotate(
                question,
                latest_answer={
                    "id": int(answer.id),
                    "excerpt": excerpt,
                    "adopted": bool(getattr(answer, "adopted", False)),
                    "expert_name": display_name,
                    "anonymous": shown_anonymous,
                },
            )

    async def hydrate_related_docs(
        self, related_docs: str | None, user=None, owner_user_id: int | None = None
    ) -> list[dict]:
        """解析关联文档串。问答可见不等于文档可读；无权 forbidden，缺失 not_found。

        owner_user_id 仅为兼容旧调用方，不再按提问者特判。
        """
        del owner_user_id
        views: list[dict] = []
        injected = getattr(self, "related_docs_access_checker", None)
        space_cache: dict[int, bool] = {}

        async def _default_checker(_user, space_id: int, file_id: int):
            from bisheng.qa_expert.domain.related_docs_access import check_related_doc_access

            return await check_related_doc_access(_user, space_id, file_id, space_cache=space_cache)

        checker = injected if callable(injected) else _default_checker
        from bisheng.qa_expert.domain.related_docs_access import load_related_doc_title

        for token in parse_related_doc_tokens(related_docs):
            parsed = parse_related_doc_ref(token)
            if parsed is None:
                views.append(
                    {
                        "id": token,
                        "space_id": None,
                        "file_id": None,
                        "title": None,
                        "accessible": False,
                        "unavailable_reason": "not_found",
                    }
                )
                continue
            space_id, file_id = parsed
            doc_id = f"{space_id}-{file_id}"
            accessible = False
            reason = "forbidden"
            access = checker(user, space_id, file_id)
            if inspect.isawaitable(access):
                try:
                    from bisheng.qa_expert.domain.related_docs_access import (
                        RELATED_DOC_ACCESS_TIMEOUT_SEC,
                    )

                    access = await asyncio.wait_for(access, timeout=RELATED_DOC_ACCESS_TIMEOUT_SEC)
                except Exception:
                    access = False
            if access is None:
                accessible = False
                reason = "not_found"
            elif access is False:
                accessible = False
                reason = "forbidden"
            else:
                accessible = True
                reason = None
            title = None
            try:
                title = await load_related_doc_title(space_id, file_id)
            except Exception:
                title = None
            views.append(
                {
                    "id": doc_id,
                    "space_id": space_id,
                    "file_id": file_id,
                    "title": title,
                    "accessible": accessible,
                    "unavailable_reason": reason,
                }
            )
        return views

    async def list_questions(
        self,
        business_domain: str | None = None,
        status: int | None = 0,
        sort_by: str = "latest",
        user_id: int | None = None,
        skip: int = 0,
        limit: int = 20,
        user=None,
        list_filter: str | None = None,
        display_status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Question], int]:
        """列表：filter=mine|invited_me 与 display_status；status=3/4 不当待采纳。"""
        viewer = self._require_user(user, user_id)
        viewer_id = int(viewer.user_id)
        normalized_filter = normalize_list_filter(status=status, list_filter=list_filter)
        expert_id = None
        if status == 4 and normalized_filter != "invited_me":
            if user_id is not None:
                expert = await self.expert_repo.get_by_user_id(user_id)
                if not expert:
                    return [], 0
                expert_id = expert.id
        questions, repo_total = await self.repository.list_all(
            business_domain=business_domain,
            status=status,
            sort_by=sort_by,
            user_id=viewer_id if normalized_filter == "mine" else user_id,
            skip=skip,
            limit=limit,
            expert_id=expert_id,
            list_filter=normalized_filter,
            display_status=display_status,
            keyword=keyword,
            viewer_user_id=viewer_id,
            viewer_is_admin=is_expert_library_admin(viewer),
        )
        await self._hydrate_invite_names(list(questions))
        invite_map = await self._invite_map(list(questions))
        can_view_real = is_expert_library_admin(viewer)
        identity = await self._identity()
        await identity.preload_for_questions(
            [int(question.id) for question in questions if getattr(question, "id", None) is not None]
        )
        visible: list[Question] = []
        for question in questions:
            invited = invite_map.get(int(question.id), set())
            if not self._is_question_visible(viewer, question, invited):
                continue
            if not matches_display_status(question, display_status):
                continue
            # 列表卡片用 qa_question.vote_count（问题点赞），不再逐条 SUM 回答赞。
            # 列表不展示图片/附件，跳过 MinIO 预签名，避免每条一次远端往返。
            self._attach_display_status(question)
            await self._attach_asker(viewer, question, can_view_real_identity=can_view_real)
            visible.append(question)
        await self._attach_latest_answers(viewer, visible, can_view_real_identity=can_view_real)
        # 分页总数用仓储计数；页内可见性再滤只影响本页条目，不能把 total 收成当前页长度。
        return visible, int(repo_total or 0)

    async def get_question_detail(
        self,
        question_id: int,
        user_id: int | None = None,
        user=None,
    ) -> Question:
        """详情：定向不可见返回 18301，不泄露标题，不增加浏览数。"""
        viewer = self._require_user(user, user_id)
        question = await self.repository.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()
        await self._hydrate_invite_names([question])
        invite_map = await self._invite_map([question])
        invited = invite_map.get(int(question.id), set())
        if not self._is_question_visible(viewer, question, invited):
            raise QaExpertQuestionAccessDeniedError()
        question.view_count = int(getattr(question, "view_count", 0) or 0) + 1
        await self.repository.update(question_id, view_count=question.view_count)
        resolved = await self._resolve_question(question)
        self._attach_display_status(resolved)
        self._annotate(
            resolved,
            related_doc_views=await self.hydrate_related_docs(
                getattr(resolved, "related_docs", None),
                user=viewer,
                owner_user_id=int(getattr(resolved, "user_id", 0) or 0),
            ),
        )
        from bisheng.qa_expert.domain.publish_service import PublishService, serialize_publish_request

        latest_publish = await PublishService().refresh_latest_for_question(int(resolved.id))
        snapshot = await self._capability_snapshot(resolved, viewer, latest_publish=latest_publish)
        result = self.capability_resolver.resolve(viewer, resolved, snapshot)
        self._annotate(resolved, capabilities=result.capabilities.__dict__)
        if latest_publish is not None:
            payload = serialize_publish_request(
                latest_publish,
                viewer_decision=snapshot.viewer_publish_decision,
            )
            self._annotate(resolved, latest_publish_request=payload)
            if str(latest_publish.status) == "pending":
                self._annotate(resolved, active_publish_request=payload)
        await self._attach_asker(
            viewer,
            resolved,
            can_view_real_identity=bool(result.capabilities.can_view_real_identity),
        )
        return resolved

    async def _capability_snapshot(self, question, user, *, latest_publish=None):
        """详情/写路径共用快照，避免列表与详情资格不一致。"""
        invite_map = await self._invite_map([question])
        invited = invite_map.get(int(question.id), set())
        uid = getattr(user, "user_id", None)
        expert = await self.expert_repo.get_by_user_id(int(uid)) if uid else None
        eligibility: set[int] = set()
        if int(getattr(question, "adopt_count", 0) or 0) > 0:
            eligibility = set(await self.eligibility_repo.list_user_ids(int(question.id)))
        has_answer = False
        if uid:
            has_answer = await self.answer_repo.has_effective_answer(int(question.id), int(uid))
        if latest_publish is None:
            latest_publish = await self.publish_request_repo.get_latest_by_question(int(question.id))
        pending = latest_publish if latest_publish is not None and str(latest_publish.status) == "pending" else None
        approver_ids: set[int] = set()
        viewer_decision: str | None = None
        uid_int = int(uid) if uid else None
        # 终态也要带回本人决策，右上角才能在拒绝后显示「已拒绝」。
        source = pending if pending is not None else latest_publish
        if source is not None:
            for row in await self.publish_approver_repo.list_by_request(int(source.id)):
                if uid_int is not None and int(row.user_id) == uid_int:
                    viewer_decision = str(row.decision)
                if pending is not None and str(row.decision) == "pending":
                    approver_ids.add(int(row.user_id))
        return CapabilitySnapshot(
            expert=expert,
            invited_user_ids=frozenset(invited),
            eligibility_user_ids=frozenset(eligibility),
            effective_answer_count=int(getattr(question, "answer_count", 0) or 0),
            user_has_effective_answer=has_answer,
            has_pending_publish=pending is not None,
            latest_publish_status=str(latest_publish.status) if latest_publish is not None else None,
            approver_user_ids=frozenset(approver_ids),
            viewer_publish_decision=viewer_decision,
        )

    async def find_similar_questions(self, user, text: str, limit: int = 5) -> list[Question]:
        """类似问题仅返回当前用户可见的题；不合并、不阻断发布。"""
        viewer = self._require_user(user, getattr(user, "user_id", None) if user is not None else None)
        rows = await self.repository.search_by_title_like(text, limit=max(limit, 5))
        invite_map = await self._invite_map(rows)
        can_view_real = is_expert_library_admin(viewer)
        visible: list[Question] = []
        for question in rows:
            invited = invite_map.get(int(question.id), set())
            if not self._is_question_visible(viewer, question, invited):
                continue
            resolved = await self._resolve_question(question)
            self._attach_display_status(resolved)
            await self._attach_asker(viewer, resolved, can_view_real_identity=can_view_real)
            visible.append(resolved)
            if len(visible) >= limit:
                break
        return visible

    async def _answerer_user_id(self, answer) -> int | None:
        """解析回答者平台用户 ID：优先 qa_answer.user_id，否则走专家档案。"""
        if getattr(answer, "user_id", None):
            return int(answer.user_id)
        if getattr(answer, "expert_id", None):
            expert = await self.expert_repo.get_by_id(answer.expert_id)
            if expert is not None and getattr(expert, "user_id", None) is not None:
                return int(expert.user_id)
        return None

    async def _write_public_eligibility(self, question, *, tenant_id: int) -> None:
        """公开题首次采纳：受邀 ∪ 采纳前回答者（含已删未采纳）。"""
        invite_map = await self.invite_repo.list_user_ids_by_question_ids([int(question.id)])
        invited = set(invite_map.get(int(question.id), set()))
        answers = await self.answer_repo.list_all_by_question_id(int(question.id))
        answerers: set[int] = set()
        for row in answers:
            user_id = await self._answerer_user_id(row)
            if user_id:
                answerers.add(user_id)
        rows: list[AnswerEligibility] = []
        for user_id in sorted(invited | answerers):
            source = ELIGIBILITY_SOURCE_PRE_ADOPT_ANSWER if user_id in answerers else ELIGIBILITY_SOURCE_INVITED
            rows.append(
                AnswerEligibility(
                    tenant_id=tenant_id,
                    question_id=int(question.id),
                    user_id=user_id,
                    source=source,
                )
            )
        if rows:
            await self.eligibility_repo.create_many(rows)

    async def adopt_answer(self, question_id: int, answer_id: int, operator_id: int) -> Question:
        """采纳：锁问题行、写 qa_answer_adopt、首次置已解决；公开题写资格快照；只调 F070 挂钩。"""
        question = await self.repository.get_by_id_for_update(question_id)
        if not question:
            raise QuestionNotFoundError()

        if question.user_id != operator_id:
            raise PermissionDeniedError(msg="Only question author can adopt answer")

        answer = await self.answer_repo.get_by_id(answer_id)
        if not answer or int(getattr(answer, "status", 0) or 0) == 3:
            raise AnswerNotFoundError()

        if answer.question_id != question_id:
            raise InvalidInvitationError(msg="Answer does not belong to this question")

        if bool(getattr(answer, "adopted", False)):
            logger.info(
                "Answer %s already adopted for question %s; idempotent return",
                answer_id,
                question_id,
            )
            return question

        adopted_count = int(getattr(question, "adopt_count", 0) or 0)
        if adopted_count >= MAX_ADOPTED_ANSWERS_PER_QUESTION:
            raise AdoptLimitExceededError()

        expert_user_id = await self._answerer_user_id(answer)
        if expert_user_id is None:
            raise AnswerNotFoundError()

        locked = await self.repository.apply_adopt_count_locked(
            question_id,
            answer_id=answer_id,
            expert_user_id=expert_user_id,
            adopted_by=operator_id,
            tenant_id=int(getattr(question, "tenant_id", 1) or 1),
            max_adopt=MAX_ADOPTED_ANSWERS_PER_QUESTION,
        )
        if locked.status == "limit":
            raise AdoptLimitExceededError()
        if locked.status == "already":
            return locked.question or question
        if locked.status == "mismatch":
            raise InvalidInvitationError(msg="Answer does not belong to this question")
        if locked.status != "ok" or locked.question is None:
            raise AnswerNotFoundError()
        question = locked.question
        is_first = bool(locked.is_first)
        if getattr(answer, "expert_id", None):
            await self.expert_repo.increment_adoption_count(answer.expert_id, count=1)

        if is_first and str(getattr(question, "question_type", QUESTION_TYPE_PUBLIC)) == QUESTION_TYPE_PUBLIC:
            try:
                await self._write_public_eligibility(
                    question,
                    tenant_id=int(getattr(question, "tenant_id", 1) or 1),
                )
            except Exception:
                logger.exception("qa_answer_eligibility snapshot failed question_id={}", question_id)

        await self._send_adoption_notification(question, answer)

        try:
            from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
            from bisheng.points.domain.services.points_award_hooks import notify_answer_adopted

            await notify_answer_adopted(
                tenant_id=int(get_current_tenant_id() or getattr(question, "tenant_id", None) or DEFAULT_TENANT_ID),
                question_id=int(question_id),
                answer_id=int(answer_id),
                answerer_id=expert_user_id,
            )
        except Exception:
            logger.exception(
                "points.award.hooks adopt notify failed answer_id=%s",
                answer_id,
            )

        self._attach_display_status(question)
        logger.info(f"Answer {answer_id} adopted for question {question_id}")
        return question

    async def get_business_domains(self) -> list[str]:
        """获取所有业务域"""
        # 修复了原代码中的错误引用 (self -> self.repository)
        return await self.repository.get_business_domains()

    async def get_stats(self) -> dict:
        """获取问题统计"""
        return await self.repository.get_stats()

    async def _send_invitation_notifications(
        self,
        question_id: int,
        sender_id: int,
        expert_ids: list[int],
    ):
        """发送邀请通知给专家"""
        for expert_id in expert_ids:
            notification = QANotification(
                recipient_id=expert_id,
                sender_id=sender_id,
                notification_type="invited",
                question_id=question_id,
                content="You are invited to answer a question",
                # tenant_id=tenant_id
            )
            await self.notification_repo.create(notification)

    async def _send_adoption_notification(
        self,
        question: Question,
        answer: Answer,
    ):
        """采纳结果通知回答作者；匿名提问者用同题别名。"""
        if not question or not answer:
            return
        from bisheng.qa_expert.domain.inbox_notice import display_name_for_trigger, send_qa_inbox

        receiver = int(getattr(answer, "user_id", 0) or 0)
        if receiver <= 0:
            return
        display, masked = await display_name_for_trigger(
            question,
            user_id=int(question.user_id),
            real_name=str(getattr(question, "created_by", "") or ""),
            anonymous=bool(int(getattr(question, "asker_anonymous", 0) or 0)),
            reveal_on_public=getattr(question, "asker_reveal_on_public", None),
        )
        await send_qa_inbox(
            action_code="qa_answer_accepted",
            system_text="qa_answer_accepted",
            question=question,
            receivers=[receiver],
            sender_user_id=int(question.user_id),
            sender_display=display,
            sender_anonymous=masked,
            answer_id=int(answer.id),
            tooltip=(answer.content or "")[:50],
        )

    async def get_answer_count_by_domain(self) -> list[dict]:
        """获取每个业务域的回答数"""
        return await self.repository.get_answer_count_by_domain()

    async def delete_question(
        self,
        question_id: int,
        tenant_id: int | None = None,
    ) -> bool:
        """删除问题；首答锁定后提问者不可删。"""
        question = await self.repository.get_by_id(question_id)
        if not question:
            return False
        if int(getattr(question, "content_locked", 0) or 0):
            raise QaExpertContentLockedError()
        deleted = await self.repository.delete(question_id)
        if deleted:
            try:
                await RealtimeQaQuestionFact.delete_question(
                    tenant_id=tenant_id,
                    question_id=question_id,
                    qa_type="expert",
                )
            except Exception:
                logger.exception(
                    "Failed to remove expert question {} from real-time dashboard",
                    question_id,
                )
        return deleted

    async def update_question(
        self,
        question_id: int,
        request: QuestionUpdateRequest,
        tenant_id: int | None = None,
    ) -> Question:
        """更新问题信息；首答后正文/类型/邀请已锁定。"""
        question = await self.repository.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()
        if int(getattr(question, "content_locked", 0) or 0):
            raise QaExpertContentLockedError()

        update_data = request.model_dump(exclude_unset=True)
        if update_data.get("status") == 2:
            update_data.pop("status", None)
        asset_fields = {"image_url", "file_url", "attachments"}
        requested_assets = {name: update_data[name] for name in asset_fields if name in update_data}
        promotion = None
        if any(value for value in requested_assets.values()):
            promotion = await (await self._assets()).promote_fields(
                tenant_id=tenant_id,
                entity_type="question",
                owner_stable_id=str(question_id),
                values=requested_assets,
            )
            update_data.update(promotion.values)
        try:
            new_question = await self.repository.update(question_id, **update_data)
        except Exception:
            if promotion is not None:
                await (await self._assets()).compensate(promotion)
            raise
        if promotion is not None:
            await (await self._assets()).cleanup_sources(promotion)
        # 发送邀请通知
        # await self._send_expert_invitation_inbox_notice(new_question, user_id,user_name)

        # logger.info(f"Question updated: {new_question.id} by user {user_id}")
        return await self._resolve_question(new_question)

    async def _send_expert_invitation_inbox_notice(
        self,
        question: Question,
        sender_id: int,
        sender_name: str,
    ):
        expert_ids = [int(item) for item in (question.invited_experts or "").split(";") if item.strip().isdigit()]
        if not expert_ids:
            return

        receiver_user_ids = []
        for expert_id in expert_ids:
            expert = await self.expert_repo.get_by_id(expert_id)
            if expert and expert.user_id != sender_id:
                receiver_user_ids.append(expert.user_id)

        receiver_user_ids = list(set(receiver_user_ids))
        if not receiver_user_ids:
            return

        from bisheng.qa_expert.domain.inbox_notice import display_name_for_trigger, send_qa_inbox

        display, masked = await display_name_for_trigger(
            question,
            user_id=int(sender_id),
            real_name=sender_name or "",
            anonymous=bool(int(getattr(question, "asker_anonymous", 0) or 0)),
            reveal_on_public=getattr(question, "asker_reveal_on_public", None),
        )
        await send_qa_inbox(
            action_code="qa_expert_invited",
            system_text="qa_expert_invited",
            question=question,
            receivers=receiver_user_ids,
            sender_user_id=int(sender_id),
            sender_display=display,
            sender_anonymous=masked,
            tooltip=question_description_to_plain_text(question.description)[:50],
        )


# ==================== 回答服务 ====================
class AnswerService:
    """回答业务逻辑"""

    def __init__(self, asset_service: QaAssetService | None = None):
        self.repository = AnswerRepository()
        self.question_repo = QuestionRepository()
        self.expert_repo = ExpertRepository()
        self.invite_repo = QuestionInviteRepository()
        self.eligibility_repo = AnswerEligibilityRepository()
        self.notification_repo = NotificationRepository()
        self.comment_repo = CommentRepository()
        self.publish_request_repo = PublishRequestRepository()
        self.asset_service = asset_service
        self.capability_resolver = CapabilityResolver()
        self.identity_service = None

    async def _identity(self) -> IdentityService:
        """懒加载身份脱敏；单测可注入 identity_service 避免打库。"""
        if self.identity_service is None:
            self.identity_service = IdentityService()
        return self.identity_service

    async def _assets(self) -> QaAssetService:
        if self.asset_service is None:
            self.asset_service = QaAssetService(await get_minio_storage())
        return self.asset_service

    @staticmethod
    def _annotate(row, **fields):
        """给 ORM 行挂响应态字段（非表列）；Pydantic 禁止直接 setattr。"""
        for name, value in fields.items():
            object.__setattr__(row, name, value)
        return row

    async def _attach_answer_author(self, viewer, answer: Answer, question: Question) -> Answer:
        """列表/详情挂脱敏后的回答者身份；不改表列 expert_name，避免别名被写回库。"""
        identity = await self._identity()
        real_name = str(getattr(answer, "expert_name", "") or "")
        anonymous = bool(int(getattr(answer, "anonymous", 0) or 0))
        user_id = int(getattr(answer, "user_id", 0) or 0)
        can_view_real = is_expert_library_admin(viewer)
        if anonymous and user_id:
            view = await identity.mask_identity(
                viewer,
                question_id=int(question.id),
                user_id=user_id,
                real_name=real_name,
                anonymous=True,
                question_type=str(getattr(question, "question_type", "") or QUESTION_TYPE_PUBLIC),
                reveal_on_public=getattr(answer, "reveal_on_public", None),
                tenant_id=int(getattr(question, "tenant_id", 1) or 1),
            )
            payload = view.to_dict(can_view_real_identity=can_view_real)
        else:
            payload = {
                "display_name": real_name or "专家",
                "avatar_url": None,
                "anonymous": False,
            }
        return self._annotate(answer, author=payload)

    async def attach_author(self, answer: Answer, viewer) -> Answer:
        """写接口返回前挂 author；缺题则原样返回。"""
        question = await self.question_repo.get_by_id(int(answer.question_id))
        if question is None:
            return answer
        return await self._attach_answer_author(viewer, answer, question)

    @staticmethod
    def _is_adopted_answer(answer) -> bool:
        """已采纳：认 qa_answer.adopted，兼容旧 status=2。"""
        if bool(getattr(answer, "adopted", False)):
            return True
        return int(getattr(answer, "status", 1) or 0) == 2

    async def _answer_author_id(self, answer) -> int | None:
        """解析回答作者用户 ID：优先 qa_answer.user_id，否则专家档案。"""
        if getattr(answer, "user_id", None):
            return int(answer.user_id)
        if getattr(answer, "expert_id", None) is not None:
            expert = await self.expert_repo.get_by_id(answer.expert_id)
            if expert is not None and getattr(expert, "user_id", None) is not None:
                return int(expert.user_id)
        return None

    async def _assert_question_visible(self, question, user) -> None:
        """回答/评论读路径与问题详情同一套定向可见性。"""
        if question is None:
            raise QuestionNotFoundError()
        viewer = user or SimpleNamespace(user_id=0, is_admin=lambda: False, role=None)
        invite_map = await self.invite_repo.list_user_ids_by_question_ids([int(question.id)])
        invited = invite_map.get(int(question.id), set())
        snapshot = CapabilitySnapshot(invited_user_ids=frozenset(invited))
        if not self.capability_resolver.resolve(viewer, question, snapshot).capabilities.visible:
            raise QaExpertQuestionAccessDeniedError()

    async def _can_author_delete(self, answer, operator_id: int, *, pending_publish: bool) -> bool:
        """作者可删：本人、未采纳、无进行中转公开、未软删。"""
        if int(getattr(answer, "status", 0) or 0) == ANSWER_STATUS_DELETED:
            return False
        if self._is_adopted_answer(answer) or pending_publish:
            return False
        author_id = await self._answer_author_id(answer)
        return author_id is not None and int(author_id) == int(operator_id)

    async def _pending_publish_after_lazy_expire(self, question_id: int):
        """列答/删答前复用转公开详情的惰性过期，避免到期后仍按 pending 拦删除。"""
        from bisheng.qa_expert.domain.publish_service import PublishService

        refresher = getattr(self, "publish_refresher", None)
        if refresher is None:
            refresher = PublishService().refresh_latest_for_question
        await refresher(int(question_id))
        return await self.publish_request_repo.get_pending_by_question(int(question_id))

    async def _resolve_answer(self, answer: Answer) -> Answer:
        values = {"images_url": answer.images_url, "attachments": answer.attachments}
        if not any(values.values()):
            return answer
        resolved = await (await self._assets()).resolve_fields(entity_type="answer", values=values)
        response_data = answer.model_dump()
        response_data.update(resolved)
        return Answer(**response_data)

    async def create_answer(
        self,
        user_id: int,
        request: AnswerCreateRequest,
        tenant_id: int | None = None,
        user=None,
    ) -> Answer:
        """提交有效回答：资格校验后写 qa_answer，CAS 置 content_locked。"""
        return await self.submit_answer(user_id, request, tenant_id=tenant_id, user=user)

    async def submit_answer(
        self,
        user_id: int,
        request: AnswerCreateRequest,
        tenant_id: int | None = None,
        user=None,
    ) -> Answer:
        """发布回答：资格校验 → 插入回答 → 条件更新锁 → inbox 通知。"""
        if not user_id:
            raise QaExpertQuestionAccessDeniedError()
        question = await self.question_repo.get_by_id(request.question_id)
        if not question:
            raise QuestionNotFoundError()

        expert = await self.expert_repo.get_by_user_id(user_id)
        if not expert:
            raise ExpertNotFoundError(message="Only verified experts can answer questions")
        if int(getattr(expert, "status", 1) or 0) != 1:
            raise QaExpertDisabledError()

        invite_map = await self.invite_repo.list_user_ids_by_question_ids([int(question.id)])
        invited = invite_map.get(int(question.id), set())
        eligibility: set[int] = set()
        if int(getattr(question, "adopt_count", 0) or 0) > 0:
            eligibility = set(await self.eligibility_repo.list_user_ids(int(question.id)))
        viewer = user or SimpleNamespace(user_id=user_id, is_admin=lambda: False, role=None, user_name="")
        snapshot = CapabilitySnapshot(
            expert=expert,
            invited_user_ids=frozenset(invited),
            eligibility_user_ids=frozenset(eligibility),
            effective_answer_count=int(getattr(question, "answer_count", 0) or 0),
        )
        caps = self.capability_resolver.resolve(viewer, question, snapshot).capabilities
        if not caps.can_answer:
            raise QaExpertAnswerNotAllowedError()

        anonymous, reveal_on_public = persist_anonymous_choice(
            anonymous=bool(getattr(request, "anonymous", False)),
            reveal_on_public=getattr(request, "reveal_on_public", None),
            question_type=str(getattr(question, "question_type", "") or QUESTION_TYPE_PUBLIC),
        )

        asset_values = {"attachments": request.attachments, "images_url": request.images_url}
        promotion = None
        if any(asset_values.values()):
            promotion = await (await self._assets()).promote_fields(
                tenant_id=tenant_id,
                entity_type="answer",
                owner_stable_id=new_owner_stable_id(),
                values=asset_values,
            )
            asset_values.update(promotion.values)

        answer = Answer(
            question_id=request.question_id,
            expert_id=expert.id,
            user_id=user_id,
            content=request.content,
            attachments=asset_values["attachments"],
            related_docs=request.related_docs,
            images_url=asset_values["images_url"],
            expert_name=expert.expert_name,
            tenant_id=tenant_id or getattr(question, "tenant_id", 1) or 1,
            anonymous=anonymous,
            reveal_on_public=reveal_on_public,
        )

        try:
            answer = await self.repository.create(answer)
        except Exception:
            if promotion is not None:
                await (await self._assets()).compensate(promotion)
            raise
        if promotion is not None:
            await (await self._assets()).cleanup_sources(promotion)

        await self.question_repo.try_lock_content(int(question.id))
        await self.question_repo.increment_answer_count(request.question_id)
        await self.expert_repo.increment_answer_count(expert.id, count=1)
        await self._send_answer_notification(question, answer)
        try:
            from bisheng.qa_expert.domain.publish_service import PublishService

            await PublishService().add_late_answerer(question, int(user_id))
        except Exception:
            logger.exception("qa.answer.join_publish_failed question_id={}", question.id)
        logger.info(f"Answer created: {answer.id} for question {request.question_id}")
        return await self._resolve_answer(answer)

    async def get_answers(
        self,
        question_id: int,
        skip: int = 0,
        limit: int = 100,
        sort_by: str | None = None,
        user=None,
    ) -> tuple[list[Answer], int]:
        """获取问题的回答列表；匿名回答者 expert_name 在 JSON 层改成别名。"""
        question = await self.question_repo.get_by_id(question_id)
        await self._assert_question_visible(question, user)
        answers, total = await self.repository.get_by_question_id(question_id, skip=skip, limit=limit, sort_by=sort_by)
        viewer = user or SimpleNamespace(user_id=0, is_admin=lambda: False, role=None)
        viewer_id = int(getattr(viewer, "user_id", 0) or 0)
        pending = await self._pending_publish_after_lazy_expire(int(question.id))
        pending_publish = pending is not None
        question_svc = QuestionService()
        question_svc.related_docs_access_checker = getattr(self, "related_docs_access_checker", None)
        resolved: list[Answer] = []
        for answer in answers:
            item = await self._resolve_answer(answer)
            item = await self._attach_answer_author(viewer, item, question)
            can_delete = await self._can_author_delete(item, viewer_id, pending_publish=pending_publish)
            related_doc_views = await question_svc.hydrate_related_docs(
                getattr(item, "related_docs", None),
                user=viewer,
                owner_user_id=int(getattr(question, "user_id", 0) or 0),
            )
            self._annotate(item, can_delete=can_delete, related_doc_views=related_doc_views)
            resolved.append(item)
        return resolved, total

    async def get_by_expertname(
        self,
        expert_name: str,
        question_id: int,
        user=None,
    ) -> Answer | None:
        """按专家名取回答；同样挂脱敏 author。"""
        answer = await self.repository.get_by_expertname(expert_name, question_id)
        if answer is None:
            return None
        resolved = await self._resolve_answer(answer)
        question = await self.question_repo.get_by_id(question_id)
        if question is None:
            return resolved
        viewer = user or SimpleNamespace(user_id=0, is_admin=lambda: False, role=None)
        return await self._attach_answer_author(viewer, resolved, question)

    async def update_answer(
        self,
        answer_id: int,
        operator_id: int,
        content: str | None = None,
        attachments: str | list[str] | None = None,
        related_docs: str | list[int] | None = None,
        images_url: str | None = None,
        tenant_id: int | None = None,
    ) -> Answer:
        """更新回答"""
        answer = await self.repository.get_by_id(answer_id)
        if not answer:
            raise AnswerNotFoundError()

        # 只有回答对应的专家用户可以编辑
        expert = await self.expert_repo.get_by_id(answer.expert_id) if answer.expert_id is not None else None
        if not expert or expert.user_id != operator_id:
            raise PermissionDeniedError(message="Only answer author can edit")

        update_data = {}
        if content is not None:
            update_data["content"] = content
        if attachments is not None:
            update_data["attachments"] = attachments
        if related_docs is not None:
            update_data["related_docs"] = related_docs
        if images_url is not None:
            update_data["images_url"] = images_url
        requested_assets = {}
        if attachments is not None:
            requested_assets["attachments"] = attachments
        if images_url is not None:
            requested_assets["images_url"] = images_url
        promotion = None
        if any(value for value in requested_assets.values()):
            promotion = await (await self._assets()).promote_fields(
                tenant_id=tenant_id,
                entity_type="answer",
                owner_stable_id=str(answer_id),
                values=requested_assets,
            )
            update_data.update(promotion.values)
        try:
            updated = await self.repository.update(answer_id, **update_data)
        except Exception:
            if promotion is not None:
                await (await self._assets()).compensate(promotion)
            raise
        if promotion is not None:
            await (await self._assets()).cleanup_sources(promotion)
        if updated is None:
            raise AnswerNotFoundError()
        return await self._resolve_answer(updated)

    async def delete_answer(self, answer_id: int, operator_id: int) -> bool:
        """作者删除未采纳回答：软删回答、硬删其下评论；有效转公开申请进行中时拒绝。"""
        answer = await self.repository.get_by_id(answer_id)
        if not answer or int(getattr(answer, "status", 0) or 0) == ANSWER_STATUS_DELETED:
            raise AnswerNotFoundError()

        author_id = await self._answer_author_id(answer)
        if author_id is None or int(author_id) != int(operator_id):
            raise PermissionDeniedError(msg="Only answer author can delete")
        if self._is_adopted_answer(answer):
            raise QaExpertAnswerDeleteNotAllowedError(msg="已采纳的回答不可删除")
        pending = await self._pending_publish_after_lazy_expire(int(answer.question_id))
        if pending is not None:
            raise QaExpertAnswerDeleteNotAllowedError(msg="转公开申请进行中，暂不可删除回答")

        deleted = await self.repository.delete(answer_id)
        if not deleted:
            raise AnswerNotFoundError()
        await self.comment_repo.delete_by_answer_id(answer_id)
        question = await self.question_repo.get_by_id(answer.question_id)
        if question is not None:
            new_count = max(int(getattr(question, "answer_count", 0) or 0) - 1, 0)
            await self.question_repo.update(answer.question_id, answer_count=new_count)
        return True

    async def _send_answer_notification(self, question: Question, answer: Answer):
        """每次提交回答通知提问者；匿名专家用同题别名。"""
        if not question or not answer:
            return
        sender_id = int(getattr(answer, "user_id", 0) or 0)
        if sender_id <= 0:
            return
        from bisheng.qa_expert.domain.inbox_notice import display_name_for_trigger, send_qa_inbox

        display, masked = await display_name_for_trigger(
            question,
            user_id=sender_id,
            real_name=str(getattr(answer, "expert_name", "") or ""),
            anonymous=bool(int(getattr(answer, "anonymous", 0) or 0)),
            reveal_on_public=getattr(answer, "reveal_on_public", None),
        )
        await send_qa_inbox(
            action_code="qa_expert_answered",
            system_text="qa_expert_answered",
            question=question,
            receivers=[int(question.user_id)],
            sender_user_id=sender_id,
            sender_display=display,
            sender_anonymous=masked,
            answer_id=int(answer.id),
            tooltip=(answer.content or "")[:50],
        )


# ==================== 评论服务 ====================
class CommentService:
    """评论业务逻辑"""

    def __init__(self):
        self.repository = CommentRepository()
        self.answer_repo = AnswerRepository()
        self.notification_repo = NotificationRepository()
        self.question_repo = QuestionRepository()
        self.expert_repo = ExpertRepository()
        self.invite_repo = QuestionInviteRepository()
        self.capability_resolver = CapabilityResolver()
        self.identity_service = None

    async def _identity(self) -> IdentityService:
        """懒加载身份脱敏；单测可注入 identity_service 避免打库。"""
        if self.identity_service is None:
            self.identity_service = IdentityService()
        return self.identity_service

    @staticmethod
    def _annotate(row, **fields):
        """给 ORM 行挂响应态字段（非表列）；Pydantic 禁止直接 setattr。"""
        for name, value in fields.items():
            object.__setattr__(row, name, value)
        return row

    @staticmethod
    def _is_answer_author(user_id: int, answer) -> bool:
        """评论者是否该回答作者；只认 qa_answer.user_id，避免误伤未填 user_id 的 mock。"""
        owner = int(getattr(answer, "user_id", 0) or 0)
        return bool(owner) and owner == int(user_id)

    def _resolve_comment_identity(
        self,
        user_id: int,
        request: CommentCreateRequest,
        question,
        answer,
    ) -> tuple[int, int | None]:
        """追问继承问题匿名；自评继承回答匿名；评他人时用请求体并校验定向 reveal。"""
        is_follow_up = bool(getattr(request, "is_follow_up", False)) or answer is None
        if is_follow_up and int(user_id) == int(getattr(question, "user_id", 0) or 0):
            return copy_stored_anonymous_flags(
                getattr(question, "asker_anonymous", 0),
                getattr(question, "asker_reveal_on_public", None),
            )
        if answer is not None and self._is_answer_author(user_id, answer):
            return copy_stored_anonymous_flags(
                getattr(answer, "anonymous", 0),
                getattr(answer, "reveal_on_public", None),
            )
        return persist_anonymous_choice(
            anonymous=bool(getattr(request, "anonymous", False)),
            reveal_on_public=getattr(request, "reveal_on_public", None),
            question_type=str(getattr(question, "question_type", "") or QUESTION_TYPE_PUBLIC),
        )

    async def _attach_comment_author(self, viewer, comment: Comment, question) -> Comment:
        """列表/创建响应挂脱敏作者；不改表列 user_name。"""
        identity = await self._identity()
        real_name = str(getattr(comment, "user_name", "") or "")
        anonymous = bool(int(getattr(comment, "anonymous", 0) or 0))
        user_id = int(getattr(comment, "user_id", 0) or 0)
        can_view_real = is_expert_library_admin(viewer)
        if anonymous and user_id:
            view = await identity.mask_identity(
                viewer,
                question_id=int(question.id),
                user_id=user_id,
                real_name=real_name,
                anonymous=True,
                question_type=str(getattr(question, "question_type", "") or QUESTION_TYPE_PUBLIC),
                reveal_on_public=getattr(comment, "reveal_on_public", None),
                tenant_id=int(getattr(question, "tenant_id", 1) or 1),
            )
            payload = view.to_dict(can_view_real_identity=can_view_real)
        else:
            payload = {
                "display_name": real_name or "用户",
                "avatar_url": None,
                "anonymous": False,
            }
        return self._annotate(comment, author=payload)

    async def attach_author(self, comment: Comment, viewer) -> Comment:
        """写接口返回前挂 author。"""
        question_id = int(getattr(comment, "question_id", 0) or 0)
        question = await self.question_repo.get_by_id(question_id) if question_id else None
        if question is None:
            return comment
        return await self._attach_comment_author(viewer, comment, question)

    async def _assert_can_comment(self, user_id: int, user_name: str, question, *, is_follow_up: bool) -> None:
        """定向题普通评论须先有有效回答；追问不受该门槛。"""
        if not user_id:
            raise QaExpertQuestionAccessDeniedError()
        invite_map = await self.invite_repo.list_user_ids_by_question_ids([int(question.id)])
        invited = invite_map.get(int(question.id), set())
        expert = await self.expert_repo.get_by_user_id(user_id)
        has_answer = await self.answer_repo.has_effective_answer(int(question.id), user_id)
        snapshot = CapabilitySnapshot(
            expert=expert,
            invited_user_ids=frozenset(invited),
            user_has_effective_answer=has_answer,
            effective_answer_count=int(getattr(question, "answer_count", 0) or 0),
        )
        viewer = SimpleNamespace(user_id=user_id, is_admin=lambda: False, role=None, user_name=user_name)
        caps = self.capability_resolver.resolve(viewer, question, snapshot).capabilities
        if not caps.visible:
            raise QaExpertQuestionAccessDeniedError()
        if is_follow_up:
            return
        if not caps.can_comment:
            raise QaExpertCommentNotAllowedError()

    async def create_comment(self, user_id: int, user_name: str, request: CommentCreateRequest) -> Comment:
        """发布评论或追问；追问/自评继承匿名，评他人才用请求体。"""
        comment = None
        if request.answer_id and request.answer_id != 0:
            answer = await self.answer_repo.get_by_id(request.answer_id)
            if not answer:
                raise AnswerNotFoundError()
            question = await self.question_repo.get_by_id(answer.question_id)
            if not question:
                raise QuestionNotFoundError()
            await self._assert_can_comment(user_id, user_name, question, is_follow_up=bool(request.is_follow_up))
            anonymous, reveal_on_public = self._resolve_comment_identity(user_id, request, question, answer)
            comment = Comment(
                answer_id=request.answer_id,
                question_id=answer.question_id,
                user_id=user_id,
                user_name=user_name,
                content=request.content,
                is_follow_up=request.is_follow_up,
                anonymous=anonymous,
                reveal_on_public=reveal_on_public,
            )

            answer.comment_count += 1
            await self.answer_repo.update(request.answer_id, comment_count=answer.comment_count)
            comment = await self.repository.create(comment)
            await self._send_comment_notification(
                answer,
                comment,
            )
        else:
            if not request.question_id:
                raise ValueError("缺少问题ID，无法创建追问")
            question = await self.question_repo.get_by_id(request.question_id)
            if not question:
                raise QuestionNotFoundError()
            await self._assert_can_comment(user_id, user_name, question, is_follow_up=True)
            anonymous, reveal_on_public = self._resolve_comment_identity(user_id, request, question, None)
            comment = Comment(
                answer_id=0,
                question_id=request.question_id,
                user_id=user_id,
                content=request.content,
                is_follow_up=True,
                user_name=user_name,
                anonymous=anonymous,
                reveal_on_public=reveal_on_public,
            )
            question.comment_count += 1
            await self.question_repo.update(request.question_id, comment_count=question.comment_count)
            comment = await self.repository.create(comment)

        return comment

    async def get_comments(
        self,
        answer_id: int | None = None,
        question_id: int | None = None,
        skip: int = 0,
        limit: int = 100,
        user=None,
    ) -> tuple[list[Comment], int]:
        """获取回答的评论；可见性跟随问题，匿名评论 user_name 在 JSON 层改成别名。"""
        question = None
        if answer_id:
            answer = await self.answer_repo.get_by_id(answer_id)
            qid = int(getattr(answer, "question_id", 0) or 0) if answer is not None else int(question_id or 0)
            if not qid:
                raise AnswerNotFoundError()
            question = await self.question_repo.get_by_id(qid)
        elif question_id:
            question = await self.question_repo.get_by_id(question_id)
        if question is None:
            raise QuestionNotFoundError()
        viewer = user or SimpleNamespace(user_id=0, is_admin=lambda: False, role=None)
        invite_map = await self.invite_repo.list_user_ids_by_question_ids([int(question.id)])
        invited = invite_map.get(int(question.id), set())
        snapshot = CapabilitySnapshot(invited_user_ids=frozenset(invited))
        if not self.capability_resolver.resolve(viewer, question, snapshot).capabilities.visible:
            raise QaExpertQuestionAccessDeniedError()
        comments, total = await self.repository.get_by_answer_id(
            answer_id, question_id=question_id or int(question.id), skip=skip, limit=limit
        )
        if not comments:
            return comments, total
        for comment in comments:
            await self._attach_comment_author(viewer, comment, question)
        return comments, total

    async def _send_comment_notification(
        self,
        answer: Answer,
        comment: Comment,
    ):
        """评论通知回答作者和提问者；匿名评论用同题别名。发件人由 send_qa_inbox 排除。"""
        if not answer or not comment:
            return
        question = await self.question_repo.get_by_id(answer.question_id)
        if not question:
            return
        answerer = int(getattr(answer, "user_id", 0) or 0)
        asker = int(getattr(question, "user_id", 0) or 0)
        receivers = list(dict.fromkeys(uid for uid in (answerer, asker) if uid > 0))
        if not receivers:
            return
        from bisheng.qa_expert.domain.inbox_notice import display_name_for_trigger, send_qa_inbox

        display, masked = await display_name_for_trigger(
            question,
            user_id=int(comment.user_id),
            real_name=str(getattr(comment, "user_name", "") or ""),
            anonymous=bool(int(getattr(comment, "anonymous", 0) or 0)),
            reveal_on_public=getattr(comment, "reveal_on_public", None),
        )
        await send_qa_inbox(
            action_code="qa_answer_commented",
            system_text="qa_answer_commented",
            question=question,
            receivers=receivers,
            sender_user_id=int(comment.user_id),
            sender_display=display,
            sender_anonymous=masked,
            answer_id=int(answer.id),
            comment_id=int(comment.id) if comment.id else None,
            tooltip=(comment.content or "")[:50],
        )


# ==================== 投票服务 ====================
class VoteService:
    """投票业务逻辑"""

    def __init__(self):
        self.repository = VoteRepository()
        self.question_repo = QuestionRepository()
        self.answer_repo = AnswerRepository()
        self.expert_repo = ExpertRepository()

    async def vote_question(self, user_id: int, question_id: int) -> bool:
        """给问题点赞"""
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise QuestionNotFoundError()

        vote = await self.repository.add_question_vote(user_id, question_id)
        if vote:
            question.vote_count += 1
            await self.question_repo.update(question_id, vote_count=question.vote_count)
            return True
        return False

    async def vote_answer(self, user_id: int, answer_id: int) -> bool:
        """给回答点赞（有用）"""
        answer = await self.answer_repo.get_by_id(answer_id)
        if not answer:
            raise AnswerNotFoundError()

        vote = await self.repository.add_answer_vote(user_id, answer_id)
        if vote:
            answer.vote_count += 1
            await self.answer_repo.update(answer_id, vote_count=answer.vote_count)

            await self.expert_repo.increment_vote_count(answer.expert_id, count=1)

            return True
        return False
