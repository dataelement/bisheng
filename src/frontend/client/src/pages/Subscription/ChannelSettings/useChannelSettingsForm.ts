import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  authorizeChannelApi,
  createManagerChannelApi,
  getChannelDetailApi,
  getChannelGrantableRelationModelsApi,
  getChannelPermissionsApi,
  updateChannelApi,
  type Channel,
  type ChannelDetailResponse,
} from "~/api/channels";
import {
  getCreationGrantableRelationModels,
  getFailedAuthorizationGrants,
  type AuthorizationResult,
  type GrantItem,
  type PermissionEntry,
  type RelationModel,
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

const MANAGE_PERMISSION_IDS = new Set([
  "manage_channel_user",
  "manage_channel_manager",
  "manage_channel_owner",
]);

interface AuthorizationRecovery {
  channelId: string;
  grants: GrantItem[];
  errorCode: number | null;
}

function toPermissionDraftRows(entries: PermissionEntry[]): PermissionDraftRow[] {
  return entries.map((entry) => ({
    subjectType: entry.subject_type,
    subjectId: entry.subject_id,
    subjectName: entry.subject_name || String(entry.subject_id),
    relation: entry.relation,
    modelId: entry.model_id,
    includeChildren: entry.include_children,
    immutableCreator: entry.is_creator === true,
    authorizationStatus: entry.authorizationStatus ?? "active",
    approvalInstanceId: entry.approvalInstanceId ?? null,
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
    role: detail.relation ?? "viewer",
    permissionIds: detail.permission_ids ?? [],
    isPinned: false,
    createdAt: detail.create_time ?? "",
    updatedAt: detail.latest_article_update_time ?? "",
    subChannels: [],
  };
}

function hasManagePermission(detail?: ChannelDetailResponse): boolean {
  return (detail?.permission_ids ?? []).some((id) => MANAGE_PERMISSION_IDS.has(id));
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
  const canEditBusiness = !isEditMode || (detail?.permission_ids ?? []).includes("edit_channel");
  const canManagePermissions = isEditMode
    ? hasManagePermission(detail)
    : true;
  // The backend returns knowledge_sync only to the actual creator. An owner
  // relation may be granted to another user, so relation names are not an
  // authority signal for this creator-only business setting.
  const isChannelCreator = !isEditMode || detail?.knowledge_sync != null;

  const relationModelsQuery = useQuery({
    queryKey: ["channel-settings", channelId ?? "create", "relation-models"],
    queryFn: () => channelId
      ? getChannelGrantableRelationModelsApi(channelId)
      : getCreationGrantableRelationModels("channel"),
    enabled: !isEditMode || canManagePermissions,
    retry: false,
  });
  const permissionQuery = useQuery({
    queryKey: ["channel-settings", channelId, "permissions"],
    queryFn: () => getChannelPermissionsApi(channelId as string),
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
    if (!permissionQuery.data) return;
    resetPermissionDraft(toPermissionDraftRows(permissionQuery.data));
  }, [permissionQuery.data, resetPermissionDraft]);

  const relationModels = useMemo<RelationModel[]>(
    () => relationModelsQuery.data ?? [],
    [relationModelsQuery.data],
  );
  const showPermissionSection = canManagePermissions && relationModels.length > 0;

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
          ? permissionDraft.diff.grants
          : [];
        const result = await createManagerChannelApi({
          ...buildCreateChannelPayload(formData),
          ...(grants.length > 0 ? { initialPermissions: { grants } } : {}),
        });
        if (result.initialPermissionResult?.status === "failed") {
          const failedGrants = getFailedAuthorizationGrants(
            grants,
            result.initialPermissionResult.results,
          );
          setAuthorizationRecovery({
            channelId: result.id,
            grants: failedGrants,
            errorCode: result.initialPermissionResult.errorCode,
          });
          return {
            status: "permission_failed" as const,
            channelId: result.id,
            authorizationResult: result.initialPermissionResult,
          };
        }
        return {
          status: "success" as const,
          channelId: result.id,
          authorizationResult: result.initialPermissionResult ?? null,
        };
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
      let authorizationResult: AuthorizationResult | null = null;
      if (
        showPermissionSection
        && formData.visibility !== "private"
        && permissionDraft.hasChanges
      ) {
        authorizationResult = await authorizeChannelApi(channelId, permissionDraft.diff);
      }
      if (authorizationResult?.failedCount) {
        return {
          status: "permission_failed" as const,
          channelId,
          authorizationResult,
        };
      }
      return { status: "success" as const, channelId, authorizationResult };
    } finally {
      setSubmitting(false);
    }
  }, [
    canEditBusiness,
    channelId,
    formData,
    isChannelCreator,
    permissionDraft.diff,
    permissionDraft.hasChanges,
    showPermissionSection,
  ]);

  const retryAuthorization = useCallback(async () => {
    if (!authorizationRecovery) return;
    setSubmitting(true);
    try {
      const result = await authorizeChannelApi(authorizationRecovery.channelId, {
        grants: authorizationRecovery.grants,
        revokes: [],
      });
      const failedGrants = getFailedAuthorizationGrants(
        authorizationRecovery.grants,
        result.results,
      );
      if (failedGrants.length > 0) {
        setAuthorizationRecovery((current) => current
          ? { ...current, grants: failedGrants, errorCode: result.results.find(
            (item) => item.outcome === "failed",
          )?.errorCode ?? current.errorCode }
          : current);
        return;
      }
      await finish(authorizationRecovery.channelId);
    } finally {
      setSubmitting(false);
    }
  }, [authorizationRecovery, finish]);

  return {
    localize,
    isEditMode,
    isLoading: (isEditMode && detailQuery.isLoading)
      || relationModelsQuery.isFetching
      || permissionQuery.isFetching,
    loadError: detailQuery.error || (
      isEditMode && canManagePermissions
        ? relationModelsQuery.error || permissionQuery.error
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
    completeSubmission: finish,
    enterCreatedChannel: authorizationRecovery
      ? () => finish(authorizationRecovery.channelId)
      : undefined,
    cancel: () => navigate("/channel"),
  };
}
