import {
  SimilarDocumentDialog,
  VersionManagementDialog,
  type SimilarDocumentFile,
  type SimilarDocumentDialogProps,
} from "@bisheng/knowledge";
import { toast } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useMemo } from "react";
import {
  knowledgeVersionsApi,
  readPendingSimilarFiles,
  type KnowledgeVersionsApi,
  type VersionDocumentCandidate,
} from "@/controllers/API/knowledgeVersions";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { locationContext } from "@/contexts/locationContext";

interface SpaceSimilarDocumentDialogProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  restrictToFileIds?: number[];
  fileId?: number | null;
  file?: SimilarDocumentFile;
  open?: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged?: () => Promise<void>;
  api?: Partial<KnowledgeVersionsApi>;
}

const showSuccess = (message: string) => toast.show({ type: "success", message });
const validId = (id: number | null | undefined): id is number =>
  id != null && Number.isSafeInteger(id) && id > 0;

export function SpaceSimilarDocumentDialog(props: SpaceSimilarDocumentDialogProps) {
  const { appConfig } = useContext(locationContext);
  const singleFile = props.fileId !== undefined;
  if (props.open === false || !props.scope.identityKey ||
      !validId(props.scope.tenantId) || !validId(props.spaceId) ||
      !(props.restrictToFileIds ?? []).every(validId) ||
      (singleFile && (!validId(props.fileId) || appConfig.versionManagementEnabled !== true))) {
    return null;
  }
  return <SimilarDocumentContent
    key={JSON.stringify([props.scope, props.spaceId, props.fileId, props.restrictToFileIds])}
    {...props}
  />;
}

function SimilarDocumentContent({
  scope, spaceId, fileId, file, restrictToFileIds, onOpenChange, onChanged, api: customApi,
}: SpaceSimilarDocumentDialogProps) {
  const client = useQueryClient();
  const sourceOnly = fileId !== undefined;
  const api = { ...knowledgeVersionsApi, ...customApi };
  const { getVersionRecommendations, searchVersionDocuments, mergeSpaceFileVersion,
    linkSpaceFileVersion, dismissSpaceSimilarFile } = api;
  const services = useMemo<SimilarDocumentDialogProps["services"]>(() => ({
    getPending: readPendingSimilarFiles,
    getRecommendations: (id, signal) => getVersionRecommendations(id, sourceOnly, signal),
    searchDocuments: async (id, keyword, currentFileId, signal) => {
      const documents = new Map<number, VersionDocumentCandidate>();
      const cursors = new Set<string>();
      let cursor: string | undefined;
      do {
        const page = await searchVersionDocuments(id, currentFileId, keyword, sourceOnly, cursor, signal);
        for (const document of page.data) documents.set(document.document_id, document);
        if (!page.has_more) break;
        if (!page.next_cursor || cursors.has(page.next_cursor))
          throw new Error("Version candidate cursor did not progress");
        cursor = page.next_cursor;
        cursors.add(cursor);
      } while (!signal?.aborted);
      return [...documents.values()];
    },
    relate: sourceOnly ? mergeSpaceFileVersion : linkSpaceFileVersion,
    dismiss: dismissSpaceSimilarFile,
  }), [getVersionRecommendations, searchVersionDocuments, mergeSpaceFileVersion,
    linkSpaceFileVersion, dismissSpaceSimilarFile, sourceOnly]);
  const history = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "similar-file", fileId],
    queryFn: ({ signal }) => api.getSpaceFileVersions(fileId!, signal),
    enabled: sourceOnly && !file,
    retry: false,
    cacheTime: 0,
  });
  useEffect(() => {
    if (history.error) showApiError(history.error);
  }, [history.error]);
  const handleProcessed = () => {
    void client.invalidateQueries({ queryKey: knowledgeQueryKeys.space(scope, spaceId) });
    void onChanged?.();
  };
  if (!sourceOnly) return <SimilarDocumentDialog
    open
    onOpenChange={onOpenChange}
    spaceId={spaceId}
    restrictToFileIds={restrictToFileIds?.map(String)}
    services={services}
    onProcessed={handleProcessed}
    onError={showApiError}
    onSuccess={showSuccess}
  />;
  const data = history.data?.knowledge_id === spaceId ? history.data : undefined;
  const current = data?.versions.find(version => version.knowledge_file_id === fileId);
  const selectedFile = file ?? (data && validId(fileId) ? {
    id: fileId,
    name: current?.original_file_name ?? data.title,
    version_no: current?.version_no ?? data.current_primary_version_no,
    user_name: current?.uploader_name,
  } : undefined);
  return <VersionManagementDialog
    open
    onOpenChange={onOpenChange}
    spaceId={spaceId}
    file={selectedFile ?? null}
    services={services}
    onLinked={handleProcessed}
    onDismissed={handleProcessed}
    onError={showApiError}
    onSuccess={showSuccess}
  />;
}
