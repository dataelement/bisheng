import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createManagerChannelApi,
  getChannelDetailApi,
  updateChannelApi,
  type Channel,
  type ChannelDetailResponse,
  ChannelRole,
} from "~/api/channels";
import {
  getCreationPermissionContext,
  getGrantablePermissionModels,
  getResourcePermissionContext,
  getResourcePermissionGrants,
  mutateResourceGrants,
  type GrantablePermissionModel,
  type CreationPermissionContext,
  type ResourcePermissionContext,
} from "~/api/permission";
import {
  usePermissionDraft,
  type PermissionDraftRow,
} from "~/components/permission/usePermissionDraft";
import { useLocalize } from "~/hooks";
import {
  buildChannelSettingsUpdatePayload,
  buildCreateChannelPayload,
  type CreateChannelFormData,
} from "../channelUtils";
import { createApiStatusError, extractApiStatusCode } from "../errorUtils";
import { useCreateChannelForm } from "../hooks/useCreateChannelForm";
import type { KnowledgeSyncDraft } from "../CreateChannel/KnowledgeSyncSection";

const EMPTY_SYNC_DRAFT: KnowledgeSyncDraft = {
  main: { enabled: false, spaces: [] },
  subs: [],
};

interface AuthorizationRecovery {
  channelId: string;
  errorCode: number | null;
}

function toPermissionDraftRows(
  entries: Awaited<ReturnType<typeof getResourcePermissionGrants>>["data"],
): PermissionDraftRow[] {
  return entries.map((entry) => ({
    subjectType: entry.subject.type,
    subjectId: Number(entry.subject.id),
    subjectName: entry.subject.name || entry.subject.id,
    modelKey: entry.model.key,
    modelName: entry.model.name,
    modelLevel: entry.model.level,
    includeChildren: entry.source.include_children,
    assigneeId: entry.assignee_id,
    assigneeVersion: entry.assignee_version,
    sourceType: entry.source.type,
    scope: entry.scope,
    inheritedFrom: entry.inherited_from,
    protected: entry.protected,
    editable: entry.editable,
  }));
}

function toChannel(detail: ChannelDetailResponse): Channel {
  return {
    ...detail,
    id: detail.id,
    name: detail.name,
    description: detail.description,
    creator: detail.creator_name,
    creatorId: "",
    subscriberCount: detail.subscriber_count,
    articleCount: detail.article_count,
    unreadCount: 0,
    role: ChannelRole.MEMBER,
    actions: detail.actions ?? [],
    isPinned: false,
    createdAt: detail.create_time ?? "",
    updatedAt: detail.latest_article_update_time ?? "",
    subChannels: [],
  };
}

export function useChannelSettingsForm(channelId?: string) {
  const localize = useLocalize();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const business = useCreateChannelForm();
  const permissionDraft = usePermissionDraft();
  const isEditMode = Boolean(channelId);
  const [knowledgeSync, setKnowledgeSync] = useState<KnowledgeSyncDraft>(EMPTY_SYNC_DRAFT);
  const [submitting, setSubmitting] = useState(false);
  const [authorizationRecovery, setAuthorizationRecovery] = useState<AuthorizationRecovery | null>(null);
  const [catalogReleaseId, setCatalogReleaseId] = useState<number | null>(null);
  const [resourceVersion, setResourceVersion] = useState<number | null>(null);
  const creationRequestId = useMemo(() => crypto.randomUUID(), []);
  const initBusinessFromChannel = business.initFromChannel;
  const setBusinessSources = business.setSources;
  const loadBusinessSourcesByIds = business.loadSourcesByIds;
  const resetPermissionDraft = permissionDraft.reset;

  const detailQuery = useQuery({
    queryKey: ["channel-settings", channelId],
    queryFn: () => getChannelDetailApi(channelId as string),
    enabled: isEditMode,
    retry: false,
  });
  const detail = detailQuery.data;
  const canEditBusiness = !isEditMode || Boolean(detail?.actions?.includes("edit"));
  const canManagePermissions = isEditMode
    ? Boolean(detail?.actions?.includes("manage_permission"))
    : true;
  // The backend returns knowledge_sync only to the actual creator. An owner
  // relation may be granted to another user, so relation names are not an
  // authority signal for this creator-only business setting.
  const isChannelCreator = !isEditMode || detail?.knowledge_sync != null;

  const permissionContextQuery = useQuery<
    ResourcePermissionContext | CreationPermissionContext
  >({
    queryKey: ["channel-settings", channelId ?? "create", "permission-context"],
    queryFn: () => channelId
      ? getResourcePermissionContext("channel", channelId)
      : getCreationPermissionContext("channel"),
    enabled: !isEditMode || canManagePermissions,
    retry: false,
  });
  const relationModelsQuery = useQuery({
    queryKey: ["channel-settings", channelId ?? "create", "relation-models"],
    queryFn: () => getGrantablePermissionModels("channel", channelId as string),
    enabled: isEditMode && canManagePermissions,
    retry: false,
  });
  const permissionQuery = useQuery({
    queryKey: ["channel-settings", channelId, "permissions"],
    queryFn: () => getResourcePermissionGrants("channel", channelId as string, { page_size: 200 }),
    enabled: isEditMode && canManagePermissions,
    retry: false,
  });

  useEffect(() => {
    if (!detail) return;
    initBusinessFromChannel(toChannel(detail));
    const sourceInfos = detail.source_infos ?? [];
    if (sourceInfos.length > 0) {
      setBusinessSources(sourceInfos.map((source) => ({
        id: source.id,
        name: source.source_name || source.name || "",
        avatar: source.source_icon || source.icon,
        type: source.source_type === "wechat" ? "official_account" : "website",
      })));
    } else {
      void loadBusinessSourcesByIds(detail.source_list ?? []);
    }
    setKnowledgeSync(detail.knowledge_sync ?? EMPTY_SYNC_DRAFT);
  }, [detail, initBusinessFromChannel, loadBusinessSourcesByIds, setBusinessSources]);

  useEffect(() => {
    const context = permissionContextQuery.data;
    if (!context) return;
    setCatalogReleaseId(context.catalog_release_id);
    if ("resource_version" in context) setResourceVersion(context.resource_version);
    if (!permissionQuery.data || !("resource_version" in context)) return;
    resetPermissionDraft(toPermissionDraftRows(permissionQuery.data.data), {
      resourceVersion: context.resource_version,
      catalogReleaseId: context.catalog_release_id,
    });
  }, [permissionContextQuery.data, permissionQuery.data, resetPermissionDraft]);

  const relationModels = useMemo<GrantablePermissionModel[]>(
    () => channelId
      ? (relationModelsQuery.data ?? [])
      : (permissionContextQuery.data && "grantable_models" in permissionContextQuery.data
          ? permissionContextQuery.data.grantable_models
          : []),
    [channelId, permissionContextQuery.data, relationModelsQuery.data],
  );
  const showPermissionSection = canManagePermissions && relationModels.length > 0;
  const accessDenied = isEditMode
    && detail != null
    && !canEditBusiness
    && !canManagePermissions;

  const formData = useMemo<CreateChannelFormData>(() => ({
    sources: business.sources,
    channelName: business.channelName.trim(),
    channelDesc: business.channelDesc.trim(),
    visibility: business.visibility,
    publishToSquare: business.publishToSquare,
    contentFilter: business.contentFilter,
    filterGroups: business.filterGroups,
    topFilterRelation: business.topFilterRelation,
    createSubChannel: business.createSubChannel,
    subChannels: business.subChannels,
    knowledgeSync,
  }), [
    business.channelDesc,
    business.channelName,
    business.contentFilter,
    business.createSubChannel,
    business.filterGroups,
    business.publishToSquare,
    business.sources,
    business.subChannels,
    business.topFilterRelation,
    business.visibility,
    knowledgeSync,
  ]);

  const finish = useCallback(async (id: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["channels"] }),
      queryClient.invalidateQueries({ queryKey: ["channel-settings", id] }),
    ]);
    navigate(`/channel/${id}`, { replace: true });
  }, [navigate, queryClient]);

  const submit = useCallback(async () => {
    setSubmitting(true);
    try {
      if (!channelId) {
        const grants = showPermissionSection && formData.visibility !== "private"
          ? permissionDraft.diff.changes.filter((change) => change.op === "ADD")
          : [];
        const result = await createManagerChannelApi({
          ...buildCreateChannelPayload(formData),
          ...(grants.length > 0 && catalogReleaseId != null ? {
            creationRequestId,
            initialPermissions: {
              expected_catalog_release_id: catalogReleaseId,
              grants: grants.map((grant) => ({ model_key: grant.model_key, subject: grant.subject })),
            },
          } : {}),
        });
        if (result.initialPermissionResult?.status === "failed") {
          setAuthorizationRecovery({
            channelId: result.id,
            errorCode: result.initialPermissionResult.errorCode,
          });
          return { status: "permission_failed" as const, channelId: result.id };
        }
        await finish(result.id);
        return { status: "success" as const, channelId: result.id };
      }

      if (canEditBusiness) {
        const updateResult = await updateChannelApi(
          channelId,
          buildChannelSettingsUpdatePayload(formData, isChannelCreator),
        );
        const updateCode = extractApiStatusCode(updateResult);
        if (updateCode && updateCode !== 200) {
          throw createApiStatusError(updateResult);
        }
      }
      if (
        showPermissionSection
        && formData.visibility !== "private"
        && permissionDraft.hasChanges
      ) {
        if (resourceVersion == null || catalogReleaseId == null) {
          throw new Error("Missing F048 permission version context");
        }
        await mutateResourceGrants("channel", channelId, {
          idempotency_key: crypto.randomUUID(),
          expected_resource_version: resourceVersion,
          expected_catalog_release_id: catalogReleaseId,
          changes: permissionDraft.diff.changes,
        });
      }
      await finish(channelId);
      return { status: "success" as const, channelId };
    } finally {
      setSubmitting(false);
    }
  }, [
    canEditBusiness,
    channelId,
    catalogReleaseId,
    creationRequestId,
    finish,
    formData,
    isChannelCreator,
    permissionDraft.diff,
    permissionDraft.hasChanges,
    resourceVersion,
    showPermissionSection,
  ]);

  const retryAuthorization = useCallback(async () => {
    if (!authorizationRecovery) return;
    setSubmitting(true);
    try {
      const context = await getResourcePermissionContext("channel", authorizationRecovery.channelId);
      await mutateResourceGrants("channel", authorizationRecovery.channelId, {
        idempotency_key: crypto.randomUUID(),
        expected_resource_version: context.resource_version,
        expected_catalog_release_id: context.catalog_release_id,
        changes: permissionDraft.diff.changes,
      });
      await finish(authorizationRecovery.channelId);
    } finally {
      setSubmitting(false);
    }
  }, [authorizationRecovery, finish, permissionDraft.diff.changes]);

  return {
    localize,
    isEditMode,
    isLoading: (isEditMode && detailQuery.isLoading)
      || permissionContextQuery.isFetching
      || relationModelsQuery.isFetching
      || permissionQuery.isFetching,
    loadError: detailQuery.error || (accessDenied
      ? new Error("Channel settings access denied")
      : null) || (
      isEditMode && canManagePermissions
        ? permissionContextQuery.error || relationModelsQuery.error || permissionQuery.error
        : null
    ),
    business,
    formData,
    knowledgeSync,
    setKnowledgeSync,
    canEditBusiness,
    canManagePermissions,
    isChannelCreator,
    showPermissionSection,
    relationModels,
    permissionDraft,
    submitting,
    authorizationRecovery,
    submit,
    retryAuthorization,
    enterCreatedChannel: authorizationRecovery
      ? () => finish(authorizationRecovery.channelId)
      : undefined,
    cancel: () => navigate("/channel"),
  };
}
