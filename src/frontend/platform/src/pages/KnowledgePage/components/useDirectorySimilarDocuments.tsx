import { useQuery } from "@tanstack/react-query";
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
  const permission = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "detail-actions"],
    queryFn: () => getMyResourcePermissionsApi("knowledge_space", String(spaceId), { showError: false }),
    enabled: enabled && (hasPending || Boolean(selection)),
    retry: false,
    cacheTime: 0,
  });
  const canManage = permission.isSuccess && permission.data.actions.includes("manage_permission");
  const active = canManage ? selection : null;
  useEffect(() => {
    if (opening && !active) setOpening(current => current === opening ? null : current);
  }, [opening, active]);

  return {
    onProcessSimilar: enabled && canManage && hasPending
      ? () => setOpening({ epoch: versionEpoch, fileIds: selectedFiles.map(row => row.id) })
      : undefined,
    overlay: active && (
      <SpaceSimilarDocumentDialog
        scope={scope}
        spaceId={spaceId}
        restrictToFileIds={active.fileIds}
        onOpenChange={open => { if (!open) setOpening(current => current === active ? null : current); }}
      />
    ),
  };
}
