import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { FileType, type KnowledgeFile } from "~/api/knowledge";
import { getMyResourcePermissions } from "~/api/permission";
import { showApiError } from "~/api/request";
import { useAuthContext } from "~/hooks";
import type { UseKnowledgeFilePermissionsOptions } from "./knowledgeSpaceTypes";
import { useKnowledgeDownloadPermissions } from "./useKnowledgeDownloadPermissions";

export function useKnowledgeFilePermissions(options: UseKnowledgeFilePermissionsOptions) {
  const { displayFiles, space, currentFolderId, downloadEpoch = 0 } = options;
  const { user } = useAuthContext();
  const client = useQueryClient();
  const instance = useId();
  const generation = useRef(0);
  const identity = JSON.stringify([user?.id, user?.role, user?.tenant_id]);
  const containerKey = useMemo(
    () => ["knowledge-action-permissions", instance, ++generation.current, identity, space.id, currentFolderId, downloadEpoch],
    [instance, identity, space.id, currentFolderId, downloadEpoch],
  );
  const probeKey = displayFiles.filter(file => !file.isCreating && /^\d+$/.test(file.id))
    .map(file => `${file.id}:${file.type}`).join("|");
  const prefix = useMemo(() => [...containerKey, ++generation.current, probeKey], [containerKey, probeKey]);
  const active = useRef(prefix);
  active.current = prefix;
  const [requested, setRequested] = useState<{ prefix: readonly unknown[]; files: KnowledgeFile[] } | null>(null);
  const files = requested?.prefix === prefix ? requested.files : [];

  const container = useQuery({
    queryKey: containerKey,
    queryFn: ({ signal }) => getMyResourcePermissions(
      currentFolderId ? "folder" : "knowledge_space", currentFolderId || space.id, { signal },
    ),
    retry: false,
    cacheTime: 0,
    keepPreviousData: false,
  });
  const fileQuery = useCallback((file: KnowledgeFile) => ({
    queryKey: [...prefix, file.type, file.id],
    queryFn: ({ signal }: { signal?: AbortSignal }) => getMyResourcePermissions(
      file.type === FileType.FOLDER ? "folder" : "knowledge_file", file.id, { signal },
    ),
    retry: false,
    cacheTime: 0,
    staleTime: Infinity,
    refetchOnWindowFocus: "always" as const,
  }), [prefix]);
  const summaries = useQueries({ queries: files.map(fileQuery) });
  const error = container.error || summaries.find(query => query.isError)?.error;
  useEffect(() => { if (error) showApiError(error); }, [error]);

  const ensureFilePermissions = useCallback(async (file: KnowledgeFile) => {
    if (file.isCreating || !/^[1-9][0-9]*$/.test(file.id) || active.current !== prefix) return;
    setRequested(previous => {
      const rows = previous?.prefix === prefix ? previous.files : [];
      return rows.some(row => row.id === file.id && row.type === file.type)
        ? previous : { prefix, files: [...rows, file] };
    });
    try {
      // Reopening a menu must recheck revoked grants. In-flight requests dedupe
      // through the query cache; observers hide old actions during the refresh.
      await client.fetchQuery({ ...fileQuery(file), staleTime: 0 });
    } catch {
      // The observing query reports the error and keeps every action hidden.
    }
  }, [client, fileQuery, prefix]);

  const holding = (action: string) => new Set(files.flatMap((file, index) => {
    const query = summaries[index];
    return query?.isSuccess && !query.isFetching && query.data?.actions.includes(action) ? [file.id] : [];
  }));
  const actions = container.isSuccess && !container.isFetching ? container.data.actions : [];
  const downloadEntryIds = useKnowledgeDownloadPermissions(options);
  return {
    canCreateFolder: actions.includes("create_folder"),
    canUploadFile: actions.includes("upload_file"),
    canMoveFile: actions.includes("upload_file"),
    canMoveFolder: actions.includes("upload_file"),
    permissionEntryIds: holding("manage_permission"),
    moveEntryIds: holding("move"),
    renameEntryIds: holding("rename"),
    editEntryIds: holding("edit"),
    deleteEntryIds: holding("delete"),
    pendingFileIds: new Set(files.filter((_, index) => summaries[index]?.isFetching).map(file => file.id)),
    downloadEntryIds,
    ensureFilePermissions,
  };
}
