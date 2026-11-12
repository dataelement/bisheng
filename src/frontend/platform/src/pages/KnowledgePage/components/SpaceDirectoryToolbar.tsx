import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import { Button, SearchInput } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

interface SpaceDirectoryToolbarProps {
  compact?: boolean;
  spaceId: number;
  parentId: number | null;
  keyword: string;
  onKeywordChange: (value: string) => void;
  canCreateFolder: boolean;
  onCreateFolder: () => void;
  canUpload: boolean;
  onWebLink?: () => void;
  onBatchDownload?: () => void;
  onBatchRetry?: () => void;
  onBatchTag?: () => void;
  onMove?: () => void;
  onMoveJobs?: () => void;
  selectedCount?: number;
  onDeleteSelected?: () => void;
  onReferences?: () => void;
}

export function SpaceDirectoryToolbar({
  compact = false,
  spaceId,
  parentId,
  keyword,
  onKeywordChange,
  canCreateFolder,
  onCreateFolder,
  canUpload,
  onWebLink,
  onBatchDownload,
  onBatchRetry,
  onBatchTag,
  onMove,
  onMoveJobs,
  selectedCount = 0,
  onDeleteSelected,
  onReferences,
}: SpaceDirectoryToolbarProps) {
  const { t } = useTranslation("knowledge");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const handleUpload = () => {
    if (!canUpload) return;
    const next = new URLSearchParams(params);
    if (parentId === null) next.delete("parent_id");
    else next.set("parent_id", String(parentId));
    navigate({
      pathname: `/filelib/upload/${spaceId}`,
      search: next.toString(),
    });
  };
  return (
    <div className="flex flex-wrap items-center justify-end gap-3">
      {selectedCount > 0 && (
        <>
          <Button variant="outlined" onClick={onMove}>
            {t("move.title")}
          </Button>
          <Button variant="outlined" onClick={onBatchDownload}>
            {t("batch.download")}
          </Button>
          <Button variant="outlined" onClick={onBatchTag}>
            {t("batch.tag")}
          </Button>
          <Button variant="outlined" onClick={onBatchRetry}>
            {t("batch.retry")}
          </Button>
        </>
      )}
      {onMoveJobs && (
        <Button variant="outlined" onClick={onMoveJobs}>
          {t("move.jobs")}
        </Button>
      )}
      {selectedCount > 0 && (
        <Button color="danger" variant="outlined" onClick={onDeleteSelected}>
          {t("deletion.selected")} ({selectedCount})
        </Button>
      )}
      {onReferences && (
        <Button variant="outlined" onClick={onReferences}>
          {t("deletion.references")}
        </Button>
      )}
      {!compact && (
        <SearchInput
          aria-label={t("searchFileName")}
          placeholder={t("searchFileName")}
          value={keyword}
          onChange={(event) => onKeywordChange(event.target.value)}
        />
      )}
      {canCreateFolder && (
        <Button onClick={onCreateFolder}>{t("f118.create_folder")}</Button>
      )}
      {canUpload && knowledgeUploadCapabilities.webLink && onWebLink && (
        <Button variant="link" onClick={onWebLink}>
          {t("webLink")}
        </Button>
      )}
      {canUpload && (
        <Button variant="link" onClick={handleUpload}>
          {t("uploadFile")}
        </Button>
      )}
    </div>
  );
}
