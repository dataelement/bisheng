import { toast } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId } from "react";
import { useTranslation } from "react-i18next";
import { inspectBatchItems } from "@/controllers/API/knowledgeBatch";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import type { SpaceVersionEntry } from "@/controllers/API/knowledgeVersions";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";

type VersionFile = Pick<SpaceVersionEntry, "knowledge_file_id">;

interface SpaceVersionFileActionsOptions {
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  versions: readonly VersionFile[];
}

export function useSpaceVersionFileActions({
  scope,
  spaceId,
  parentId,
  versions,
}: SpaceVersionFileActionsOptions) {
  const { t } = useTranslation("shared", { keyPrefix: "knowledge.version.history.download_feedback" });
  const opening = useId();
  const fileIds = new Set(
    versions.map((version) => version.knowledge_file_id).filter((id) => Number.isSafeInteger(id) && id > 0),
  );
  const items = Array.from(fileIds, (id) => ({ id, type: "file" as const }));
  const downloadPermissions = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), "version-download-actions", parentId, opening, items],
    queryFn: ({ signal }) => inspectBatchItems({ spaceId, operation: "download", items }, signal),
    enabled: items.length > 0,
    cacheTime: 0,
    retry: false,
  });
  useEffect(() => {
    if (downloadPermissions.error) showApiError(downloadPermissions.error);
  }, [downloadPermissions.error]);

  const downloadable = new Set(
    downloadPermissions.isSuccess && !downloadPermissions.isFetching && downloadPermissions.data.check_complete
      ? downloadPermissions.data.valid_items.filter((item) => item.type === "file").map((item) => item.id)
      : [],
  );

  const onPreview = (fileId: number) => {
    if (!fileIds.has(fileId)) return;
    const params = new URLSearchParams({ file_id: String(fileId) });
    if (scope.view === "admin") params.set("view", "admin");
    if (parentId !== null) params.set("parent_id", String(parentId));
    const basePath = __APP_ENV__.BASE_URL.replace(/\/$/, "");
    window.open(`${basePath}/filelib/${spaceId}?${params}`, "_blank", "noopener");
  };

  const onDownload = async (fileId: number, fileName: string, signal: AbortSignal) => {
    if (signal.aborted || !fileIds.has(fileId) || !downloadable.has(fileId)) return;
    try {
      const data = await knowledgeFilesApi.getSpaceFileDownload(spaceId, fileId, signal);
      if (signal.aborted) return;
      if (!data.original_url) {
        toast.show({ type: "warning", message: t("no_url") });
        return;
      }
      const anchor = document.createElement("a");
      anchor.href = data.original_url;
      anchor.download = fileName;
      anchor.target = "_blank";
      anchor.rel = "noopener";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch {
      if (!signal.aborted) toast.show({ type: "warning", message: t("failed") });
    }
  };

  return {
    canDownload: (version: VersionFile) => downloadable.has(version.knowledge_file_id),
    onDownload,
    onPreview,
  };
}
