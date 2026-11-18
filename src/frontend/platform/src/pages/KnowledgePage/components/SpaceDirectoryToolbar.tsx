import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import { Button, Dropdown, DropdownItem, SearchInput } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { FolderPlus, Link2 } from "lucide-react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";

interface SpaceDirectoryToolbarProps {
  toolbarTarget?: HTMLDivElement | null;
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
  selectedCount?: number;
  onDeleteSelected?: () => void;
  onReferences?: () => void;
}

export function SpaceDirectoryToolbar({
  toolbarTarget,
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
  selectedCount = 0,
  onDeleteSelected,
  onReferences,
}: SpaceDirectoryToolbarProps) {
  const { t } = useTranslation("knowledge");
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const hasBatchActions = Boolean(onMove || onBatchDownload || onBatchTag || onBatchRetry || onReferences || onDeleteSelected);
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
  if (toolbarTarget !== undefined) {
    const controls = (
      <div className="flex flex-wrap items-center gap-3">
        {hasBatchActions && <Dropdown
          align="end"
          menu={
            <>
              {onMove && (
                <DropdownItem disabled={!selectedCount} onSelect={onMove}>
                  {t("move.title")}
                </DropdownItem>
              )}
              {onBatchDownload && (
                <DropdownItem
                  disabled={!selectedCount}
                  onSelect={onBatchDownload}
                >
                  {t("batch.download")}
                </DropdownItem>
              )}
              {onBatchTag && (
                <DropdownItem disabled={!selectedCount} onSelect={onBatchTag}>
                  {t("batch.tag")}
                </DropdownItem>
              )}
              {onBatchRetry && (
                <DropdownItem disabled={!selectedCount} onSelect={onBatchRetry}>
                  {t("batch.retry")}
                </DropdownItem>
              )}
              {onReferences && (
                <DropdownItem onSelect={onReferences}>
                  {t("deletion.references")}
                </DropdownItem>
              )}
              {onDeleteSelected && (
                <DropdownItem
                  danger
                  disabled={!selectedCount}
                  onSelect={onDeleteSelected}
                >
                  {t("deletion.selected")}
                </DropdownItem>
              )}
            </>
          }
        >
          <Button variant="outlined" color="default">
            {t("detail.batch")}
            {selectedCount > 0 ? ` (${selectedCount})` : ""}
            <Outlined.Down />
          </Button>
        </Dropdown>}
        {(canCreateFolder || canUpload) && (
          <Dropdown
            align="end"
            menu={
              <>
                {canCreateFolder && (
                  <DropdownItem icon={<FolderPlus />} onSelect={onCreateFolder}>
                    {t("f118.create_folder")}
                  </DropdownItem>
                )}
                {canUpload && (
                  <DropdownItem icon={<Outlined.Upload />} onSelect={handleUpload}>
                    {t("uploadFile")}
                  </DropdownItem>
                )}
                {canUpload &&
                  knowledgeUploadCapabilities.webLink &&
                  onWebLink && (
                    <DropdownItem icon={<Link2 />} onSelect={onWebLink}>
                      {t("webLink")}
                    </DropdownItem>
                  )}
              </>
            }
          >
            <Button variant="outlined" color="default" className="text-text-1">
              {t("detail.add")}
              <Outlined.Down />
            </Button>
          </Dropdown>
        )}
      </div>
    );
    return toolbarTarget ? createPortal(controls, toolbarTarget) : null;
  }
  return (
    <div className="flex flex-wrap items-center justify-end gap-3">
      {selectedCount > 0 && (
        <>
          {onMove && <Button variant="outlined" onClick={onMove}>
            {t("move.title")}
          </Button>}
          {onBatchDownload && <Button variant="outlined" onClick={onBatchDownload}>
            {t("batch.download")}
          </Button>}
          {onBatchTag && <Button variant="outlined" onClick={onBatchTag}>
            {t("batch.tag")}
          </Button>}
          {onBatchRetry && <Button variant="outlined" onClick={onBatchRetry}>
            {t("batch.retry")}
          </Button>}
        </>
      )}
      {selectedCount > 0 && onDeleteSelected && (
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
