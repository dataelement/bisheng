import { VersionHistoryDialog, type VersionHistoryEntry } from "@bisheng/knowledge";
import { toast } from "@bisheng/ui";
import { useQueries, useQuery, useQueryClient, type QueryFunctionContext } from "@tanstack/react-query";
import { useContext, useEffect, useId, useRef } from "react";
import {
  knowledgeVersionsApi,
  type KnowledgeVersionsApi,
  type SpaceVersionHistory,
} from "@/controllers/API/knowledgeVersions";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { locationContext } from "@/contexts/locationContext";
import { KnowledgeScopeUnavailable } from "./KnowledgeScopeUnavailable";
import { useSpaceVersionFileActions } from "./useSpaceVersionFileActions";

interface SpaceVersionHistorySheetProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  fileId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged?: (anchorFileId?: number) => void;
  api?: Partial<KnowledgeVersionsApi>;
}

const validId = (id: number | null): id is number =>
  id !== null && Number.isSafeInteger(id) && id > 0;

export function SpaceVersionHistorySheet(props: SpaceVersionHistorySheetProps) {
  const { appConfig } = useContext(locationContext);
  if (!props.open) return null;
  const key = JSON.stringify([
    ...knowledgeQueryKeys.space(props.scope, props.spaceId),
    props.parentId,
    props.fileId,
    appConfig.versionManagementEnabled === true,
  ]);
  return <HistoryOpening key={key} {...props} />;
}

function HistoryOpening({
  scope,
  spaceId,
  parentId,
  fileId,
  onOpenChange,
  onChanged,
  api: customApi,
}: SpaceVersionHistorySheetProps) {
  const { appConfig } = useContext(locationContext);
  const api = { ...knowledgeVersionsApi, ...customApi };
  const client = useQueryClient();
  const opening = useId();
  const readFileId = useRef(fileId);
  const removedFileIds = useRef(new Set<number>());
  const current = useRef(true);
  useEffect(() => {
    current.current = true;
    return () => { current.current = false; };
  }, []);
  const spaceKey = knowledgeQueryKeys.space(scope, spaceId);
  const enabled = Boolean(scope.identityKey) && validId(scope.tenantId) &&
    validId(spaceId) && validId(fileId) && (parentId === null || validId(parentId));
  // Each opening has its own request and cache lifetime.
  const historyKey = [...spaceKey, "version-history", parentId, fileId, opening];
  const query = useQuery({
    queryKey: historyKey,
    enabled,
    queryFn: ({ signal }) => api.getSpaceFileVersions(readFileId.current!, signal),
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (query.error) showApiError(query.error);
  }, [query.error]);
  const matchesSpace = query.data?.knowledge_id === spaceId;
  const data = query.data && !query.isError && matchesSpace ? {
    ...query.data,
    versions: query.data.versions.filter(version => !removedFileIds.current.has(version.knowledge_file_id)),
  } : undefined;

  const permissions = useQuery({
    queryKey: [...spaceKey, "version-actions", opening],
    queryFn: () => getMyResourcePermissionsApi("knowledge_space", String(spaceId)),
    enabled: enabled && appConfig.versionManagementEnabled === true,
    retry: false,
    cacheTime: 0,
  });
  const canManage = appConfig.versionManagementEnabled === true && Boolean(data) &&
    permissions.isSuccess && !permissions.isFetching && permissions.data.actions?.includes("edit") === true;
  const historicalIds = [...new Set((data?.versions ?? [])
    .filter(version => !version.is_primary && validId(version.knowledge_file_id))
    .map(version => version.knowledge_file_id))];
  const deletePermissions = useQueries({
    queries: historicalIds.map(id => ({
      queryKey: [...spaceKey, "version-delete-actions", id, opening],
      queryFn: ({ signal }: QueryFunctionContext) => getMyResourcePermissionsApi("knowledge_file", String(id), { signal }),
      enabled: canManage,
      retry: false,
      cacheTime: 0,
    })),
  });
  const permissionError = permissions.error ?? deletePermissions.find(permission => permission.isError)?.error;
  useEffect(() => {
    if (permissionError) showApiError(permissionError);
  }, [permissionError]);
  const canDelete = (version: VersionHistoryEntry) => {
    const permission = deletePermissions[historicalIds.indexOf(version.knowledge_file_id)];
    return canManage && permission?.isSuccess === true && !permission.isFetching && permission.data.actions?.includes("delete") === true;
  };

  const fileActions = useSpaceVersionFileActions({ scope, spaceId, parentId, versions: data?.versions ?? [] });
  const unavailable = !enabled || Boolean(query.data && !matchesSpace && !query.isError);
  const referencesRemovedFile = (key: readonly unknown[]) => {
    const kind = key[spaceKey.length];
    if (kind === "version-delete-actions") {
      const id = key[spaceKey.length + 1];
      return typeof id === "number" && removedFileIds.current.has(id);
    }
    if (kind === "version-download-actions") {
      const items = key[spaceKey.length + 3];
      return Array.isArray(items) && items.some((item: unknown) =>
        typeof item === "object" && item !== null && "id" in item &&
        typeof item.id === "number" && removedFileIds.current.has(item.id),
      );
    }
    return false;
  };
  const handleDeleteVersion = async (versionId: number, signal: AbortSignal) => {
    const version = data?.versions.find(item => item.version_id === versionId);
    const result = await api.deleteSpaceFileVersion(versionId, signal);
    if (signal.aborted || !current.current) return result;
    if (version) removedFileIds.current.add(version.knowledge_file_id);
    // Retire committed deletions before invalidation can refetch their permissions.
    client.setQueryData<SpaceVersionHistory>(historyKey, previous => previous && {
      ...previous,
      versions: previous.versions.filter(item => item.version_id !== versionId),
    });
    await client.cancelQueries({
      queryKey: spaceKey,
      predicate: cached => referencesRemovedFile(cached.queryKey),
    });
    return result;
  };
  const handleChanged = async (anchorFileId?: number) => {
    const nextAnchor = anchorFileId != null && validId(anchorFileId) ? anchorFileId : undefined;
    if (nextAnchor !== undefined && nextAnchor !== readFileId.current) {
      readFileId.current = nextAnchor;
      await client.cancelQueries({ queryKey: historyKey, exact: true });
      if (!current.current) return;
    }
    onChanged?.(nextAnchor);
    await client.invalidateQueries({
      queryKey: spaceKey,
      predicate: cached => !referencesRemovedFile(cached.queryKey),
    });
  };
  return (
    <VersionHistoryDialog
      open
      onOpenChange={onOpenChange}
      data={data}
      loading={query.isInitialLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      unavailable={unavailable ? <KnowledgeScopeUnavailable size="panel" role={enabled ? "alert" : "status"} /> : undefined}
      canManage={canManage}
      canDelete={canDelete}
      setPrimary={api.setSpacePrimaryVersion}
      deleteVersion={handleDeleteVersion}
      onChanged={handleChanged}
      onError={showApiError}
      onSuccess={message => toast.show({ type: "success", message })}
      {...fileActions}
    />
  );
}
