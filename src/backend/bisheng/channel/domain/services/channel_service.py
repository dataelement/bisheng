import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision, ApprovalGateRequest
from bisheng.approval.domain.services.approval_gate import ApprovalGate
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.channel_subscribe_scenario_handler import ChannelSubscribeScenarioHandler
from bisheng.channel.domain.models.article_read_record import ArticleReadRecord
from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.models.channel_knowledge_sync import (
    ChannelKnowledgeSync,
    ChannelKnowledgeSyncDao,
)
from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
from bisheng.channel.domain.repositories.interfaces.article_read_repository import ArticleReadRepository
from bisheng.channel.domain.repositories.interfaces.channel_info_source_repository import ChannelInfoSourceRepository
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.schemas.article_schema import (
    ArticleDetailResponse,
    ArticleFullDocument,
    ArticleSearchPageResponse,
    ArticleSearchResultItem,
    ArticleSensitiveHit,
    ArticleSensitiveReview,
)
from bisheng.channel.domain.schemas.channel_manager_schema import (
    AddArticlesToKnowledgeSpaceRequest,
    ChannelDetailResponse,
    ChannelItemResponse,
    ChannelMemberPageResponse,
    ChannelMemberResponse,
    ChannelSquareItemResponse,
    ChannelSquarePageResponse,
    CreateChannelRequest,
    KnowledgeSyncConfig,
    KnowledgeSyncMainConfig,
    KnowledgeSyncSpaceItem,
    KnowledgeSyncSubConfig,
    MyChannelQueryRequest,
    QueryTypeEnum,
    RemoveMemberRequest,
    SetPinRequest,
    SortByEnum,
    SubscribeChannelRequest,
    SubscriptionStatusEnum,
    UpdateChannelRequest,
    UpdateMemberRoleRequest,
)
from bisheng.channel.domain.services.article_count_cache import ArticleCountCache
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import (
    ArticleSensitiveViolationError,
    ChannelAccessDeniedError,
    ChannelAdminLimitExceededError,
    ChannelCreateLimitExceededError,
    ChannelNotFoundError,
    ChannelOrganizationGrantUnsubscribeDeniedError,
    ChannelPermissionDeniedError,
)
from bisheng.common.errcode.knowledge_space import SpaceFileNameDuplicateError, SpacePermissionDeniedError
from bisheng.common.models.space_channel_member import (
    CHANNEL_ROLE_TO_RELATION,
    REJECTED_STATUS_DISPLAY_WINDOW,
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMemberDao,
    UserRoleEnum,
    legacy_role_for_channel_relation,
    resolve_channel_relation,
)
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import get_bisheng_information_client
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.models.knowledge_file import FileSource
from bisheng.message.domain.services.message_service import MessageService
from bisheng.message.domain.services.notification_content import build_notify_content
from bisheng.permission.domain.channel_permission_template import (
    default_permission_ids_for_relation as default_channel_permission_ids_for_relation,
)
from bisheng.permission.domain.channel_permission_template import (
    relation_from_channel_permission_ids,
)
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRevokeItem
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService
from bisheng.permission.domain.services.owner_service import OwnerService
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.role.domain.services.quota_service import QuotaResourceType, QuotaService
from bisheng.sensitive_word.domain.schemas import SensitiveWordBusinessType
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import SensitiveWordPolicyService
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid, get_request_ip

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

# Maximum number of administrators per channel
MAX_ADMIN_COUNT = 5
CHANNEL_ADMIN_ASSIGNMENT_MESSAGE = "assigned_channel_admin"
CHANNEL_ADMIN_REVOKED_MESSAGE = "revoked_channel_admin"
CHANNEL_MEMBER_REMOVED_MESSAGE = "removed_channel_member"
CHANNEL_MADE_PRIVATE_MESSAGE = "channel_made_private"
CHANNEL_DISMISSED_MESSAGE = "channel_dismissed"
CHANNEL_MEMBER_RELATIONS = {"owner", "manager", "editor", "viewer"}
# F037-B: a single ES `terms` clause holds up to index.max_terms_count ids
# (default 65536). Beyond that, the batched unread query falls back to the
# per-channel total-minus-read path to avoid a query error.
_MAX_UNREAD_EXCLUDE_TERMS = 65536


def _self_channel_binding_key(channel_id: str, user_id: int, relation: ChannelRelationEnum) -> str:
    return f"channel:{channel_id}:self:{user_id}:{relation.value}:-"


def _member_relation_value(member) -> str | None:
    relation = resolve_channel_relation(member) if member else None
    return relation.value if relation else None


def _legacy_role_value_for_member(member) -> str:
    relation = resolve_channel_relation(member)
    if relation:
        return legacy_role_for_channel_relation(relation).value
    return member.user_role.value


def _is_direct_channel_source(member, user_id: int) -> bool:
    subject_type = getattr(member, "grant_subject_type", None)
    subject_id = getattr(member, "grant_subject_id", None)
    if subject_type is None:
        return True
    return subject_type in {"self", "user"} and (subject_id is None or int(subject_id) == int(user_id))


def _is_organization_channel_source(member) -> bool:
    return getattr(member, "grant_subject_type", None) in {"department", "user_group"}


def _is_authorized_channel_source(member) -> bool:
    return getattr(member, "grant_subject_type", None) in {"user", "department", "user_group"}


def _sorted_channel_permission_ids(permission_ids: set[str]) -> list[str]:
    return sorted(permission_ids)


def _business_member_permission_ids(member) -> set[str]:
    if not member or _is_authorized_channel_source(member):
        return set()
    relation = resolve_channel_relation(member)
    if relation is None:
        return set()
    return default_channel_permission_ids_for_relation(relation.value)


def _effective_relation_value(permission_ids: set[str], member) -> str | None:
    relation = relation_from_channel_permission_ids(permission_ids)
    if relation:
        return relation
    if member and not _is_authorized_channel_source(member):
        return _member_relation_value(member)
    return None


def _legacy_role_value_for_relation(relation: str | None, member=None) -> str:
    if relation:
        return legacy_role_for_channel_relation(ChannelRelationEnum(relation)).value
    if member and not _is_authorized_channel_source(member):
        return _legacy_role_value_for_member(member)
    return UserRoleEnum.MEMBER.value


class ChannelService:
    def __init__(
        self,
        channel_repository: "ChannelRepository",
        space_channel_member_repository: "SpaceChannelMemberRepository",
        channel_info_source_repository: "ChannelInfoSourceRepository",
        article_es_service: "ArticleEsService" = None,
        article_read_repository: "ArticleReadRepository" = None,
        message_service: MessageService | None = None,
        approval_gate: ApprovalGate | None = None,
    ):
        self.channel_repository = channel_repository
        self.space_channel_member_repository = space_channel_member_repository
        self.channel_info_source_repository = channel_info_source_repository
        self.article_es_service = article_es_service or ArticleEsService()
        self.article_read_repository = article_read_repository
        self.message_service = message_service
        self.approval_gate = approval_gate

    async def _get_channel_permission_ids(
        self,
        channel_id: str,
        login_user: UserPayload,
        membership=None,
        *,
        context: dict | None = None,
    ) -> set[str]:
        # F037: when resolving permission ids for a *list* of channels, the user
        # subject strings / bindings / models / binding index are identical across
        # every channel in the request. Building them once (via
        # ``_build_channel_permission_context``) and passing them in here is
        # equivalent to letting ``get_effective_permission_ids_async`` derive them
        # per call -- it falls back to the same helpers when the kwargs are omitted
        # -- but avoids recomputing them (and their DB round-trips) per channel.
        try:
            permission_ids = set(
                await FineGrainedPermissionService.get_effective_permission_ids_async(
                    login_user,
                    "channel",
                    channel_id,
                    **(context or {}),
                )
            )
        except Exception:
            logger.exception("failed to resolve channel permission ids: channel_id=%s", channel_id)
            permission_ids = set()
        permission_ids.update(_business_member_permission_ids(membership))
        return permission_ids

    async def _build_channel_permission_context(self, login_user: UserPayload) -> dict:
        """F037: per-request shared ReBAC evaluation context for channel-list paths.

        These inputs do not vary by channel within a single request; computing them
        once and passing them to each ``_get_channel_permission_ids`` call collapses
        N per-channel recomputations (subject expansion, bindings/models fetch,
        binding index build) into one. The object-specific ``lineage`` is
        intentionally *not* included so every channel still gets its own lineage.
        """
        from bisheng.permission.api.endpoints.resource_permission import _get_bindings

        bindings = await _get_bindings()
        models = await FineGrainedPermissionService.get_relation_models_map()
        user_subject_strings = await FineGrainedPermissionService.get_current_user_subject_strings(login_user)
        binding_department_paths = await FineGrainedPermissionService.get_binding_department_paths(bindings)
        return {
            "models": models,
            "bindings": bindings,
            "binding_department_paths": binding_department_paths,
            "user_subject_strings": user_subject_strings,
            "binding_index": FineGrainedPermissionService.build_binding_index(bindings),
        }

    async def _get_channel_organization_grant_subject_types(
        self,
        channel_id: str,
        login_user: UserPayload,
    ) -> set[str]:
        return await FineGrainedPermissionService.get_matching_binding_subject_types_async(
            login_user,
            "channel",
            channel_id,
            {"department", "user_group"},
        )

    @staticmethod
    def _resolve_subscription_status(
        membership_status: MembershipStatusEnum | None,
        update_time: datetime | None = None,
    ) -> SubscriptionStatusEnum:
        if membership_status is None:
            return SubscriptionStatusEnum.NOT_SUBSCRIBED
        if membership_status == MembershipStatusEnum.ACTIVE:
            return SubscriptionStatusEnum.SUBSCRIBED
        if membership_status == MembershipStatusEnum.PENDING:
            return SubscriptionStatusEnum.PENDING
        if (
            membership_status == MembershipStatusEnum.REJECTED
            and update_time is not None
            and update_time >= datetime.now() - REJECTED_STATUS_DISPLAY_WINDOW
        ):
            return SubscriptionStatusEnum.REJECTED
        return SubscriptionStatusEnum.NOT_SUBSCRIBED

    @classmethod
    def _resolve_membership_subscription_status(cls, membership) -> SubscriptionStatusEnum:
        if membership is None:
            return SubscriptionStatusEnum.NOT_SUBSCRIBED
        return cls._resolve_subscription_status(membership.status, membership.update_time)

    @staticmethod
    def _current_tenant_id(login_user: UserPayload) -> int:
        from bisheng.core.context.tenant import get_current_tenant_id

        return get_current_tenant_id() or login_user.tenant_id

    @staticmethod
    async def _can_view_sensitive_article(login_user: UserPayload) -> bool:
        from bisheng.utils.http_middleware import _check_is_global_super

        if await _check_is_global_super(login_user.user_id):
            return True
        tenant_id = ChannelService._current_tenant_id(login_user)
        return bool(tenant_id and await login_user.has_tenant_admin(tenant_id))

    @staticmethod
    def _article_review_text(article: ArticleSearchResultItem | ArticleFullDocument) -> str:
        return "\n".join(
            [
                getattr(article, "title", "") or "",
                getattr(article, "review_content", "") or getattr(article, "content", "") or "",
            ]
        )

    @classmethod
    def _to_sensitive_review(
        cls,
        *,
        enabled: bool,
        hits: list[Any],
        auto_reply: str | None,
        can_view_sensitive: bool,
    ) -> ArticleSensitiveReview:
        violated = bool(hits)
        return ArticleSensitiveReview(
            enabled=enabled,
            violated=violated,
            hits=[ArticleSensitiveHit(word=hit.word, count=hit.count) for hit in hits],
            can_view=(not violated) or can_view_sensitive,
            auto_reply=auto_reply,
        )

    @classmethod
    async def apply_article_sensitive_reviews(
        cls,
        articles: list[ArticleSearchResultItem | ArticleFullDocument],
        login_user: UserPayload,
    ) -> None:
        if not articles:
            return
        tenant_id = cls._current_tenant_id(login_user)
        can_view_sensitive = await cls._can_view_sensitive_article(login_user)
        results = SensitiveWordPolicyService.check_texts(
            tenant_id=tenant_id,
            business_type=SensitiveWordBusinessType.CHANNEL_ARTICLE,
            texts=[cls._article_review_text(article) for article in articles],
        )
        for article, result in zip(articles, results):
            article.sensitive_review = cls._to_sensitive_review(
                enabled=result.enabled,
                hits=result.hits,
                auto_reply=result.auto_reply,
                can_view_sensitive=can_view_sensitive,
            )

    @classmethod
    async def ensure_article_sensitive_view_allowed(
        cls,
        article: ArticleFullDocument,
        login_user: UserPayload,
    ) -> ArticleSensitiveReview:
        await cls.apply_article_sensitive_reviews([article], login_user)
        review = article.sensitive_review or ArticleSensitiveReview()
        if review.violated and not review.can_view:
            raise ArticleSensitiveViolationError(
                msg=review.auto_reply or ArticleSensitiveViolationError.Msg,
            )
        return review

    @staticmethod
    def _to_article_detail_response(article: ArticleFullDocument) -> ArticleDetailResponse:
        return ArticleDetailResponse(
            doc_id=article.doc_id,
            source_type=article.source_type,
            source_id=article.source_id,
            source_info=article.source_info,
            title=article.title,
            content_html=article.content_html,
            cover_image=article.cover_image,
            publish_time=article.publish_time,
            source_url=article.source_url,
            create_time=article.create_time,
            update_time=article.update_time,
            is_read=article.is_read,
            sensitive_review=article.sensitive_review,
        )

    async def _sync_channel_info_source_metadata(
        self, bisheng_information_client, source_ids: list[str]
    ) -> list[ChannelInfoSource]:
        """Fetch metadata for newly-subscribed sources and insert their channel_info_source rows.

        Shared by create_channel / update_channel / reconcile. Returns the inserted rows so
        callers can schedule follow-up work (e.g. article sync) on them.
        """
        if not source_ids:
            return []
        information_sources = await bisheng_information_client.get_information_source_by_ids(source_ids)
        new_rows = [
            ChannelInfoSource(
                id=info_source.id,
                source_name=info_source.name,
                source_icon=info_source.icon,
                source_type=info_source.business_type,
                description=info_source.description,
            )
            for info_source in information_sources
        ]
        if new_rows:
            await self.channel_info_source_repository.batch_add(new_rows)
        return new_rows

    async def reconcile_information_subscriptions(self) -> dict:
        """Reconcile information-service subscriptions for the current tenant.

        The desired subscription set is the union of every channel's ``source_list``;
        the materialized view is the ``channel_info_source`` table. This converges the two
        (and the external information service) on the eventual-consistency path:

        - ``current - desired`` (orphans): unsubscribe at the information service + delete row.
        - ``desired - current`` (missing): subscribe + fetch metadata + insert row
          (heals subscribes that were missed or failed on the synchronous hot path).

        Per-source failures are isolated (logged + counted) so one bad source never aborts
        the rest; the next run retries it. Must run inside the target tenant's context — the
        ``channel`` / ``channel_info_source`` queries are tenant-scoped automatically.

        Returns ``{"to_sub", "to_unsub", "failed"}`` for observability.
        """
        bisheng_information_client = await get_bisheng_information_client()
        desired = await self.channel_repository.find_all_referenced_source_ids()
        current_rows = await self.channel_info_source_repository.find_all()
        current = {row.id for row in current_rows}

        to_unsub = current - desired
        to_sub = desired - current
        failed = 0

        for source_id in to_unsub:
            try:
                await bisheng_information_client.unsubscribe_information_source([source_id])
                await self.channel_info_source_repository.delete_by_ids([source_id])
            except Exception:
                logger.exception("reconcile: failed to unsubscribe information source %s", source_id)
                failed += 1

        for source_id in to_sub:
            try:
                await bisheng_information_client.subscribe_information_source([source_id])
                await self._sync_channel_info_source_metadata(bisheng_information_client, [source_id])
            except Exception:
                logger.exception("reconcile: failed to subscribe information source %s", source_id)
                failed += 1

        return {"to_sub": len(to_sub), "to_unsub": len(to_unsub), "failed": failed}

    async def create_channel(self, channel_data: CreateChannelRequest, login_user: UserPayload, request=None):
        """Create a new channel based on the provided data and the logged-in user."""
        # Check if the user has reached the role-configurable channel creation quota
        # (F005 quota: `channel`, default 10; admins/-1 = unlimited). effective already
        # folds in the tenant-chain cap, so this enforces both role and tenant limits.
        effective = await QuotaService.get_effective_quota(
            login_user.user_id, QuotaResourceType.CHANNEL, login_user.tenant_id, login_user=login_user
        )
        if effective != -1:
            # Count only channels that STILL EXIST. find_channel_memberships reads
            # space_channel_member without joining `channel`, so a stale creator membership
            # left behind by an already-deleted channel (orphan row) would inflate the count
            # and reject creation one slot early (configured 14 -> only 13 usable). Intersecting
            # the membership business_ids with find_channels_by_ids mirrors what the "created
            # channels" list (get_my_channels) and the front-end pre-check count, keeping all
            # three in lock-step.
            memberships = await self.space_channel_member_repository.find_channel_memberships(
                user_id=login_user.user_id, roles=[UserRoleEnum.CREATOR], statuses=[MembershipStatusEnum.ACTIVE]
            )
            channel_ids = [m.business_id for m in memberships]
            existing_channels = await self.channel_repository.find_channels_by_ids(channel_ids) if channel_ids else []
            if len(existing_channels) >= effective:
                raise ChannelCreateLimitExceededError(quota=effective)

        bisheng_information_client = await get_bisheng_information_client()
        if channel_data.source_list:
            # A source already present in the local channel_info_source table has been
            # subscribed before. The row and the information-service subscription share a
            # lifecycle (both created on first subscribe, both removed together by the
            # daily reconcile), so a present row means "already subscribed" — we skip
            # re-subscribing it. Only sources missing from the table are new subscriptions.
            existing_sources = await self.channel_info_source_repository.find_by_ids(channel_data.source_list)
            existing_source_ids = {source.id for source in existing_sources}
            missing_source_ids = [
                sid for sid in dict.fromkeys(channel_data.source_list) if sid not in existing_source_ids
            ]

            if missing_source_ids:
                # Subscribe the not-yet-subscribed sources BEFORE persisting the channel.
                # The subscribe call enforces the API-key source-count limit (19007); doing
                # it first guarantees that a limit error aborts creation instead of leaving
                # an orphaned channel / membership / OpenFGA owner tuple.
                await bisheng_information_client.subscribe_information_source(missing_source_ids)
                await self._sync_channel_info_source_metadata(bisheng_information_client, missing_source_ids)

        channel_model = Channel(
            name=channel_data.name,
            source_list=channel_data.source_list,
            description=channel_data.description,
            visibility=channel_data.visibility,
            filter_rules=[] if not channel_data.filter_rules else [f.model_dump() for f in channel_data.filter_rules],
            user_id=login_user.user_id,
            is_released=channel_data.is_released,
        )

        channel_model = await self.channel_repository.save(channel_model)

        # Add the creator as a member of the channel
        await self.space_channel_member_repository.add_member(
            business_id=channel_model.id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id,
            role=UserRoleEnum.CREATOR,
            relation=ChannelRelationEnum.OWNER,
            grant_subject_type="self",
            grant_subject_id=login_user.user_id,
            grant_relation=ChannelRelationEnum.OWNER,
            grant_model_id=ChannelRelationEnum.OWNER.value,
            grant_binding_key=_self_channel_binding_key(
                str(channel_model.id),
                login_user.user_id,
                ChannelRelationEnum.OWNER,
            ),
        )

        # F008: Write owner tuple to OpenFGA (INV-2)
        try:
            await OwnerService.write_owner_tuple(
                login_user.user_id,
                "channel",
                str(channel_model.id),
            )
        except Exception as e:
            logger.warning("Failed to write owner tuple for channel %s: %s", channel_model.id, e)

        # Update latest_article_update_time for the new channel
        if channel_model.source_list:
            await self.update_channels_latest_article_time([channel_model])

        # Persist knowledge-sync config, if provided, using the freshly-assigned id.
        if channel_data.knowledge_sync is not None:
            await self._save_knowledge_sync(
                channel_id=channel_model.id,
                cfg=channel_data.knowledge_sync,
                user_id=login_user.user_id,
            )

        # Audit log
        from bisheng.api.services.audit_log import AuditLogService

        if request:
            await AuditLogService.create_channel(
                login_user, get_request_ip(request), str(channel_model.id), channel_model.name
            )

        return channel_model

    async def get_my_channels(
        self, query_data: MyChannelQueryRequest, login_user: UserPayload
    ) -> list[ChannelItemResponse]:
        """
        Get the list of channels associated with the logged-in user based on the query type (created or followed) and sorting preference.
        """

        if query_data.query_type == QueryTypeEnum.CREATED:
            roles = [UserRoleEnum.CREATOR]
        else:
            # My Followed Channels include both ADMIN and MEMBER roles
            roles = [UserRoleEnum.ADMIN, UserRoleEnum.MEMBER]

        # Get the user's channel memberships based on the query type and active status
        memberships = await self.space_channel_member_repository.find_channel_memberships(
            user_id=login_user.user_id, roles=roles, statuses=[MembershipStatusEnum.ACTIVE]
        )

        accessible_ids: list[str] = []
        if query_data.query_type == QueryTypeEnum.FOLLOWED:
            listed_ids = await PermissionService.list_accessible_ids(
                user_id=login_user.user_id,
                relation="can_read",
                object_type="channel",
                login_user=login_user,
            )
            if listed_ids is not None:
                accessible_ids = [str(channel_id) for channel_id in listed_ids]
            else:
                # Admins short-circuit list_accessible_ids to None ("can read all"), which
                # would otherwise drop channels the admin was specifically authorized to via
                # member management (direct user grant: ReBAC + binding, no membership row).
                # Recover those from the admin's own direct channel bindings so they still
                # surface in the followed list — without dumping every channel.
                accessible_ids = await self._directly_granted_channel_ids(login_user.user_id)

        # Batch query channels by IDs
        channel_ids = list(
            dict.fromkeys(
                [
                    *(m.business_id for m in memberships),
                    *accessible_ids,
                ]
            )
        )
        if not channel_ids:
            return []
        channels = await self.channel_repository.find_channels_by_ids(channel_ids)
        channel_map = {ch.id: ch for ch in channels}

        # Get all read article IDs for the current user
        all_read_ids = []
        if self.article_read_repository:
            all_read_ids = await self.article_read_repository.get_all_read_article_ids(login_user.user_id)

        # Build a map of business_id to membership for quick lookup
        membership_map = {m.business_id: m for m in memberships}
        # F037: build the shared ReBAC evaluation context once, then reuse it for
        # every channel instead of recomputing subjects/bindings/models per channel.
        permission_context = await self._build_channel_permission_context(login_user)
        permission_id_results = await asyncio.gather(
            *[
                self._get_channel_permission_ids(
                    channel.id,
                    login_user,
                    membership_map.get(channel.id),
                    context=permission_context,
                )
                for channel in channels
            ]
        )
        permission_ids_map = {
            channel.id: permission_ids for channel, permission_ids in zip(channels, permission_id_results)
        }

        # Construct the result list, filtering out non-authorized private channels for "followed" query type
        result: list[ChannelItemResponse] = []
        channels_to_process = []
        for channel_id in channel_ids:
            channel = channel_map.get(channel_id)
            if not channel:
                continue
            membership = membership_map.get(channel_id)
            permission_ids = permission_ids_map.get(channel_id, set())

            if query_data.query_type == QueryTypeEnum.FOLLOWED:
                if getattr(channel, "user_id", None) == login_user.user_id:
                    continue
                has_view_permission = "view_channel" in permission_ids
                has_business_membership = bool(membership and not _is_authorized_channel_source(membership))
                if not has_business_membership and not has_view_permission:
                    continue
                if membership and _is_authorized_channel_source(membership) and not has_view_permission:
                    continue
                if channel.visibility == ChannelVisibilityEnum.PRIVATE and not has_view_permission:
                    continue

            channels_to_process.append((channel, membership, permission_ids))

        # F037-B: unread counts for the whole page in a single ES msearch round-trip
        # (was N channels x (1 total + read-id chunks) sequential count queries).
        unread_counts = await self._calculate_unread_counts_batch(
            [channel for channel, _, _ in channels_to_process], all_read_ids
        )

        for (channel, membership, permission_ids), unread_count in zip(channels_to_process, unread_counts):
            relation = _effective_relation_value(permission_ids, membership)
            item = ChannelItemResponse(
                id=channel.id,
                name=channel.name,
                source_list=channel.source_list,
                visibility=channel.visibility,
                is_released=channel.is_released,
                latest_article_update_time=channel.latest_article_update_time,
                create_time=channel.create_time,
                user_role=_legacy_role_value_for_relation(relation, membership),
                relation=relation,
                permission_ids=_sorted_channel_permission_ids(permission_ids),
                is_pinned=bool(membership and membership.is_pinned),
                subscribed_at=membership.create_time if membership else None,
                unread_count=unread_count,
            )
            result.append(item)

        # Apply mixed sorting: pinned channels first, then sort by the selected criteria within each group
        result = self._sort_channels(result, query_data.sort_by)

        return result

    async def _calculate_unread_counts_batch(self, channels: list[Channel], all_read_ids: list[str]) -> list[int]:
        """F037-B: unread counts for many channels in one ES msearch round-trip.

        unread = articles matching the channel's main filter AND not in the user's
        read set, expressed as a single count per channel (must_not terms on _id)
        and batched via ``count_articles_batch``. Equivalent to the per-channel
        ``_calculate_unread_count`` oracle (total-minus-read is the same set as
        filter AND NOT read), but collapses N x (1 + read-chunk) sequential ES
        queries into a single round-trip. Order matches the input ``channels``.
        """
        if not channels:
            return []
        # Defensive fallback: a read set larger than a single terms clause can hold
        # would error; preserve correctness via the original per-channel path.
        if all_read_ids and len(all_read_ids) > _MAX_UNREAD_EXCLUDE_TERMS:
            return await asyncio.gather(*[self._calculate_unread_count(channel, all_read_ids) for channel in channels])

        exclude = all_read_ids or None
        requests = []
        for channel in channels:
            main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
            requests.append(
                {
                    "source_ids": channel.source_list,
                    "filter_rules": main_rule_groups if main_rule_groups else None,
                    "exclude_article_ids": exclude,
                }
            )
        return await self.article_es_service.count_articles_batch(requests)

    async def _calculate_unread_count(self, channel: Channel, all_read_ids: list[str]) -> int:
        """Calculate the exact number of unread articles for a given channel."""
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")

        # 2. Get total number of articles for this channel
        total_count = await self.article_es_service.count_articles(
            source_ids=channel.source_list,
            filter_rules=main_rule_groups if main_rule_groups else None,
        )

        if total_count == 0:
            return 0

        # If user hasn't read any articles, everything is unread
        if not all_read_ids:
            return total_count

        # 3. Calculate how many read articles belong to this channel
        # Chunk requests to avoid Elasticsearch TooManyClauses exception (default limit is 1024)
        chunk_size = 1000
        matching_read_count = 0

        tasks = []
        for i in range(0, len(all_read_ids), chunk_size):
            chunked_ids = all_read_ids[i : i + chunk_size]
            tasks.append(
                self.article_es_service.count_articles(
                    source_ids=channel.source_list,
                    filter_rules=main_rule_groups if main_rule_groups else None,
                    include_article_ids=chunked_ids,
                )
            )

        if tasks:
            counts = await asyncio.gather(*tasks)
            matching_read_count = sum(counts)

        # Ensure no negative count just in case
        return max(0, total_count - matching_read_count)

    async def _calculate_sub_channel_unread_counts(self, channel: Channel, all_read_ids: list[str]) -> dict[str, int]:
        """Unread count per sub-channel: total − read for (main rules AND that sub's rules).

        Mirrors _calculate_unread_count but combines the main filter rules with each
        sub-channel's rules (same AND semantics the article search uses)."""
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")

        # Distinct sub-channel names defined on this channel.
        sub_names: list[str] = []
        for fr in channel.filter_rules or []:
            if isinstance(fr, dict) and fr.get("channel_type") == "sub":
                name = fr.get("name")
                if name and name not in sub_names:
                    sub_names.append(name)

        async def unread_for(name: str) -> int:
            sub_rule_groups = self._extract_filter_rule_groups(channel, channel_type="sub", sub_channel_name=name)
            effective_rule_groups = [*main_rule_groups, *sub_rule_groups]
            total_count = await self.article_es_service.count_articles(
                source_ids=channel.source_list,
                filter_rules=effective_rule_groups if effective_rule_groups else None,
            )
            if total_count == 0:
                return 0
            if not all_read_ids:
                return total_count
            chunk_size = 1000
            tasks = [
                self.article_es_service.count_articles(
                    source_ids=channel.source_list,
                    filter_rules=effective_rule_groups if effective_rule_groups else None,
                    include_article_ids=all_read_ids[i : i + chunk_size],
                )
                for i in range(0, len(all_read_ids), chunk_size)
            ]
            matching_read_count = sum(await asyncio.gather(*tasks)) if tasks else 0
            return max(0, total_count - matching_read_count)

        if not sub_names:
            return {}
        counts = await asyncio.gather(*[unread_for(n) for n in sub_names])
        return {name: count for name, count in zip(sub_names, counts)}

    async def _calculate_sub_channel_unread_counts_batch(
        self, channel: Channel, all_read_ids: list[str]
    ) -> dict[str, int]:
        """F040: per-sub-channel unread for one channel in a single ES msearch.

        Expresses each sub-channel's unread directly as ``count(main+sub filter AND
        NOT read_ids)`` (must_not terms) and batches all sub-channels via
        ``count_articles_batch`` — collapsing the per-sub ``total - matching_read``
        loop (S x (1 + read-chunk) sequential ES queries) into one round-trip. Set
        identity makes this equal to the ``_calculate_sub_channel_unread_counts``
        oracle. Oversized read sets fall back to that oracle for correctness."""
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
        sub_names: list[str] = []
        for fr in channel.filter_rules or []:
            if isinstance(fr, dict) and fr.get("channel_type") == "sub":
                name = fr.get("name")
                if name and name not in sub_names:
                    sub_names.append(name)
        if not sub_names:
            return {}
        if all_read_ids and len(all_read_ids) > _MAX_UNREAD_EXCLUDE_TERMS:
            return await self._calculate_sub_channel_unread_counts(channel, all_read_ids)

        exclude = all_read_ids or None
        requests = []
        for name in sub_names:
            sub_rule_groups = self._extract_filter_rule_groups(channel, channel_type="sub", sub_channel_name=name)
            effective_rule_groups = [*main_rule_groups, *sub_rule_groups]
            requests.append(
                {
                    "source_ids": channel.source_list,
                    "filter_rules": effective_rule_groups if effective_rule_groups else None,
                    "exclude_article_ids": exclude,
                }
            )
        counts = await self.article_es_service.count_articles_batch(requests)
        return {name: count for name, count in zip(sub_names, counts)}

    async def get_sub_channel_unread_counts(self, channel_id: str, login_user: UserPayload) -> dict[str, int]:
        """F040: per-sub-channel unread for the current user — served by the dedicated
        ``GET /channel/manager/{id}/unread-counts`` endpoint (split out of channel
        detail so the preview/detail path no longer pays this per-user ES cost)."""
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]
        all_read_ids: list[str] = []
        if self.article_read_repository:
            all_read_ids = await self.article_read_repository.get_all_read_article_ids(login_user.user_id)
        return await self._calculate_sub_channel_unread_counts_batch(channel, all_read_ids)

    @staticmethod
    def _sort_channels(items: list[ChannelItemResponse], sort_by: SortByEnum) -> list[ChannelItemResponse]:
        """
        Sort channels with pinned channels always on top, then sort by the selected criteria:
        """
        if sort_by == SortByEnum.LATEST_UPDATE:

            def sort_key(item: ChannelItemResponse):
                # Pinned channels get pin_order=0, others get pin_order=1, so pinned channels come first.
                pin_order = 0 if item.is_pinned else 1
                timestamp = item.latest_article_update_time.timestamp() if item.latest_article_update_time else 0.0
                return pin_order, -timestamp

        elif sort_by == SortByEnum.LATEST_ADDED:

            def sort_key(item: ChannelItemResponse):
                pin_order = 0 if item.is_pinned else 1
                timestamp = item.subscribed_at.timestamp() if item.subscribed_at else 0.0
                return pin_order, -timestamp

        else:  # CHANNEL_NAME

            def sort_key(item: ChannelItemResponse):
                pin_order = 0 if item.is_pinned else 1
                return (pin_order, item.name or "")

        return sorted(items, key=sort_key)

    async def set_channel_pin(self, pin_data: SetPinRequest, login_user: UserPayload) -> bool:
        """
        Set the pin status of a channel for the logged-in user.
        - Validate that the user is a member of the channel
        - Update the is_pinned status in the membership record
        """

        membership = await self.space_channel_member_repository.find_membership(
            business_id=pin_data.channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=login_user.user_id
        )

        if not membership or membership.status != MembershipStatusEnum.ACTIVE:
            raise ChannelNotFoundError()

        await self.space_channel_member_repository.update_pin_status(
            member_id=membership.id, is_pinned=pin_data.is_pinned
        )

        return True

    async def list_channel_members(
        self, channel_id: str, page: int, page_size: int, keyword: str | None, login_user: UserPayload
    ) -> ChannelMemberPageResponse:
        from bisheng.user.domain.services.user import UserService

        """
        Paginate through the list of channel members.
        - Verify if the current user is a member of the channel
        - Support fuzzy search by username
        - Return user information and associated user groups
        - Sorting: Creators and administrators at the top, regular members sorted by username
        """
        # 1. Verify if the current user is a member of the channel
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=login_user.user_id
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            raise ValueError("You are not a member of this channel and cannot view the member list")

        # 2. If a keyword is provided, perform a fuzzy search on usernames to get matched user_ids
        search_user_ids = None
        if keyword:
            matched_users = await UserDao.afilter_users(user_ids=[], keyword=keyword)
            search_user_ids = [u.user_id for u in matched_users]
            if not search_user_ids:
                return ChannelMemberPageResponse(data=[], total=0)

        # 3. Paginate member records
        members = await self.space_channel_member_repository.find_channel_members_paginated(
            channel_id=channel_id, user_ids=search_user_ids, page=page, page_size=page_size
        )

        # 4. Query total count
        total = await self.space_channel_member_repository.count_channel_members(
            channel_id=channel_id, user_ids=search_user_ids
        )

        if not members:
            return ChannelMemberPageResponse(data=[], total=total)

        # 5. Batch query user information
        member_user_ids = [m.user_id for m in members]
        users = await UserDao.aget_user_by_ids(member_user_ids)
        user_map = {u.user_id: u for u in users}

        # 6. Batch query user group information
        result_list: list[ChannelMemberResponse] = []
        for member in members:
            user = user_map.get(member.user_id)
            user_name = user.user_name if user else f"User {member.user_id}"

            # Query user groups the user belongs to
            user_groups = await login_user.get_user_groups(member.user_id)

            result_list.append(
                ChannelMemberResponse(
                    user_id=member.user_id,
                    user_name=user_name,
                    user_avatar=await UserService.get_avatar_share_link(user.avatar) if user else None,
                    user_role=_legacy_role_value_for_member(member),
                    relation=_member_relation_value(member),
                    user_groups=user_groups,
                )
            )

        return ChannelMemberPageResponse(data=result_list, total=total)

    async def update_member_role(self, req: UpdateMemberRoleRequest, login_user: UserPayload) -> bool:
        """
        Set member role (admin/regular member).
        Permissions:
        - Creators can set anyone as an admin or member
        - Admins cannot promote others to admin, nor can they modify the roles of other admins or creators
        - Modifying the creator's role is not allowed
        """
        # 1. Verify current user permissions
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=login_user.user_id
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            raise ChannelNotFoundError()

        if current_membership.user_role not in (UserRoleEnum.CREATOR, UserRoleEnum.ADMIN):
            raise ChannelPermissionDeniedError()

        # 2. Query target member
        target_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=req.user_id
        )
        if not target_membership or target_membership.status != MembershipStatusEnum.ACTIVE:
            raise ValueError("The target user is not a member of this channel")

        # 3. Modifying the creator's role is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Modifying the creator's role is not allowed")

        # 4. Admin permission limits
        if current_membership.user_role == UserRoleEnum.ADMIN:
            # Admins cannot set others as admins
            if req.role == UserRoleEnum.ADMIN.value:
                raise ValueError("Admins do not have permission to set others as admins")
            # Admins cannot modify the roles of other admins
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError("Admins do not have permission to modify the roles of other admins")

        # 5. Check maximum limit when setting as an admin
        if req.role == UserRoleEnum.ADMIN.value:
            current_admins = await self.space_channel_member_repository.find_members_by_role(
                channel_id=req.channel_id, role=UserRoleEnum.ADMIN
            )
            if len(current_admins) >= MAX_ADMIN_COUNT:
                raise ChannelAdminLimitExceededError()

        should_notify_admin_assignment = (
            target_membership.user_role == UserRoleEnum.MEMBER and req.role == UserRoleEnum.ADMIN.value
        )
        should_notify_admin_revoked = (
            target_membership.user_role == UserRoleEnum.ADMIN and req.role == UserRoleEnum.MEMBER.value
        )
        had_manage_access = False
        if should_notify_admin_assignment:
            had_manage_access = await self._user_can_manage_channel(
                target_membership.user_id,
                req.channel_id,
            )

        # 6. Update role
        target_membership.user_role = UserRoleEnum(req.role)
        await self.space_channel_member_repository.update(target_membership)

        if should_notify_admin_assignment and self.message_service and not had_manage_access:
            await self._send_admin_assignment_notification(
                operator_user_id=login_user.user_id,
                target_user_id=target_membership.user_id,
                channel_id=req.channel_id,
            )
        if should_notify_admin_revoked and self.message_service:
            if not await self._user_can_manage_channel(target_membership.user_id, req.channel_id):
                await self._send_channel_event_notification(
                    action_code=CHANNEL_ADMIN_REVOKED_MESSAGE,
                    operator_user_id=login_user.user_id,
                    operator_user_name=getattr(login_user, "user_name", None),
                    receiver_user_ids=[target_membership.user_id],
                    channel_id=req.channel_id,
                    navigable=True,
                )

        return True

    async def _send_admin_assignment_notification(
        self,
        operator_user_id: int,
        target_user_id: int,
        channel_id: str,
    ) -> None:
        """Notify a channel member after being promoted from member to admin."""
        channel = await self.channel_repository.find_by_id(channel_id)
        if not channel:
            logger.warning(
                "Channel not found when sending admin assignment notification: channel_id=%s, target_user_id=%s",
                channel_id,
                target_user_id,
            )
            return

        user = await UserDao.aget_user(target_user_id)
        target_user_name = user.user_name if user else f"User {target_user_id}"

        content = [
            {
                "type": "user",
                "content": f"@{target_user_name}",
                "metadata": {"user_id": target_user_id},
            },
            {
                "type": "system_text",
                "content": CHANNEL_ADMIN_ASSIGNMENT_MESSAGE,
            },
            {
                "type": "business_url",
                "content": f"--{channel.name}",
                "metadata": {
                    "business_type": "channel_id",
                    "data": {"channel_id": channel.id},
                },
            },
        ]

        await self.message_service.send_generic_notify(
            sender=operator_user_id,
            receiver_user_ids=[target_user_id],
            content_item_list=content,
            action_code=CHANNEL_ADMIN_ASSIGNMENT_MESSAGE,
        )

    async def _send_channel_event_notification(
        self,
        *,
        action_code: str,
        operator_user_id: int,
        receiver_user_ids: list[int],
        channel_id: str,
        operator_user_name: str | None = None,
        channel_name: str | None = None,
        navigable: bool = False,
    ) -> None:
        if not self.message_service or not receiver_user_ids:
            return

        try:
            channel = None
            if channel_name is None:
                channel = await self.channel_repository.find_by_id(channel_id)
                channel_name = channel.name if channel else str(channel_id)

            await self.message_service.send_generic_notify(
                sender=operator_user_id,
                receiver_user_ids=receiver_user_ids,
                content_item_list=build_notify_content(
                    action_code=action_code,
                    target_name=channel_name,
                    business_type="channel_id",
                    business_id=channel_id,
                    actor_user_id=operator_user_id,
                    actor_user_name=operator_user_name,
                    navigable=navigable,
                ),
                action_code=action_code,
            )
        except Exception:
            logger.exception(
                "failed to send channel event notification: action_code=%s channel_id=%s",
                action_code,
                channel_id,
            )

    @staticmethod
    async def _user_can_manage_channel(user_id: int, channel_id: str) -> bool:
        return await PermissionService.check(
            user_id=user_id,
            relation="can_manage",
            object_type="channel",
            object_id=channel_id,
        )

    @staticmethod
    async def _user_can_edit_channel(user_id: int, channel_id: str) -> bool:
        return await PermissionService.check(
            user_id=user_id,
            relation="can_edit",
            object_type="channel",
            object_id=channel_id,
        )

    @staticmethod
    async def _user_can_read_channel(user_id: int, channel_id: str) -> bool:
        return await PermissionService.check(
            user_id=user_id,
            relation="can_read",
            object_type="channel",
            object_id=channel_id,
        )

    @staticmethod
    async def _authorized_channel_user_ids(channel_id: str) -> set[int]:
        permissions = await PermissionService.get_resource_permissions("channel", channel_id)
        user_ids: set[int] = set()
        for permission in permissions:
            if getattr(permission, "relation", None) not in CHANNEL_MEMBER_RELATIONS:
                continue
            include_children = getattr(permission, "include_children", None)
            user_ids.update(
                await PermissionService._affected_user_ids_for_subject(
                    getattr(permission, "subject_type", ""),
                    int(getattr(permission, "subject_id", 0) or 0),
                    True if include_children is None else bool(include_children),
                )
            )
        return user_ids

    async def remove_member(self, req: RemoveMemberRequest, login_user: UserPayload) -> bool:
        """
        Remove a member (hard delete).
        Permissions:
        - Creators can remove anyone (except themselves)
        - Admins can remove regular members
        - Admins cannot remove other admins or creators
        """
        # 1. Verify current user permissions
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=login_user.user_id
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            raise ValueError("You are not a member of this channel")

        if current_membership.user_role not in (UserRoleEnum.CREATOR, UserRoleEnum.ADMIN):
            raise ValueError("You do not have permission to remove members")

        # 2. Cannot remove yourself
        if req.user_id == login_user.user_id:
            raise ValueError("Cannot remove yourself")

        # 3. Query target member
        target_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=req.user_id
        )
        if not target_membership or target_membership.status != MembershipStatusEnum.ACTIVE:
            raise ValueError("The target user is not a member of this channel")

        # 4. Removing the creator is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Removing the creator is not allowed")

        # 5. Admins cannot remove other admins
        if current_membership.user_role == UserRoleEnum.ADMIN:
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError("Admins do not have permission to remove other admins")

        # 6. Hard delete: remove from database
        await self.space_channel_member_repository.delete(target_membership.id)
        if self.message_service and not await self._user_can_read_channel(req.user_id, req.channel_id):
            await self._send_channel_event_notification(
                action_code=CHANNEL_MEMBER_REMOVED_MESSAGE,
                operator_user_id=login_user.user_id,
                operator_user_name=getattr(login_user, "user_name", None),
                receiver_user_ids=[req.user_id],
                channel_id=req.channel_id,
                navigable=False,
            )

        return True

    async def get_channel_square(
        self, keyword: str | None, page: int, page_size: int, login_user: UserPayload
    ) -> ChannelSquarePageResponse:
        """
        Get the channel square: paginated list of all released channels with subscription status
        and subscriber count for the current user.
        - Supports fuzzy search by channel name and description
        - Unsubscribed/unapplied channels are shown first
        - Subscribed/applied channels are shown last
        - Within each group, sorted by update_time descending
        """
        # 1. Multi-table join query for channels with subscription info
        rows = await self.channel_repository.find_square_channels(
            user_id=login_user.user_id, keyword=keyword, page=page, page_size=page_size
        )

        # 2. Count total matching channels
        total = await self.channel_repository.count_square_channels(keyword=keyword)

        # 3. Map rows to response items (ES article counts + top source infos)
        result_list = await self._build_square_items(rows)

        return ChannelSquarePageResponse(data=result_list, total=total)

    async def get_recommended_channels(self, login_user: UserPayload, limit: int = 12) -> ChannelSquarePageResponse:
        """
        Home-page discovery recommendations: released PUBLIC channels sorted by
        content (article) count descending, for the empty-state carousel shown to
        users with no created/subscribed channels.

        Article count comes from Elasticsearch per channel, so it cannot be ordered
        at the DB layer: we pull a bounded candidate set of public channels, compute
        their counts in one ES batch, then sort in memory and return the top ``limit``.
        ``total`` is the number of qualifying public channels (capped at the candidate
        limit) so the frontend can fall back to the empty illustration when < 3.
        """
        rows = await self.channel_repository.find_public_recommend_channels(user_id=login_user.user_id)

        items = await self._build_square_items(rows)

        # Sort by content count desc; tie-break on subscriber count then name for stability.
        items.sort(key=lambda x: (x.article_count, x.subscriber_count, x.name), reverse=True)

        total = len(items)
        return ChannelSquarePageResponse(data=items[:limit], total=total)

    async def _build_square_items(self, rows) -> list[ChannelSquareItemResponse]:
        """
        Map channel-square repository rows
        ``(Channel, user_subscription_status, user_subscription_update_time, subscriber_count)``
        to ``ChannelSquareItemResponse`` items, preserving the input order.

        Batches the per-channel ES article-count and the top-5 source lookups to avoid
        N+1 queries. Shared by the channel square and the home-page recommendations.
        """
        if not rows:
            return []

        # F040: main article counts come from a short-TTL Redis cache; only the cache
        # *misses* go to ES (still batched into one msearch), then are written back.
        # ``article_counts`` stays a list parallel to ``rows``. Shared by the square and
        # the home-page recommendations, so both benefit from the cache.
        channels = [row[0] for row in rows]
        cached_counts = await ArticleCountCache.get_main_counts([c.id for c in channels])

        miss_indices = [i for i, c in enumerate(channels) if c.id not in cached_counts]
        miss_requests = [
            {
                "source_ids": channels[i].source_list or [],
                "filter_rules": self._extract_filter_rule_groups(channels[i], channel_type="main") or None,
                "include_article_ids": None,
            }
            for i in miss_indices
        ]
        fresh_counts = await self.article_es_service.count_articles_batch(miss_requests) if miss_requests else []
        fresh_by_index = {idx: (fresh_counts[j] if j < len(fresh_counts) else 0) for j, idx in enumerate(miss_indices)}
        await ArticleCountCache.set_main_counts({channels[i].id: fresh_by_index[i] for i in miss_indices})
        article_counts = [cached_counts.get(c.id, fresh_by_index.get(i, 0)) for i, c in enumerate(channels)]

        # Collect top 5 source IDs from all channels for the square
        all_needed_source_ids = set()
        channel_to_top_sources = {}
        for row in rows:
            channel = row[0]
            top_5_sources = (channel.source_list or [])[:5]
            channel_to_top_sources[channel.id] = top_5_sources
            all_needed_source_ids.update(top_5_sources)

        # Batch fetch all needed sources
        source_map = {}
        if all_needed_source_ids:
            sources = await self.channel_info_source_repository.find_by_ids(list(all_needed_source_ids))
            source_map = {s.id: s for s in sources}

        result_list: list[ChannelSquareItemResponse] = []
        for i, row in enumerate(rows):
            channel = row[0]  # Channel object
            user_subscription_status = row[1]
            user_subscription_update_time = row[2]
            subscriber_count = row[3]
            article_count = article_counts[i] if i < len(article_counts) else 0

            status = self._resolve_subscription_status(
                membership_status=user_subscription_status,
                update_time=user_subscription_update_time,
            )

            # Prepare source infos
            top_source_ids = channel_to_top_sources.get(channel.id, [])
            source_infos = []
            for sid in top_source_ids:
                if sid in source_map:
                    s = source_map[sid]
                    source_infos.append(
                        {
                            "id": s.id,
                            "source_name": s.source_name,
                            "source_icon": s.source_icon,
                            "source_type": s.source_type,
                            "description": s.description,
                        }
                    )

            result_list.append(
                ChannelSquareItemResponse(
                    id=channel.id,
                    name=channel.name,
                    description=channel.description,
                    visibility=channel.visibility,
                    latest_article_update_time=channel.latest_article_update_time,
                    create_time=channel.create_time,
                    update_time=channel.update_time,
                    subscription_status=status,
                    subscriber_count=subscriber_count,
                    article_count=article_count,
                    source_infos=source_infos,
                )
            )

        return result_list

    async def subscribe_channel(
        self,
        req: SubscribeChannelRequest,
        login_user: UserPayload,
        request=None,
    ) -> SubscriptionStatusEnum:
        """
        Subscribe to a channel (public or review).
        - Private channels cannot be subscribed to.
        - Public channels can be subscribed to directly.
        - Review channels require approval, so status is set to False (pending).
        """
        # 1. Verify channel existence
        channels = await self.channel_repository.find_channels_by_ids([req.channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]

        existing_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=login_user.user_id
        )
        if existing_membership and existing_membership.user_role != UserRoleEnum.MEMBER:
            return SubscriptionStatusEnum.SUBSCRIBED

        # 3. Check channel visibility
        if channel.visibility == ChannelVisibilityEnum.PRIVATE:
            raise ChannelAccessDeniedError()

        # 4. Determine subscription status based on channel visibility
        if channel.visibility == ChannelVisibilityEnum.PUBLIC:
            status = MembershipStatusEnum.ACTIVE
            return_status = SubscriptionStatusEnum.SUBSCRIBED
        elif channel.visibility == ChannelVisibilityEnum.REVIEW:
            status = MembershipStatusEnum.PENDING
            return_status = SubscriptionStatusEnum.PENDING
        else:
            raise ValueError(f"Unsupported channel visibility: {channel.visibility}")

        if existing_membership and existing_membership.status == MembershipStatusEnum.ACTIVE:
            return SubscriptionStatusEnum.SUBSCRIBED
        if (
            existing_membership
            and existing_membership.status == MembershipStatusEnum.PENDING
            and status == MembershipStatusEnum.PENDING
        ):
            return SubscriptionStatusEnum.PENDING

        if not existing_membership or existing_membership.status == MembershipStatusEnum.REJECTED:
            await QuotaService.check_quota(
                user_id=login_user.user_id,
                resource_type=QuotaResourceType.CHANNEL_SUBSCRIBE,
                tenant_id=login_user.tenant_id,
                login_user=login_user,
            )

        if existing_membership:
            existing_membership.status = status
            await self.space_channel_member_repository.update(existing_membership)
            member_row = existing_membership
        else:
            member_row = await self.space_channel_member_repository.add_member(
                business_id=req.channel_id,
                business_type=BusinessTypeEnum.CHANNEL,
                user_id=login_user.user_id,
                role=UserRoleEnum.MEMBER,
                status=status,
            )

        # Public channels activate the subscriber immediately, so mirror the
        # membership into an explicit ReBAC viewer grant. Review channels stay
        # PENDING here and are synced once their approval passes.
        if status == MembershipStatusEnum.ACTIVE:
            await self.__class__.sync_direct_channel_user_permissions(
                req.channel_id,
                login_user.user_id,
                UserRoleEnum.MEMBER,
                is_active=True,
            )

        if channel.visibility == ChannelVisibilityEnum.REVIEW:
            gate = self.approval_gate or self._build_channel_approval_gate()
            from bisheng.database.models.department import UserDepartmentDao

            primary_dept = await UserDepartmentDao.aget_user_primary_department(login_user.user_id)
            gate_result = await gate.request_or_pass(
                ApprovalGateRequest(
                    tenant_id=login_user.tenant_id,
                    scenario_code="channel_subscribe_request",
                    business_key=f"channel:{channel.id}:user:{login_user.user_id}",
                    business_resource_type="channel",
                    business_resource_id=str(channel.id),
                    business_name=channel.name,
                    applicant_user_id=login_user.user_id,
                    applicant_user_name=getattr(login_user, "user_name", str(login_user.user_id)),
                    applicant_department_id=primary_dept.department_id if primary_dept else None,
                    payload_snapshot={
                        "channel_id": str(channel.id),
                        "channel_name": channel.name,
                        "applicant_user_id": login_user.user_id,
                    },
                    ip_address=get_request_ip(request) if request else None,
                )
            )
            if gate_result.decision == ApprovalGateDecision.PASS:
                # Reuse the membership row created/updated above instead of
                # re-fetching it. The old re-fetch raced a concurrent unsubscribe
                # (returned None between create and re-fetch → the just-approved
                # access was silently dropped, no error). member_row is always set
                # by the create/update block above.
                if member_row is not None:
                    member_row.status = MembershipStatusEnum.ACTIVE
                    await self.space_channel_member_repository.update(member_row)
                else:
                    # Defensive upsert: the row vanished (concurrent unsubscribe);
                    # recreate it ACTIVE so an approved subscription is never lost.
                    await self.space_channel_member_repository.add_member(
                        business_id=req.channel_id,
                        business_type=BusinessTypeEnum.CHANNEL,
                        user_id=login_user.user_id,
                        role=UserRoleEnum.MEMBER,
                        status=MembershipStatusEnum.ACTIVE,
                    )
                await self.__class__.sync_direct_channel_user_permissions(
                    req.channel_id,
                    login_user.user_id,
                    UserRoleEnum.MEMBER,
                    is_active=True,
                )
                return SubscriptionStatusEnum.SUBSCRIBED
            if gate_result.decision == ApprovalGateDecision.PENDING and gate_result.task_ids and self.message_service:
                await self._send_channel_approval_notification(
                    channel=channel,
                    login_user=login_user,
                    instance_id=gate_result.instance_id,
                    task_ids=gate_result.task_ids,
                )

        return return_status

    def _build_channel_approval_gate(self) -> ApprovalGate:
        registry = ApprovalRegistry.with_default_presets()
        registry.register_handler(
            "channel_subscribe_request",
            ChannelSubscribeScenarioHandler(self.space_channel_member_repository),
        )
        return ApprovalGate(registry=registry)

    async def _send_channel_approval_notification(
        self,
        *,
        channel: Channel,
        login_user: UserPayload,
        instance_id: int,
        task_ids: list[int],
    ) -> None:
        from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository

        approver_user_ids: list[int] = []
        seen: set[int] = set()
        for task_id in task_ids:
            task = await ApprovalInstanceRepository.get_task(task_id)
            if task and task.approver_user_id not in seen:
                seen.add(task.approver_user_id)
                approver_user_ids.append(task.approver_user_id)
        if not approver_user_ids:
            return
        await self.message_service.send_generic_approval(
            applicant_user_id=login_user.user_id,
            applicant_user_name=getattr(login_user, "user_name", str(login_user.user_id)),
            action_code="request_channel",
            business_type="approval_instance_id",
            business_id=str(instance_id),
            business_name=channel.name,
            button_action_code="request_channel",
            receiver_user_ids=approver_user_ids,
            scenario_code="channel_subscribe_request",
        )

    async def _send_subscribe_approval_notification(
        self,
        channel: Channel,
        login_user: UserPayload,
    ) -> None:
        """
        Send approval notification to channel creator and admins when a user
        subscribes to a review-required channel.
        """
        # 1. Get channel creator and admins
        creators = await self.space_channel_member_repository.find_members_by_role(
            channel_id=channel.id,
            role=UserRoleEnum.CREATOR,
        )
        admins = await self.space_channel_member_repository.find_members_by_role(
            channel_id=channel.id,
            role=UserRoleEnum.ADMIN,
        )

        receiver_user_ids = list({m.user_id for m in creators + admins})
        if not receiver_user_ids:
            logger.warning(
                "No creator or admin found for channel %s, skipping approval notification",
                channel.id,
            )
            return

        # 2. Get applicant user name
        users = await UserDao.aget_user_by_ids([login_user.user_id])
        applicant_name = users[0].user_name if users else f"User {login_user.user_id}"

        # 3. Send the approval message
        await self.message_service.send_generic_approval(
            applicant_user_id=login_user.user_id,
            applicant_user_name=applicant_name,
            action_code="request_channel",
            business_type="channel_id",
            business_id=channel.id,
            business_name=channel.name,
            button_action_code="request_channel",
            receiver_user_ids=receiver_user_ids,
            scenario_code="channel_subscribe_request",
        )

    async def update_channel(self, channel_id: str, req: UpdateChannelRequest, login_user: UserPayload):
        """
        Update channel settings.
        Channel owner, manager, and editor can update the channel.
        """
        # 1. Verify channel existence
        channel = await self.channel_repository.find_by_id(channel_id)
        if not channel:
            raise ChannelNotFoundError()

        # 2. Verify current user can edit channel settings. Super admins are always
        # allowed; otherwise the ReBAC ``can_edit`` relation decides. ``can_edit`` is
        # satisfied by owner / manager / editor (permission pyramid), and—unlike the
        # membership table—also honours edit grants delivered through departments,
        # user groups or direct OpenFGA tuples.
        if not login_user.is_admin() and not await self._user_can_edit_channel(login_user.user_id, channel_id):
            raise ChannelPermissionDeniedError(
                msg="Only the owner, manager, or editor can update the channel information"
            )

        bisheng_information_client = await get_bisheng_information_client()

        # 3. Update channel information
        if req.name is not None:
            channel.name = req.name
        if req.description is not None:
            channel.description = req.description
        if req.is_released is not None:
            channel.is_released = req.is_released
        if req.filter_rules is not None:
            channel.filter_rules = [f.model_dump() for f in req.filter_rules]
        if req.visibility is not None:
            new_visibility = ChannelVisibilityEnum(req.visibility)
            old_visibility = channel.visibility
            if old_visibility != new_visibility:
                # When changing to PRIVATE (from PUBLIC or REVIEW), revoke every
                # non-owner permission relation so the channel is only reachable
                # by its owner(s): square subscribers, directly authorized users,
                # and department/user_group grants alike.
                if new_visibility == ChannelVisibilityEnum.PRIVATE:
                    owners = await self.space_channel_member_repository.find_members_by_role(
                        channel_id,
                        UserRoleEnum.CREATOR,
                    )
                    owner_user_ids = {owner.user_id for owner in owners}
                    # Capture active non-owner members before removal so we can
                    # notify everyone who loses access.
                    removed_user_ids = []
                    if self.message_service:
                        existing_members = await self.space_channel_member_repository.find_all(
                            business_id=channel_id,
                            business_type=BusinessTypeEnum.CHANNEL,
                        )
                        removed_user_ids = [
                            member.user_id
                            for member in existing_members
                            if member.status == MembershipStatusEnum.ACTIVE and member.user_id not in owner_user_ids
                        ]
                    # 1. Drop every non-owner membership row.
                    await self.space_channel_member_repository.remove_non_creator_members(channel_id)
                    # 2. Revoke every non-owner ReBAC relation (users, departments,
                    #    user groups) at the FGA layer.
                    try:
                        await OwnerService.delete_non_owner_resource_tuples("channel", channel_id)
                    except Exception as e:
                        logger.warning(
                            "Failed to revoke non-owner FGA tuples after PRIVATE switch for channel %s: %s",
                            channel_id,
                            e,
                        )
                    # 3. Drop their relation-model bindings so a later re-grant
                    #    cannot resurrect a stale model.
                    try:
                        from bisheng.channel.domain.services.channel_authorization_service import (
                            ChannelAuthorizationService,
                        )

                        await ChannelAuthorizationService.clear_non_owner_bindings(channel_id)
                    except Exception as e:
                        logger.warning(
                            "Failed to clear non-owner relation-model bindings after PRIVATE switch for channel %s: %s",
                            channel_id,
                            e,
                        )
                    # 4. Re-assert owner FGA tuples defensively.
                    try:
                        for owner in owners:
                            await OwnerService.write_owner_tuple(owner.user_id, "channel", channel_id)
                    except Exception as e:
                        logger.warning(
                            "Failed to ensure owner FGA tuples after PRIVATE switch for channel %s: %s", channel_id, e
                        )
                    if removed_user_ids and self.message_service:
                        final_removed_user_ids = []
                        for user_id in removed_user_ids:
                            if not await self._user_can_read_channel(user_id, channel_id):
                                final_removed_user_ids.append(user_id)
                        await self._send_channel_event_notification(
                            action_code=CHANNEL_MADE_PRIVATE_MESSAGE,
                            operator_user_id=login_user.user_id,
                            operator_user_name=getattr(login_user, "user_name", None),
                            receiver_user_ids=final_removed_user_ids,
                            channel_id=channel_id,
                            channel_name=channel.name,
                            navigable=False,
                        )
                # When changing from REVIEW to PUBLIC, activate pending members and approve their messages
                elif old_visibility == ChannelVisibilityEnum.REVIEW and new_visibility == ChannelVisibilityEnum.PUBLIC:
                    activated_members = await self.space_channel_member_repository.activate_pending_members(channel_id)
                    if activated_members:
                        logger.info(
                            "Activated %d pending members for channel_id=%s after visibility change from REVIEW to PUBLIC",
                            len(activated_members),
                            channel_id,
                        )
                        # Mirror the newly-activated members into explicit ReBAC grants.
                        for member in activated_members:
                            await self.__class__.sync_direct_channel_user_permissions(
                                channel_id,
                                member.user_id,
                                member.user_role,
                                is_active=True,
                            )
                    await self.space_channel_member_repository.remove_rejected_members(channel_id)
                    if self.message_service:
                        await self.message_service.batch_approve_channel_subscription_messages(
                            channel_id=channel_id,
                            operator_user_id=login_user.user_id,
                        )
            channel.visibility = new_visibility

        # Track if source_list changed for updating latest_article_update_time
        source_list_changed = False
        if req.source_list is not None:
            # Calculate the difference between old and new source lists to minimize calls to bisheng_information_client
            old_sources = set(channel.source_list or [])
            new_sources = set(req.source_list)
            to_add_sources = list(new_sources - old_sources)
            to_remove_sources = list(old_sources - new_sources)

            # Mark as changed if there are any additions or removals
            if to_add_sources or to_remove_sources:
                source_list_changed = True

            if to_add_sources:
                # Subscribe only sources not already subscribed (missing from
                # channel_info_source). Already-subscribed sources are skipped.
                existing_add = await self.channel_info_source_repository.find_by_ids(to_add_sources)
                existing_add_ids = {source.id for source in existing_add}
                missing_add = [sid for sid in to_add_sources if sid not in existing_add_ids]
                if missing_add:
                    await bisheng_information_client.subscribe_information_source(missing_add)
            # Removed sources are NOT unsubscribed here: unsubscription is deferred to
            # the daily reconcile, which unsubscribes a source only once no channel
            # references it (avoids over-unsubscribing sources shared by other channels).

            channel.source_list = req.source_list

        channel = await self.channel_repository.update(channel)

        # Update latest_article_update_time if source_list changed
        if source_list_changed:
            await self.update_channels_latest_article_time([channel])

        if channel.source_list:
            # Sync information sources to local database
            existing_sources = await self.channel_info_source_repository.find_by_ids(channel.source_list)
            existing_source_ids = {source.id for source in existing_sources}
            missing_source_ids = [sid for sid in channel.source_list if sid not in existing_source_ids]

            new_channel_info_sources = await self._sync_channel_info_source_metadata(
                bisheng_information_client, missing_source_ids
            )
            if new_channel_info_sources:
                from bisheng.worker.information.article import sync_information_article

                for one in new_channel_info_sources:
                    # Sync articles for the new information source one hour later
                    exec_time = datetime.now() + timedelta(hours=1)
                    sync_information_article.apply_async(args=(one.id,), eta=exec_time)

        # Replace knowledge-sync config atomically if caller provided one.
        if req.knowledge_sync is not None:
            await self._save_knowledge_sync(
                channel_id=channel.id,
                cfg=req.knowledge_sync,
                user_id=login_user.user_id,
            )

        return channel

    async def get_channel_detail(self, channel_id: str, login_user: UserPayload) -> ChannelDetailResponse:
        """
        Get channel detailed information including creator, subscriber count, and article count.
        """
        # 1. Verify channel existence
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]

        # 2. Verify current user permission.
        # F040: a single ``find_membership_split`` lookup returns both
        # ``current_membership`` (highest-rank ACTIVE row → permission gating) and
        # ``status_membership`` (highest-rank row of any status → displayed
        # subscription status), replacing the old two-query path. Deriving both
        # from one result set is exactly equivalent AND avoids the
        # collapse-to-one-row bug where a higher-ranked PENDING/REJECTED row
        # (multi-grant model) would mask an ACTIVE membership.
        current_membership, status_membership = await self.space_channel_member_repository.find_membership_split(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id,
        )
        # F040: build the F037 shared ReBAC context once and pass it in, instead of
        # letting ``_get_channel_permission_ids`` re-derive bindings/models/subject
        # strings inline on every detail request.
        permission_context = await self._build_channel_permission_context(login_user)
        permission_ids = await self._get_channel_permission_ids(
            channel_id,
            login_user,
            current_membership,
            context=permission_context,
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            # If private, only members can view unless special requirement
            if channel.visibility == ChannelVisibilityEnum.PRIVATE and "view_channel" not in permission_ids:
                raise ChannelAccessDeniedError(msg="You do not have permission to view this channel")

        # 3. Get Creator Name
        creators = await self.space_channel_member_repository.find_members_by_role(
            channel_id=channel_id, role=UserRoleEnum.CREATOR
        )
        creator_name = "Unknown"
        if creators:
            creator_user_id = creators[0].user_id
            users = await UserDao.aget_user_by_ids([creator_user_id])
            if users:
                creator_name = users[0].user_name

        # 4. Get Subscriber Count
        subscriber_count = await self.space_channel_member_repository.count_channel_members(channel_id=channel_id)

        # 5. Get Article Count — F040: served from a short-TTL Redis cache (the main
        # count is user-independent). On miss / Redis down, fall back to a live ES
        # count and write it back. ``None`` means miss (a cached 0 is a valid hit).
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")

        article_count = await ArticleCountCache.get_main_count(channel_id)
        if article_count is None:
            article_count = await self.article_es_service.count_articles(
                source_ids=channel.source_list,
                filter_rules=main_rule_groups if main_rule_groups else None,
            )
            await ArticleCountCache.set_main_count(channel_id, article_count)

        # 5b. F040: per-sub-channel unread counts are NO LONGER computed here — they
        # are the dominant per-user ES cost and the preview drawer never shows them.
        # In-channel views fetch them lazily via GET /channel/manager/{id}/unread-counts.

        # Complete info source list
        source_infos = []
        if channel.source_list:
            sources = await self.channel_info_source_repository.find_by_ids(channel.source_list)
            source_map = {s.id: s for s in sources}
            for sid in channel.source_list:
                if sid in source_map:
                    s = source_map[sid]
                    source_infos.append(
                        {
                            "id": s.id,
                            "source_name": s.source_name,
                            "source_icon": s.source_icon,
                            "source_type": s.source_type,
                            "description": s.description,
                        }
                    )
                else:
                    source_infos.append(
                        {"id": sid, "source_name": "Unknown", "source_icon": "", "source_type": "", "description": ""}
                    )

        # Determine subscription status. ``current_membership`` is ACTIVE-only (it
        # gates permissions), but the subscribe button must also reflect PENDING /
        # REJECTED applications — the same states the channel square shows. F040:
        # ``status_membership`` (the highest-rank row of any status from the split
        # lookup above) carries that PENDING/REJECTED state, so use it directly.
        subscription_status = self._resolve_membership_subscription_status(status_membership)

        # Knowledge-sync config — only returned for the channel creator since
        # the feature is creator-only (Module D). Members don't need to see it.
        knowledge_sync_cfg: KnowledgeSyncConfig | None = None
        is_creator = (
            current_membership is not None and resolve_channel_relation(current_membership) == ChannelRelationEnum.OWNER
        )
        if is_creator:
            knowledge_sync_cfg = await self._load_knowledge_sync(channel.id)

        relation = _effective_relation_value(permission_ids, current_membership)

        return ChannelDetailResponse(
            id=channel.id,
            name=channel.name,
            description=channel.description,
            source_infos=source_infos,
            visibility=channel.visibility,
            filter_rules=channel.filter_rules or [],
            is_released=channel.is_released,
            latest_article_update_time=channel.latest_article_update_time,
            create_time=channel.create_time,
            creator_name=creator_name,
            subscriber_count=subscriber_count,
            article_count=article_count,
            subscription_status=subscription_status,
            relation=relation,
            permission_ids=_sorted_channel_permission_ids(permission_ids),
            knowledge_sync=knowledge_sync_cfg,
        )

    # ------------------------------------------------------------------ #
    # Knowledge-space sync helpers (v2.5 Module D).
    # The channel create/update endpoints accept an optional `knowledge_sync`
    # field which we persist atomically alongside the channel itself. On read,
    # `get_channel_detail` re-hydrates the same shape for the creator's UI.
    # ------------------------------------------------------------------ #

    async def _save_knowledge_sync(
        self,
        channel_id: str,
        cfg: KnowledgeSyncConfig,
        user_id: int,
    ) -> None:
        """Replace every sync row for `channel_id` with the rows derived from `cfg`.

        One row per (channel, sub_channel_name?, space_id + folder_id).
        When a scope's `enabled` flag is False we still persist the rows but
        mark them `is_enabled=False` so the worker skips them; dropping them
        entirely would lose the user's selected spaces once they flip the
        switch back on.
        """
        # TC-037 defence-in-depth: the UI restricts the picker to spaces the
        # current user created, but the server must not trust the client —
        # reject any binding whose space is not owned by `user_id`.
        referenced_ids = {s.knowledge_space_id for s in cfg.main.spaces}
        for sub in cfg.subs:
            referenced_ids.update(s.knowledge_space_id for s in sub.spaces)
        if referenced_ids:
            owned_members = await SpaceChannelMemberDao.async_get_user_created_members(int(user_id))
            owned_ids = {m.business_id for m in owned_members}
            if not referenced_ids.issubset(owned_ids):
                raise SpacePermissionDeniedError()

        rows: list[ChannelKnowledgeSync] = []

        # main-channel scope
        for space in cfg.main.spaces:
            rows.append(
                ChannelKnowledgeSync(
                    channel_id=channel_id,
                    sub_channel_name=None,
                    knowledge_space_id=space.knowledge_space_id,
                    folder_id=space.folder_id,
                    folder_path=space.folder_path,
                    is_enabled=cfg.main.enabled,
                    user_id=int(user_id),
                )
            )

        # sub-channel scopes
        for sub in cfg.subs:
            if not sub.sub_channel_name:
                continue
            for space in sub.spaces:
                rows.append(
                    ChannelKnowledgeSync(
                        channel_id=channel_id,
                        sub_channel_name=sub.sub_channel_name,
                        knowledge_space_id=space.knowledge_space_id,
                        folder_id=space.folder_id,
                        folder_path=space.folder_path,
                        is_enabled=sub.enabled,
                        user_id=int(user_id),
                    )
                )

        await ChannelKnowledgeSyncDao.areplace_for_channel(channel_id, rows)

    async def _load_knowledge_sync(
        self,
        channel_id: str,
    ) -> KnowledgeSyncConfig:
        """Build a KnowledgeSyncConfig from the stored rows, plus display
        names for the bound knowledge spaces."""
        rows = await ChannelKnowledgeSyncDao.alist_by_channel_id(channel_id)
        # Sort by create_time for stable, creation-order display (requirement 3.1.1).
        rows.sort(key=lambda r: r.create_time)

        # Resolve knowledge-space display names for the UI.
        space_name_by_id: dict[str, str] = {}
        numeric_ids = [
            int(r.knowledge_space_id) for r in rows if r.knowledge_space_id and str(r.knowledge_space_id).isdigit()
        ]
        if numeric_ids:
            from sqlmodel import select as _select

            from bisheng.core.database import get_async_db_session
            from bisheng.knowledge.domain.models.knowledge import Knowledge

            async with get_async_db_session() as session:
                q = _select(Knowledge).where(Knowledge.id.in_(numeric_ids))
                for kb in (await session.exec(q)).all():
                    space_name_by_id[str(kb.id)] = kb.name

        # Defensive filter: drop bindings whose target space or folder no longer
        # exists. There is a race window between space/folder deletion and
        # channel_knowledge_sync cleanup; this keeps the UI clean if a row leaks.
        existing_space_ids = set(space_name_by_id.keys())
        rows = [
            r
            for r in rows
            if r.knowledge_space_id
            and str(r.knowledge_space_id).isdigit()
            and str(r.knowledge_space_id) in existing_space_ids
        ]
        folder_ids_to_check = {int(r.folder_id) for r in rows if r.folder_id is not None and str(r.folder_id).isdigit()}
        if folder_ids_to_check:
            from sqlmodel import select as _select

            from bisheng.core.database import get_async_db_session
            from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

            existing_folder_ids: set = set()
            async with get_async_db_session() as session:
                q = _select(KnowledgeFile.id).where(KnowledgeFile.id.in_(list(folder_ids_to_check)))
                for row in (await session.exec(q)).all():
                    fid = row[0] if isinstance(row, tuple) else row
                    existing_folder_ids.add(int(fid))
            rows = [r for r in rows if r.folder_id is None or int(r.folder_id) in existing_folder_ids]

        def _to_item(r: ChannelKnowledgeSync) -> KnowledgeSyncSpaceItem:
            return KnowledgeSyncSpaceItem(
                knowledge_space_id=str(r.knowledge_space_id),
                knowledge_space_name=space_name_by_id.get(str(r.knowledge_space_id), ""),
                folder_id=r.folder_id,
                folder_path=r.folder_path,
            )

        main_rows = [r for r in rows if not r.sub_channel_name]
        sub_rows_by_name: dict[str, list[ChannelKnowledgeSync]] = {}
        for r in rows:
            if r.sub_channel_name:
                sub_rows_by_name.setdefault(r.sub_channel_name, []).append(r)

        main_cfg = KnowledgeSyncMainConfig(
            enabled=bool(main_rows) and all(r.is_enabled for r in main_rows),
            spaces=[_to_item(r) for r in main_rows],
        )
        subs: list[KnowledgeSyncSubConfig] = []
        for name, rlist in sub_rows_by_name.items():
            subs.append(
                KnowledgeSyncSubConfig(
                    sub_channel_name=name,
                    enabled=bool(rlist) and all(r.is_enabled for r in rlist),
                    spaces=[_to_item(r) for r in rlist],
                )
            )
        return KnowledgeSyncConfig(main=main_cfg, subs=subs)

    async def dismiss_channel(self, channel_id: str, login_user: UserPayload, request=None):
        """
        Dismiss a channel:
        - Must be creator
        - Delete all user relationships
        - Delete channel
        - Information sources are unsubscribed lazily by the daily reconcile, not here
        """
        # 1. Verify channel existence
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]

        # 2. Verify current user may dismiss the channel: a super admin, the creator,
        #    or a user granted the `delete_channel` fine-grained permission via ReBAC.
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=login_user.user_id
        )
        is_active_creator = (
            current_membership is not None
            and current_membership.status == MembershipStatusEnum.ACTIVE
            and current_membership.user_role == UserRoleEnum.CREATOR
        )
        if not login_user.is_admin() and not is_active_creator:
            permission_ids = await self._get_channel_permission_ids(channel_id, login_user, current_membership)
            if "delete_channel" not in permission_ids:
                raise ChannelPermissionDeniedError(
                    msg="Only the creator or a user with delete permission can dismiss the channel"
                )

        # 3. Delete all user relationships
        members = await self.space_channel_member_repository.find_all(
            business_id=channel_id, business_type=BusinessTypeEnum.CHANNEL
        )
        original_member_ids = {member.user_id for member in members if member.status == MembershipStatusEnum.ACTIVE}
        original_member_ids.update(await self._authorized_channel_user_ids(channel_id))
        await self._send_channel_event_notification(
            action_code=CHANNEL_DISMISSED_MESSAGE,
            operator_user_id=login_user.user_id,
            operator_user_name=getattr(login_user, "user_name", None),
            receiver_user_ids=sorted(original_member_ids),
            channel_id=channel_id,
            channel_name=channel.name,
            navigable=False,
        )
        for member in members:
            await self.space_channel_member_repository.delete(member.id)

        # F008: Delete all FGA tuples for this channel
        try:
            await OwnerService.delete_resource_tuples("channel", channel_id)
        except Exception as e:
            logger.warning("Failed to delete FGA tuples for channel %s: %s", channel_id, e)

        # 4. Delete channel
        await self.channel_repository.delete(channel_id)

        # 5. Information sources are NOT unsubscribed here. Unsubscription is deferred to
        #    the daily reconcile, which unsubscribes a source only once no channel
        #    references it — dismissing one channel must not unsubscribe a source still
        #    used by other channels.

        # Audit log
        from bisheng.api.services.audit_log import AuditLogService

        if request:
            await AuditLogService.delete_channel(login_user, get_request_ip(request), channel_id, channel.name)

        return True

    async def unsubscribe_channel(self, channel_id: str, login_user: UserPayload):
        """
        Unsubscribe from a channel:
        - Remove current user and channel relationship
        """
        # 1. Verify current user is a member
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id, business_type=BusinessTypeEnum.CHANNEL, user_id=login_user.user_id
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            model_organization_subject_types = await self._get_channel_organization_grant_subject_types(
                channel_id,
                login_user,
            )
            if model_organization_subject_types:
                raise ChannelOrganizationGrantUnsubscribeDeniedError(
                    blocked_by=sorted(model_organization_subject_types),
                )
            # A member-management direct USER authorization grants a ReBAC relation + UI
            # binding but no membership row (F026 keeps authorization separate from
            # membership), yet the channel still appears in the user's followed list, which
            # includes ReBAC-accessible channels. Mirror knowledge_space.unsubscribe_space:
            # revoke the direct grant instead of failing with "not subscribed".
            if await self._has_direct_channel_user_grant(channel_id, login_user.user_id):
                await self.__class__.sync_direct_channel_user_permissions(
                    channel_id,
                    login_user.user_id,
                    None,
                    is_active=False,
                )
                return True
            raise ValueError("You are not subscribed to this channel")

        sources = await self.space_channel_member_repository.find_channel_membership_sources(
            channel_id,
            login_user.user_id,
        )
        if not sources:
            sources = [current_membership]

        direct_sources = [source for source in sources if _is_direct_channel_source(source, login_user.user_id)]
        organization_sources = [source for source in sources if _is_organization_channel_source(source)]

        member_organization_subject_types = {
            source.grant_subject_type for source in organization_sources if source.grant_subject_type
        }
        if member_organization_subject_types:
            raise ChannelOrganizationGrantUnsubscribeDeniedError(
                blocked_by=sorted(member_organization_subject_types),
            )

        model_organization_subject_types = await self._get_channel_organization_grant_subject_types(
            channel_id,
            login_user,
        )
        blocked_by = sorted(model_organization_subject_types)
        if blocked_by:
            raise ChannelOrganizationGrantUnsubscribeDeniedError(blocked_by=blocked_by)

        targets = direct_sources or [current_membership]
        for source in targets:
            await self._remove_channel_direct_source(channel_id, source)

        return True

    @staticmethod
    def _is_direct_channel_user_binding(binding: dict, channel_id: str, user_id: int) -> bool:
        return (
            binding.get("resource_type") == "channel"
            and str(binding.get("resource_id")) == str(channel_id)
            and binding.get("subject_type") == "user"
            and str(binding.get("subject_id")) == str(user_id)
        )

    async def _has_direct_channel_user_grant(self, channel_id: str, user_id: int) -> bool:
        """Whether the user holds a direct 'user' authorization binding on the channel.

        Detects member-management grants that exist only as ReBAC tuples + a UI binding
        (no membership row), so unsubscribe can revoke them like a self-subscribe.
        """
        from bisheng.permission.api.endpoints.resource_permission import _get_bindings

        bindings = await _get_bindings()
        return any(self._is_direct_channel_user_binding(binding, channel_id, user_id) for binding in bindings)

    async def _directly_granted_channel_ids(self, user_id: int) -> list[str]:
        """Channel ids the user holds a direct 'user' authorization binding on.

        Used to recover an admin's explicitly-authorized channels for the followed list,
        since ``list_accessible_ids`` returns None (can-read-all) for admins and would
        otherwise hide channels the admin was granted but is not a member of.
        """
        from bisheng.permission.api.endpoints.resource_permission import _get_bindings

        bindings = await _get_bindings()
        return [
            str(binding.get("resource_id"))
            for binding in bindings
            if binding.get("resource_type") == "channel"
            and binding.get("subject_type") == "user"
            and str(binding.get("subject_id")) == str(user_id)
        ]

    @classmethod
    async def sync_direct_channel_user_permissions(
        cls,
        channel_id: str,
        user_id: int,
        user_role: UserRoleEnum | None,
        *,
        is_active: bool,
    ) -> None:
        """Keep direct channel memberships and ReBAC grants in sync.

        Active members receive a single explicit relation grant (viewer/editor/manager)
        plus the matching UI binding so they surface in the channel authorization list.
        The owner relation is never mirrored here; it is managed by OwnerService.
        """
        from bisheng.permission.api.endpoints.resource_permission import (
            _binding_key_with_scope,
            _get_bindings,
            _save_bindings,
        )

        desired_relation: str | None = None
        if is_active and user_role is not None:
            relation_enum = CHANNEL_ROLE_TO_RELATION.get(UserRoleEnum(user_role))
            desired_relation = relation_enum.value if relation_enum else None
            if desired_relation == ChannelRelationEnum.OWNER.value:
                desired_relation = None

        relations_to_revoke = {
            ChannelRelationEnum.VIEWER.value,
            ChannelRelationEnum.EDITOR.value,
            ChannelRelationEnum.MANAGER.value,
        }
        if desired_relation:
            relations_to_revoke.discard(desired_relation)

        revokes = [
            AuthorizeRevokeItem(
                subject_type="user",
                subject_id=int(user_id),
                relation=relation,
                include_children=False,
            )
            for relation in sorted(relations_to_revoke)
        ]
        grants = []
        if desired_relation:
            grants.append(
                AuthorizeGrantItem(
                    subject_type="user",
                    subject_id=int(user_id),
                    relation=desired_relation,
                    include_children=False,
                    model_id=desired_relation,
                )
            )

        await PermissionService.authorize(
            object_type="channel",
            object_id=str(channel_id),
            grants=grants,
            revokes=revokes,
            enforce_fga_success=True,
        )

        bindings = await _get_bindings()
        updated_bindings = [
            binding for binding in bindings if not cls._is_direct_channel_user_binding(binding, channel_id, user_id)
        ]
        if desired_relation:
            key = _binding_key_with_scope(
                "channel",
                str(channel_id),
                "user",
                int(user_id),
                desired_relation,
                None,
            )
            updated_bindings.append(
                {
                    "key": key,
                    "resource_type": "channel",
                    "resource_id": str(channel_id),
                    "subject_type": "user",
                    "subject_id": int(user_id),
                    "relation": desired_relation,
                    "include_children": None,
                    "model_id": desired_relation,
                }
            )
        await _save_bindings(updated_bindings)

    async def _remove_channel_direct_source(self, channel_id: str, source) -> None:
        # Subscribe mirrors a direct membership into an explicit ReBAC grant
        # (viewer/editor/manager) plus a UI binding via
        # sync_direct_channel_user_permissions. Unsubscribe must tear both down,
        # otherwise the user keeps channel access through ReBAC and still surfaces
        # in the authorization list after the membership row is deleted. This
        # covers self-subscribe (grant_subject_type None/'self') and admin-direct
        # user grants (grant_subject_type 'user') alike.
        revoke_user_id = getattr(source, "grant_subject_id", None) or getattr(source, "user_id", None)
        if revoke_user_id is not None:
            await self.__class__.sync_direct_channel_user_permissions(
                channel_id,
                int(revoke_user_id),
                None,
                is_active=False,
            )

        binding_key = getattr(source, "grant_binding_key", None)
        if binding_key:
            await self.space_channel_member_repository.delete_channel_membership_source(channel_id, binding_key)
            return
        await self.space_channel_member_repository.delete(source.id)

    async def search_channel_articles(
        self,
        channel_id: str,
        keyword: str | None = None,
        source_ids: list[str] | None = None,
        sub_channel_name: str | None = None,
        page: int = 1,
        page_size: int = 20,
        login_user: UserPayload = None,
        only_unread: bool = False,
    ) -> ArticleSearchPageResponse:
        """
        Paginated search for articles in a channel.

        1. Query channel by channel_id to get source_list and filter_rules
        2. Determine if a sub-channel is specified, apply corresponding filter rules
        3. Build ES query: info source filter + filter rules + keyword search + highlight + sort + pagination

        Args:
            channel_id: Channel ID
            keyword: Search keyword (title, content, source ID)
            source_ids: Info source ID list specified by frontend (must be a subset of channel source_list)
            sub_channel_name: Sub-channel name, if specified use the corresponding sub-channel's filter rules
            page: Page number
            page_size: Page size
            login_user: Current logged-in user

        Returns:
            ArticleSearchPageResponse
        """
        # 1. Query channel info
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ValueError("Channel not found")
        channel = channels[0]

        # 2. Determine info source list
        channel_source_ids = channel.source_list or []
        if source_ids:
            # Info sources from frontend must be a subset of channel info sources
            effective_source_ids = [sid for sid in source_ids if sid in channel_source_ids]
            if not effective_source_ids:
                # None of the provided info sources are in the channel, return empty result
                return ArticleSearchPageResponse(data=[], total=0, page=page, page_size=page_size)
        else:
            effective_source_ids = channel_source_ids
        if not effective_source_ids:
            return ArticleSearchPageResponse(data=[], total=0, page=page, page_size=page_size)

        # 3. Parse filter rules
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
        sub_rule_groups = []
        if sub_channel_name:
            sub_rule_groups = self._extract_filter_rule_groups(
                channel,
                channel_type="sub",
                sub_channel_name=sub_channel_name,
            )

        if sub_rule_groups:
            effective_rule_groups = [*main_rule_groups, *sub_rule_groups]
        else:
            effective_rule_groups = main_rule_groups

        # 4. Get read article ID list
        read_article_ids = []
        if login_user and self.article_read_repository:
            read_article_ids = await self.article_read_repository.find_article_ids_by_user_and_sources(
                user_id=login_user.user_id, source_ids=effective_source_ids
            )

        # 5. Call ArticleEsService to search
        exclude_article_ids = read_article_ids if only_unread else None
        article_search_response = await self.article_es_service.search_articles(
            source_ids=effective_source_ids,
            keyword=keyword,
            filter_rules=effective_rule_groups if effective_rule_groups else None,
            page=page,
            page_size=page_size,
            exclude_article_ids=exclude_article_ids,
            include_content=True,
        )

        source_ids_in_result = [item.source_id for item in article_search_response.data]

        # Batch query info source info
        source_info_map = {}
        if source_ids_in_result:
            sources = await self.channel_info_source_repository.find_by_ids(source_ids_in_result)
            for s in sources:
                source_info_map[s.id] = {
                    "id": s.id,
                    "source_name": s.source_name,
                    "source_icon": s.source_icon,
                    "source_type": s.source_type,
                    "description": s.description,
                }

        read_ids_set = set(read_article_ids)
        for item in article_search_response.data:
            if item.source_id in source_info_map:
                item.source_info = source_info_map[item.source_id]
            # Set read status
            item.is_read = item.doc_id in read_ids_set

        await self.apply_article_sensitive_reviews(article_search_response.data, login_user)

        return article_search_response

    async def get_article_detail(self, article_id: str, channel_id: str, login_user: UserPayload):
        """
        Get article details by ID and record reading status.
        """
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]

        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id,
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            # Non-members may still view when granted `view_channel` via ReBAC, or
            # when they are a super/tenant admin (resolved to owner-equivalent
            # permissions). Mirrors knowledge-space APPROVAL access, where admins /
            # ReBAC-granted users read content without subscribing. find_membership
            # is ACTIVE-only for channels, so a PENDING applicant resolves to None
            # here and gains no membership-derived permission — the approval gate
            # stays intact.
            permission_ids = await self._get_channel_permission_ids(channel_id, login_user, current_membership)
            if "view_channel" not in permission_ids:
                raise ChannelAccessDeniedError(msg="You do not have permission to view this channel")

        # 1. Fetch article from ES
        article = await self.article_es_service.get_article(article_id)
        if not article:
            raise ValueError("Article not found")

        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
        matched_count = await self.article_es_service.count_articles(
            source_ids=channel.source_list or [],
            filter_rules=main_rule_groups if main_rule_groups else None,
            include_article_ids=[article_id],
        )
        if matched_count == 0:
            raise ChannelAccessDeniedError(msg="You do not have permission to view this article")

        await self.ensure_article_sensitive_view_allowed(article, login_user)

        # 2. Check read record
        if self.article_read_repository:
            read_record = await self.article_read_repository.find_by_user_and_article(
                user_id=login_user.user_id, article_id=article_id
            )

            # 3. Add read record if not exists
            if not read_record:
                new_record = ArticleReadRecord(
                    article_id=article_id,
                    user_id=login_user.user_id,
                    source_id=article.source_id,
                )
                await self.article_read_repository.save(new_record)

        if article.source_id:
            source = await self.channel_info_source_repository.find_by_id(article.source_id)
            if source:
                article.source_info = {
                    "id": source.id,
                    "source_name": source.source_name,
                    "source_icon": source.source_icon,
                    "source_type": source.source_type,
                    "description": source.description,
                }

        return self._to_article_detail_response(article)

    # ──────────────────────────────────────────
    #  Channel latest article update time methods
    # ──────────────────────────────────────────

    @staticmethod
    def _extract_filter_rule_groups(
        channel: Channel,
        channel_type: str = "main",
        sub_channel_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract filter rule groups while preserving top-level grouping semantics."""
        filter_rules_raw = channel.filter_rules or []
        matched_groups: list[dict[str, Any]] = []
        legacy_main_rules: list[dict[str, Any]] = []

        for filter_rule in filter_rules_raw:
            if filter_rule.get("type") in {"single", "multi"}:
                if channel_type == "main":
                    legacy_main_rules.append(filter_rule)
                continue

            current_channel_type = filter_rule.get("channel_type", "main")
            if current_channel_type != channel_type:
                continue

            if channel_type == "sub":
                if not sub_channel_name or filter_rule.get("name") != sub_channel_name:
                    continue

            matched_groups.append(filter_rule)

        if legacy_main_rules and channel_type == "main":
            matched_groups.append(
                {
                    "relation": "or",
                    "rules": legacy_main_rules,
                    "channel_type": "main",
                }
            )

        return matched_groups

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        """Normalize datetime values before comparison and persistence."""
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    async def _get_channel_latest_article_create_time(self, channel: Channel) -> datetime | None:
        """Get the latest article create_time for a channel under main filter rules (async version)."""
        from bisheng.channel.domain.es.article_index import ARTICLE_INDEX_NAME
        from bisheng.core.search.elasticsearch.manager import get_es_connection

        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
        query = self.article_es_service._build_count_query(
            source_ids=channel.source_list or [],
            filter_rules=main_rule_groups or None,
        )
        if query is None:
            return None

        client = await get_es_connection()
        body = {
            "size": 1,
            "query": query,
            "sort": [{"publish_time": {"order": "desc"}}],
            "_source": ["publish_time"],
        }
        response = await client.search(index=ARTICLE_INDEX_NAME, body=body)
        hits = response["hits"]["hits"]
        if not hits:
            return None

        latest_time = hits[0]["_source"].get("publish_time")
        if not latest_time:
            return None

        return self._normalize_datetime(datetime.fromisoformat(latest_time))

    async def update_channels_latest_article_time(self, channels: list[Channel]) -> int:
        """
        Update latest_article_update_time for the given channels (async version).

        Args:
            channels: List of channels to update

        Returns:
            Number of channels updated
        """
        if not channels:
            return 0

        updated_count = 0
        for channel in channels:
            try:
                latest_article_create_time = await self._get_channel_latest_article_create_time(channel)
            except Exception as exc:
                logger.exception(f"Failed to query latest article create_time for channel {channel.id}: {exc}")
                continue

            channel.latest_article_update_time = latest_article_create_time
            await self.channel_repository.update(channel)
            updated_count += 1

        return updated_count

    @staticmethod
    def update_channels_latest_article_time_sync(channels: list[Channel]) -> int:
        """
        Update latest_article_update_time for the given channels (sync version).

        This method is designed to be called from sync contexts like Celery workers.

        Args:
            channels: List of channels to update

        Returns:
            Number of channels updated
        """
        from bisheng.channel.domain.es.article_index import ARTICLE_INDEX_NAME
        from bisheng.core.database import get_sync_db_session
        from bisheng.core.search.elasticsearch.manager import get_es_connection_sync

        if not channels:
            return 0

        article_service = ArticleEsService()
        updated_count = 0

        update_channels = []
        for channel in channels:
            try:
                # Get latest article create_time
                main_rule_groups = ChannelService._extract_filter_rule_groups(channel, channel_type="main")
                query = article_service._build_count_query(
                    source_ids=channel.source_list or [],
                    filter_rules=main_rule_groups or None,
                )
                if query is None:
                    # No valid query (empty source_list or no filter rules), clear the time
                    channel.latest_article_update_time = None
                    update_channels.append(channel)
                    updated_count += 1
                    continue

                client = get_es_connection_sync()
                body = {
                    "size": 1,
                    "query": query,
                    "sort": [{"publish_time": {"order": "desc"}}],
                    "_source": ["publish_time"],
                }
                response = client.search(index=ARTICLE_INDEX_NAME, body=body)
                hits = response["hits"]["hits"]
                if not hits:
                    # No articles found, clear the time
                    channel.latest_article_update_time = None
                    update_channels.append(channel)
                    updated_count += 1
                    continue

                latest_publish_time = hits[0]["_source"].get("publish_time")
                if not latest_publish_time:
                    channel.latest_article_update_time = None
                    update_channels.append(channel)
                    updated_count += 1
                    continue

                latest_article_time = ChannelService._normalize_datetime(datetime.fromisoformat(latest_publish_time))
                channel.latest_article_update_time = latest_article_time
                update_channels.append(channel)
                updated_count += 1

            except Exception as exc:
                logger.exception(f"Failed to update latest_article_update_time for channel {channel.id}: {exc}")
                continue

        if update_channels:
            with get_sync_db_session() as session:
                channel_repository = ChannelRepositoryImpl(session=session)
                # Batch update channels in the database using UPDATE statements
                channel_repository.update_channel_latest_article_update_time(update_channels)
        return updated_count

    # ──────────────────────────────────────────
    #  Add articles to knowledge space
    # ──────────────────────────────────────────

    @staticmethod
    def _sanitize_file_name(title: str) -> str:
        """Remove or replace characters that are invalid in file names."""
        invalid_chars = '/\\:*?"<>|\0'
        for ch in invalid_chars:
            title = title.replace(ch, "_")
        return title.strip()[:200]

    async def add_articles_to_knowledge_space(
        self,
        req: AddArticlesToKnowledgeSpaceRequest,
        login_user: UserPayload,
        request: "Request",
    ) -> list[dict]:
        """Add channel articles to a knowledge space.

        1. Validate articles exist in ES.
        2. Check write permission on the target knowledge space.
        3. Upload article content as .md and content_html as .html to minio.
        4. Call KnowledgeSpaceService.add_file to import into the space.
        5. Update preview_file_object_name for successfully created files.
        """
        # 1. Fetch all articles from ES and validate
        articles = []
        for article_id in req.article_ids:
            article = await self.article_es_service.get_article(article_id)
            if not article:
                if req.skip_missing_and_duplicates:
                    logger.warning(f"add_articles_to_knowledge_space: skipping missing article {article_id}")
                    continue
                raise ValueError(f"Article not found: {article_id}")
            await self.ensure_article_sensitive_view_allowed(article, login_user)
            articles.append(article)
        if not articles:
            # Nothing to do (all were missing and we're in skip-mode).
            return []

        # 2. Check write permission before uploading to minio
        role = await SpaceChannelMemberDao.async_get_active_member_role(req.knowledge_id, login_user.user_id)
        _WRITE_ROLES = {UserRoleEnum.CREATOR, UserRoleEnum.ADMIN}
        if role not in _WRITE_ROLES:
            raise SpacePermissionDeniedError()

        # 3. Upload articles to minio
        minio_client = await get_minio_storage()
        md_file_paths = []
        preview_map: dict[int, str] = {}  # md_object_name -> preview_object_name

        for index, article in enumerate(articles):
            file_name = self._sanitize_file_name(article.title)
            unique_id = generate_uuid()

            # Upload content as .md
            md_object_name = f"channel_articles/{unique_id}/{file_name}.md"
            md_content = article.content or ""
            await minio_client.put_object_tmp(
                object_name=md_object_name,
                file=md_content.encode("utf-8"),
                content_type="text/markdown",
            )
            md_file_paths.append(
                await minio_client.get_share_link(md_object_name, bucket=minio_client.tmp_bucket, clear_host=False)
            )

            preview_map[index] = article.content_html

        # 4. Call KnowledgeSpaceService.add_file
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        knowledge_files = await space_service.add_file(
            knowledge_id=req.knowledge_id,
            file_path=md_file_paths,
            parent_id=req.parent_id,
            file_source=FileSource.CHANNEL,
        )

        # 5. Update preview_file_object_name for successful files
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao, KnowledgeFileStatus

        result = []
        failed = False
        for index, kf in enumerate(knowledge_files):
            if kf.status != KnowledgeFileStatus.FAILED.value:
                html_content = preview_map[index]
                preview_object_name = f"preview/{kf.id}.html"
                await minio_client.put_object(
                    object_name=preview_object_name, file=html_content.encode("utf-8"), content_type="text/html"
                )
                kf.preview_file_object_name = preview_object_name
                result.append(kf)
            else:
                failed = True
        await KnowledgeFileDao.async_update_batch(result)
        if failed and not req.skip_missing_and_duplicates:
            raise SpaceFileNameDuplicateError()

        return result
