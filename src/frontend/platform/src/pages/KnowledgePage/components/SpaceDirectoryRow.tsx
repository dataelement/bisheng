import { Button, Checkbox, Dropdown, DropdownItem, Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useContext, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileIcon, type FileType } from "@/components/bs-icons/file";
import { TableCell, TableRow } from "@/components/bs-ui/table";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { locationContext } from "@/contexts/locationContext";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { StatusIndicator } from "./KnowledgeFileStatus";
import { SpaceFileTools } from "./SpaceFileTools";
import { SpaceVersionHistorySheet } from "./SpaceVersionHistorySheet";

interface SpaceDirectoryRowProps {
  layout?: "list" | "card";
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  item: KnowledgeSpaceChild;
  open: boolean;
  actions: readonly string[];
  loading: boolean;
  error: boolean;
  selected?: boolean;
  onSelect?: (selected: boolean) => void;
  onDelete?: () => void;
  onReferences?: () => void;
  onMenu: (open: boolean) => void;
  onOpen: () => void;
  onPreview: () => void;
  onRename: () => void;
  onDownload: () => void;
}
export function SpaceDirectoryRow({
  layout,
  scope,
  spaceId,
  parentId,
  item,
  open,
  actions,
  loading,
  error,
  selected,
  onSelect,
  onDelete,
  onReferences,
  onMenu,
  onOpen,
  onPreview,
  onRename,
  onDownload,
}: SpaceDirectoryRowProps) {
  const { t } = useTranslation("knowledge");
  const { appConfig } = useContext(locationContext);
  const folder = item.file_type === 0;
  const known = folder || item.file_type === 1;
  const historyEnabled =
    appConfig.versionManagementEnabled === true && item.file_type === 1;
  const { identityKey, tenantId, managementTenantId, view } = scope;
  // Every scope/target/feature transition retires the previous opening forever.
  const epoch = useMemo(
    () => ({
      scope: { identityKey, tenantId, managementTenantId, view },
      spaceId,
      parentId,
      fileId: item.id,
      enabled: historyEnabled,
    }),
    [
      identityKey,
      tenantId,
      managementTenantId,
      view,
      spaceId,
      parentId,
      item.id,
      historyEnabled,
    ],
  );
  const [history, setHistory] = useState<typeof epoch | null>(null);
  const selection = known && onSelect && (
    <Checkbox
      aria-label={`${t("deletion.select")} ${item.file_name}`}
      checked={selected}
      onCheckedChange={(checked) => onSelect(checked === true)}
    />
  );
  const [failedThumbnail, setFailedThumbnail] = useState<string | null>(null);
  const extension = item.file_name.split(".").pop()?.toLowerCase() ?? "txt";
  const thumbnail =
    layout &&
    !folder &&
    item.status === 2 &&
    !["txt", "md", "csv", "html"].includes(extension) &&
    item.thumbnails &&
    item.thumbnails !== failedThumbnail
      ? item.thumbnails
      : null;
  const typeIcon = folder ? (
    <Outlined.FolderClose
      aria-hidden="true"
      className={
        layout === "card"
          ? "size-14 text-text-3"
          : layout
            ? "size-8 text-text-3"
            : undefined
      }
    />
  ) : (
    <FileIcon
      className={layout === "card" ? "size-14" : layout ? "size-8" : undefined}
      type={extension as FileType}
    />
  );
  const icon = thumbnail ? (
    <img
      src={thumbnail}
      alt=""
      loading="lazy"
      decoding="async"
      className={
        layout === "card"
          ? "size-full object-contain"
          : "size-8 rounded-sm object-cover"
      }
      onError={() => setFailedThumbnail(thumbnail)}
    />
  ) : (
    typeIcon
  );
  const status = !folder && typeof item.status === "number" && (
    <StatusIndicator status={item.status} remark={item.remark ?? undefined} />
  );
  const actionsContent = (
    <>
      {known && (
        <Dropdown
          align="end"
          open={open}
          onOpenChange={onMenu}
          menu={
            <>
              {loading && <DropdownItem disabled>{t("loading")}</DropdownItem>}
              {error && (
                <DropdownItem
                  onSelect={() => queueMicrotask(() => onMenu(true))}
                >
                  {t("retry")}
                </DropdownItem>
              )}
              {!loading && !error && actions.includes("rename") && (
                <DropdownItem onSelect={onRename}>{t("rename")}</DropdownItem>
              )}
              {!loading && !error && actions.includes("delete") && (
                <>
                  <DropdownItem onSelect={onReferences}>
                    {t("deletion.references")}
                  </DropdownItem>
                  <DropdownItem danger onSelect={onDelete}>
                    {t("delete")}
                  </DropdownItem>
                </>
              )}
              {historyEnabled &&
                !loading &&
                !error &&
                actions.includes("visible") && (
                  <DropdownItem onSelect={() => setHistory(epoch)}>
                    {t("f118.version_history")}
                  </DropdownItem>
                )}
              {!folder &&
                !loading &&
                !error &&
                actions.includes("download") && (
                  <DropdownItem onSelect={onDownload}>
                    {t("downloadOriginal")}
                  </DropdownItem>
                )}
            </>
          }
        >
          <Button
            variant="text"
            color="default"
            iconOnly
            aria-label={`${t("more", { ns: "bs" })} ${item.file_name}`}
          >
            <Outlined.More />
          </Button>
        </Dropdown>
      )}
      {!folder && (
        <SpaceFileTools
          scope={scope}
          spaceId={spaceId}
          fileId={item.id}
          status={item.status}
        />
      )}
      <SpaceVersionHistorySheet
        scope={epoch.scope}
        spaceId={epoch.spaceId}
        parentId={epoch.parentId}
        fileId={epoch.fileId}
        hasSimilar={
          item.has_similar === true &&
          item.is_multi_version !== true &&
          item.status === 2
        }
        open={epoch.enabled && history === epoch}
        onOpenChange={(next) => {
          if (!next) setHistory(null);
        }}
      />
    </>
  );
  const handleOpen = folder ? onOpen : onPreview;
  if (layout === "card")
    return (
      <div
        className={`group relative flex h-[160px] min-w-0 flex-col overflow-hidden rounded-md border border-border-base transition-colors hover:border-border-deep ${selected ? "bg-primary/5" : "bg-bg-page"}`}
      >
        <div className="relative flex min-h-0 flex-1 p-1.5">
          <button
            type="button"
            className="flex size-full items-center justify-center overflow-hidden rounded-sm"
            disabled={!known}
            onClick={handleOpen}
            aria-label={item.file_name}
          >
            {icon}
          </button>
          <span
            className={`absolute left-2 top-2 z-10 ${selected ? "" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 coarse-pointer:opacity-100"}`}
          >
            {selection}
          </span>
          <span className="absolute right-2 top-2 z-10 inline-flex items-center bg-bg-page opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 coarse-pointer:opacity-100">
            {actionsContent}
          </span>
          {item.status !== 2 && (
            <span className="absolute bottom-1.5 left-2">{status}</span>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-1 px-2 py-1.5">
          <button
            type="button"
            className="block w-full truncate text-left text-caption font-medium text-text-1 hover:text-primary disabled:text-text-3"
            title={item.file_name}
            disabled={!known}
            onClick={handleOpen}
          >
            {item.file_name}
          </button>
          <div className="flex min-h-5 min-w-0 items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1 overflow-hidden">
              {item.tags?.map((tag) => (
                <Tag key={tag.id} size="small">
                  {tag.name}
                </Tag>
              ))}
            </span>
            <span className="shrink-0 text-caption-sm text-text-3 tabular-nums">
              {item.update_time?.slice(0, 10) || "--"}
            </span>
          </div>
        </div>
      </div>
    );
  if (layout === "list")
    return (
      <div className="group flex min-h-14 min-w-0 items-center gap-3 px-4 py-2 odd:bg-bg-page even:bg-fill-1 hover:bg-fill-2">
        {selection}
        <span className="flex size-8 shrink-0 items-center justify-center">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            className="block w-full truncate text-left text-body text-text-1 hover:text-primary disabled:text-text-3"
            title={item.file_name}
            disabled={!known}
            onClick={handleOpen}
          >
            {item.file_name}
          </button>
          <div className="mt-0.5 flex min-w-0 items-center gap-2 overflow-hidden text-caption-sm text-text-3">
            <span className="shrink-0 tabular-nums">
              {item.update_time?.replace("T", " ") || "--"}
            </span>
            {!folder && item.file_size != null && (
              <span className="shrink-0">
                {formatWorkspaceFileSize(item.file_size)}
              </span>
            )}
            {item.tags?.map((tag) => (
              <Tag key={tag.id} size="small">
                {tag.name}
              </Tag>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          {status}
          <span className="inline-flex items-center">{actionsContent}</span>
        </div>
      </div>
    );
  return (
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-2">
          {selection}
          {icon}
          <Button variant="link" disabled={!known} onClick={handleOpen}>
            {item.file_name}
          </Button>
        </div>
      </TableCell>
      <TableCell>{item.update_time?.replace("T", " ") || "--"}</TableCell>
      <TableCell>{status}</TableCell>
      <TableCell className="text-right">{actionsContent}</TableCell>
    </TableRow>
  );
}

export function formatWorkspaceFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "--";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
