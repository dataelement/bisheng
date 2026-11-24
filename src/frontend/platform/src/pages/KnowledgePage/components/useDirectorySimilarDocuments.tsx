import { useQueries } from "@tanstack/react-query";
import { useContext, useEffect, useMemo, useState } from "react";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { locationContext } from "@/contexts/locationContext";
import { SpaceSimilarDocumentDialog } from "./SpaceSimilarDocumentDialog";

interface DirectorySimilarDocumentsOptions {
  epoch: object;
  scope: KnowledgeQueryScope;
  spaceId: number;
  selectedRows: readonly KnowledgeSpaceChild[];
}

export function useDirectorySimilarDocuments({ epoch, scope, spaceId, selectedRows }: DirectorySimilarDocumentsOptions) {
  const { appConfig } = useContext(locationContext);
  const enabled = appConfig.versionManagementEnabled === true && Boolean(scope.identityKey);
  const versionEpoch = useMemo(() => ({ epoch, enabled }), [epoch, enabled]);
  const [opening, setOpening] = useState<{ epoch: typeof versionEpoch; fileIds: number[] } | null>(null);
  const selectedFiles = selectedRows.filter(row =>
    row.file_type === 1 && row.knowledge_id === spaceId && Number.isSafeInteger(row.id) && row.id > 0,
  );
  const hasPending = selectedFiles.some(row => row.has_similar === true && row.is_multi_version !== true && row.status === 2);
  const selection = enabled && opening?.epoch === versionEpoch ? opening : null;
  const fileIds = [...new Set(selection?.fileIds ?? selectedFiles.map(row => row.id))];
  const permissions = useQueries({
    queries: fileIds.map(id => ({
      queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "version-file-actions", id],
      queryFn: ({ signal }: { signal?: AbortSignal }) => getMyResourcePermissionsApi("knowledge_file", String(id), { showError: false, signal }),
      enabled: enabled && (hasPending || Boolean(selection)),
      retry: false,
      cacheTime: 0,
    })),
  });
  const grantedIds = fileIds.filter((_, index) => {
    const permission = permissions[index];
    return permission?.isSuccess && permission.data.actions.includes("edit");
  });
  const editableIds = grantedIds.filter(id => !permissions[fileIds.indexOf(id)]?.isFetching);
  const hasEditablePending = selectedFiles.some(row => editableIds.includes(row.id) && row.has_similar === true && row.is_multi_version !== true && row.status === 2);
  const active = grantedIds.length > 0 ? selection : null;
  useEffect(() => {
    if (opening && !active) setOpening(current => current === opening ? null : current);
  }, [opening, active]);

  return {
    onProcessSimilar: enabled && hasEditablePending
      ? () => setOpening({ epoch: versionEpoch, fileIds: editableIds })
      : undefined,
    overlay: active && (
      <SpaceSimilarDocumentDialog
        scope={scope}
        spaceId={spaceId}
        restrictToFileIds={active.fileIds.filter(id => grantedIds.includes(id))}
        onOpenChange={open => { if (!open) setOpening(current => current === active ? null : current); }}
      />
    ),
  };
}
