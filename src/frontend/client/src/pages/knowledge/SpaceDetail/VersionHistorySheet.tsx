import { VersionHistoryDialog, type VersionHistoryEntry } from "@bisheng/knowledge";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef } from "react";
import {
  deleteFileVersionApi,
  getFileVersionsApi,
  setPrimaryVersionApi,
} from "~/api/knowledge";
import { inspectBatch } from "~/api/knowledgeBatch";
import { getMyResourcePermissions } from "~/api/permission";
import { showApiError } from "~/api/request";
import { useToastContext } from "~/Providers";
import { useAuthContext, useLocalize } from "~/hooks";

interface VersionHistorySheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spaceId: number;
  fileId: number | null;
  documentTitle?: string;
  canManage: boolean;
  onPreview?: (versionFileId: number, fileName: string) => void;
  onDownload?: (versionFileId: number, fileName: string, signal: AbortSignal) => Promise<void>;
  onChanged?: () => void;
}

interface VersionHistorySessionProps extends Omit<VersionHistorySheetProps, "fileId"> {
  fileId: number;
  scopeKey: string;
  validScope: boolean;
}

function isValidId(id: number): boolean {
  return Number.isSafeInteger(id) && id > 0;
}

export function VersionHistorySheet(props: VersionHistorySheetProps) {
  const { user } = useAuthContext();
  if (!props.open || props.fileId === null) return null;

  const scopeKey = JSON.stringify([user?.id, user?.role, user?.tenant_id, props.spaceId, props.fileId]);
  return (
    <VersionHistorySession
      key={scopeKey}
      {...props}
      fileId={props.fileId}
      scopeKey={scopeKey}
      validScope={Boolean(user?.id) && isValidId(props.spaceId) && isValidId(props.fileId)}
    />
  );
}

function VersionHistorySession({
  open,
  onOpenChange,
  spaceId,
  fileId,
  documentTitle,
  canManage,
  onPreview,
  onDownload,
  onChanged,
  scopeKey,
  validScope,
}: VersionHistorySessionProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const instance = useId();
  // The selected file can become historical and be deleted while the dialog is open.
  const readFileId = useRef(fileId);
  const queryClient = useQueryClient();
  const queryKey = ["file-versions", fileId, scopeKey, instance];
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => getFileVersionsApi(readFileId.current, signal),
    onError: showApiError,
    enabled: validScope,
    retry: false,
    cacheTime: 0,
  });

  const scopeMismatch = Boolean(query.data && query.data.knowledge_id !== spaceId);
  const data = validScope && !scopeMismatch && !query.isError ? query.data : undefined;
  const fileIds = [...new Set(data?.versions.map(version => version.knowledge_file_id).filter(isValidId))];
  const deleteIds = [...new Set(data?.versions.filter(version => !version.is_primary)
    .map(version => version.knowledge_file_id).filter(isValidId))];
  const deletes = useQueries({
    queries: deleteIds.map(id => ({
      queryKey: [...queryKey, "delete", id],
      queryFn: ({ signal }: { signal?: AbortSignal }) => getMyResourcePermissions("knowledge_file", String(id), { signal }),
      enabled: canManage,
      retry: false,
      cacheTime: 0,
    })),
  });
  const deletePermissionError = deletes.find(permission => permission.isError)?.error;
  useEffect(() => { if (deletePermissionError) showApiError(deletePermissionError); }, [deletePermissionError]);

  const downloadQuery = useQuery({
    queryKey: [...queryKey, "download", fileIds],
    queryFn: ({ signal }) => inspectBatch({
      spaceId,
      operation: "download",
      items: fileIds.map(id => ({ id, type: "file" })),
    }, signal),
    enabled: Boolean(onDownload) && fileIds.length > 0,
    onError: showApiError,
    retry: false,
    cacheTime: 0,
  });
  const downloadable = new Set(downloadQuery.isSuccess && !downloadQuery.isFetching &&
    downloadQuery.data.inspection.check_complete
    ? downloadQuery.data.inspection.valid_items.filter(item => item.type === "file").map(item => item.id)
    : []);

  const canDelete = (version: VersionHistoryEntry) => {
    const permission = deletes[deleteIds.indexOf(version.knowledge_file_id)];
    return permission?.isSuccess === true && !permission.isFetching && permission.data.actions.includes("delete");
  };
  const handleChanged = (anchorFileId?: number) => {
    if (anchorFileId !== undefined && isValidId(anchorFileId) && anchorFileId !== readFileId.current) {
      readFileId.current = anchorFileId;
      void queryClient.cancelQueries({ queryKey, exact: true });
    }
    onChanged?.();
    return queryClient.invalidateQueries({ queryKey }, { cancelRefetch: false });
  };

  return (
    <VersionHistoryDialog
      open={open}
      onOpenChange={onOpenChange}
      documentTitle={documentTitle}
      data={data}
      loading={query.isInitialLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      unavailable={!validScope || scopeMismatch ? <p role="alert">{localize("com_ui_error")}</p> : undefined}
      canManage={canManage}
      canDelete={canDelete}
      onPreview={onPreview}
      onDownload={onDownload}
      canDownload={version => downloadable.has(version.knowledge_file_id)}
      setPrimary={setPrimaryVersionApi}
      deleteVersion={deleteFileVersionApi}
      onChanged={handleChanged}
      onError={showApiError}
      onSuccess={message => showToast({ message, status: "success" })}
    />
  );
}
