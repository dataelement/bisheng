import {
  Button,
  Checkbox,
  Dropdown,
  DropdownItem,
  DropdownSeparator,
  Tag,
} from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useContext, useMemo, useState } from "react";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { FileAbnormalStatusCell } from "./FileAbnormalStatusCell";
import KnowledgeTagSelect from "./tags/KnowledgeTagSelect";
import { SpaceRowVersionMenu } from "./SpaceRowVersionMenu";
import { useTranslation } from "react-i18next";
import { TableCell, TableRow } from "@/components/bs-ui/table";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { locationContext } from "@/contexts/locationContext";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { formatStrTime } from "@/util/utils";
import { StatusIndicator } from "./KnowledgeFileStatus";
import { SpaceDirectoryIcon } from "./SpaceDirectoryIcon";
import { SpaceVersionHistorySheet } from "./SpaceVersionHistorySheet";
import { SPACE_FILE_CHECKBOX_CLASS } from "./spaceFileSelectionStyles";

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
  onMove?: () => void;
  onRetry?: () => void;
  onChanged?: () => Promise<unknown>;
  canDownload?: boolean;
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
  onMove,
  onRetry,
  onChanged,
  canDownload = false,
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
      multiVersion: item.is_multi_version,
      hasSimilar: item.has_similar,
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
      item.is_multi_version,
      item.has_similar,
    ],
  );
  const [history, setHistory] = useState<{
    epoch: typeof epoch;
    panel: "merge" | "similar" | null;
  } | null>(null);
  const [permission, setPermission] = useState<typeof epoch | null>(null);
  const [tagsEditor, setTagsEditor] = useState<typeof epoch | null>(null);
  const menuReady = !loading && !error;
  const canRename = menuReady && actions.includes("rename");
  const canManagePermission =
    menuReady && actions.includes("manage_permission");
  const retryable = folder
    ? item.has_failed_files === true
    : [3, 6, 7].includes(item.status ?? -1);
  const selection = (layout || (known && onSelect)) && (
    <Checkbox
      aria-label={`${t("deletion.select")} ${item.file_name}`}
      checked={selected}
      disabled={!known || !onSelect}
      className={layout ? `shrink-0 ${SPACE_FILE_CHECKBOX_CLASS}` : undefined}
      onCheckedChange={(checked) => onSelect?.(checked === true)}
    />
  );
  const icon = <SpaceDirectoryIcon item={item} layout={layout} />;
  const similarIndicator = (
    <SpaceRowVersionMenu
      scope={scope}
      spaceId={spaceId}
      item={item}
      indicator
      enabled={historyEnabled}
      onOpen={(panel) => setHistory({ epoch, panel })}
    />
  );
  const status = folder ? (
    <FileAbnormalStatusCell hasAbnormalFiles={item.has_abnormal_files} />
  ) : (
    <>
      {typeof item.status === "number" && (
        <StatusIndicator
          status={item.status}
          remark={item.remark ?? undefined}
          workspace={Boolean(layout)}
        />
      )}
      {similarIndicator}
      {historyEnabled && item.is_multi_version === true && (item.version_no ?? 0) >= 1 && (
        <Tag size="small" color={layout ? "brand" : "default"} className={layout ? "shrink-0" : undefined}>
          {`V${item.version_no}`}
        </Tag>
      )}
    </>
  );
  const actionsContent = (
    <>
      {!folder && canDownload && (
        <Button
          variant="text"
          color="default"
          iconOnly
          aria-label={t("downloadOriginal")}
          onClick={onDownload}
        >
          <Outlined.Download />
        </Button>
      )}
      {known && (
        <Dropdown
          align="end"
          open={open}
          onOpenChange={onMenu}
          menu={
            <>
              {loading && (
                <DropdownItem
                  disabled
                  icon={
                    <Outlined.Loading
                      aria-hidden
                      className="animate-spin motion-reduce:animate-pulse"
                    />
                  }
                >
                  {t("loading")}
                </DropdownItem>
              )}
              {error && (
                <DropdownItem
                  icon={<Outlined.Refresh aria-hidden />}
                  onSelect={() => queueMicrotask(() => onMenu(true))}
                >
                  {t("retry")}
                </DropdownItem>
              )}
              {menuReady && !folder && canDownload && (
                <DropdownItem
                  icon={<Outlined.Download aria-hidden />}
                  onSelect={onDownload}
                >
                  {t("downloadOriginal")}
                </DropdownItem>
              )}
              {canManagePermission && (
                <DropdownItem
                  icon={<Outlined.PeopleSafe aria-hidden />}
                  onSelect={() => setPermission(epoch)}
                >
                  {t("managePermission", { ns: "permission" })}
                </DropdownItem>
              )}
              {canRename && !folder && (
                <DropdownItem
                  icon={<Outlined.Tag aria-hidden />}
                  onSelect={() => setTagsEditor(epoch)}
                >
                  {t("editTag")}
                </DropdownItem>
              )}
              {canRename && (
                <DropdownItem
                  icon={<Outlined.Edit aria-hidden />}
                  onSelect={onRename}
                >
                  {t("rename")}
                </DropdownItem>
              )}
              {menuReady && actions.includes("move") && onMove && (
                <DropdownItem
                  icon={<Outlined.MoveToFolder aria-hidden />}
                  onSelect={onMove}
                >
                  {t("move.title")}
                </DropdownItem>
              )}
              {canRename && retryable && onRetry && (
                <DropdownItem
                  icon={<Outlined.Refresh aria-hidden />}
                  onSelect={onRetry}
                >
                  {t("retry")}
                </DropdownItem>
              )}
              {historyEnabled &&
                menuReady &&
                item.is_multi_version === true && (
                  <DropdownItem
                    icon={<Outlined.History aria-hidden />}
                    onSelect={() => setHistory({ epoch, panel: null })}
                  >
                    {t("f118.version_history")}
                  </DropdownItem>
                )}
              <SpaceRowVersionMenu
                scope={scope}
                spaceId={spaceId}
                item={item}
                enabled={historyEnabled && menuReady && open}
                onOpen={(panel) => setHistory({ epoch, panel })}
              />
              {menuReady && actions.includes("delete") && (
                <>
                  <DropdownItem
                    icon={<Outlined.FileSearch aria-hidden />}
                    onSelect={onReferences}
                  >
                    {t("deletion.references")}
                  </DropdownItem>
                  <DropdownSeparator />
                  <DropdownItem
                    danger
                    icon={<Outlined.Delete aria-hidden />}
                    onSelect={onDelete}
                  >
                    {t("delete")}
                  </DropdownItem>
                </>
              )}
            </>
          }
        >
          <Button
            variant={layout === "card" ? "outlined" : "text"}
            color="default"
            iconOnly
            className={
              layout === "card"
                ? "size-5 rounded-md px-0"
                : layout
                  ? "rounded-lg"
                  : undefined
            }
            aria-label={`${t("more", { ns: "bs" })} ${item.file_name}`}
          >
            <Outlined.More
              className={layout === "card" ? "rotate-90" : undefined}
            />
          </Button>
        </Dropdown>
      )}
      {permission === epoch && (
        <PermissionDialog
          open
          onOpenChange={(next) => {
            if (!next) {
              setPermission(null);
              void onChanged?.();
            }
          }}
          resourceType={folder ? "folder" : "knowledge_file"}
          resourceId={String(item.id)}
          resourceName={item.file_name}
        />
      )}
      {tagsEditor === epoch && (
        <KnowledgeTagSelect
          knowledgeId={spaceId}
          fileIds={[item.id]}
          initialTags={item.tags}
          open
          onOpenChange={(next) => {
            if (!next) setTagsEditor(null);
          }}
          onUpdate={() => {
            void onChanged?.();
          }}
        />
      )}
      <SpaceVersionHistorySheet
        scope={epoch.scope}
        spaceId={epoch.spaceId}
        parentId={epoch.parentId}
        fileId={epoch.fileId}
        file={{
          id: item.id,
          name: item.file_name,
          version_no: item.version_no,
          user_name: item.user_name,
        }}
        hasSimilar={
          item.has_similar === true &&
          item.is_multi_version !== true &&
          item.status === 2
        }
        open={epoch.enabled && history?.epoch === epoch}
        initialPanel={history?.epoch === epoch ? history.panel : null}
        onOpenChange={(next) => {
          if (!next) setHistory(null);
        }}
      />
    </>
  );
  const handleOpen = folder ? onOpen : onPreview;
  const compactDate = item.update_time
    ? formatStrTime(item.update_time, "yyyy-MM-dd")
    : "--";
  const unparsed = !folder && item.status !== 2;
  const nameTone = unparsed ? "text-text-3" : "text-text-1 hover:text-blue-500";
  const selectedStyle = selected
    ? { backgroundColor: "rgb(var(--brand-500) / 0.07)" }
    : undefined;
  const tags =
    !folder && item.tags?.length ? (
      <span className="flex min-w-0 items-center gap-1 overflow-hidden">
        {item.tags.map((tag) => (
          <span key={tag.id} className="truncate" title={tag.name}>
            #{tag.name}
          </span>
        ))}
      </span>
    ) : null;
  if (layout === "card")
    return (
      <div
        className={`group relative flex h-[160px] min-w-0 flex-col overflow-hidden rounded-md border-[0.5px] border-border-base transition-colors duration-[350ms] ${selected ? "" : "hover:border-border-deep"} ${unparsed ? "bg-[#fbfbfb] dark:bg-fill-1" : "bg-bg-page"}`}
        style={selectedStyle}
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
          <span
            className={`absolute right-2 top-2 z-20 inline-flex items-center transition-opacity ${open ? "" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 coarse-pointer:opacity-100"}`}
          >
            {actionsContent}
          </span>
          <span className="absolute bottom-2.5 left-2.5 z-10 flex items-center gap-1">
            {status}
          </span>
        </div>
        <div className="flex min-w-0 flex-col gap-1 px-2 py-1.5">
          <button
            type="button"
            className={`w-full text-left text-xs font-medium leading-5 disabled:text-text-3 ${nameTone}`}
            title={item.file_name}
            disabled={!known}
            onClick={handleOpen}
          >
            <span className="line-clamp-2 min-h-10 break-all">
              {item.file_name}
            </span>
          </button>
          <div className="flex min-h-5 min-w-0 items-center justify-between gap-2">
            <div className="min-w-0 flex-1 text-caption-sm leading-5 text-text-3">
              {tags}
            </div>
            <span className="shrink-0 text-caption-sm leading-5 text-text-3 tabular-nums">
              {compactDate}
            </span>
          </div>
        </div>
      </div>
    );
  if (layout === "list")
    return (
      <div
        className={`group flex h-14 min-w-0 items-center gap-2 px-4 transition-colors odd:bg-bg-page even:bg-[#fbfbfb] dark:even:bg-fill-1 ${selected ? "" : "hover:bg-fill-1"}`}
        style={selectedStyle}
      >
        {selection}
        <span className="relative flex size-8 shrink-0 items-center justify-center overflow-hidden rounded">
          {icon}
        </span>
        <div className="flex min-w-0 flex-1 flex-col justify-center">
          <button
            type="button"
            className={`block w-fit max-w-full truncate text-left text-sm leading-[22px] disabled:text-text-3 ${nameTone}`}
            title={item.file_name}
            disabled={!known}
            onClick={handleOpen}
          >
            {item.file_name}
          </button>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 overflow-hidden text-[10px] leading-[18px] text-text-3">
            <span className="shrink-0 tabular-nums">{compactDate}</span>
            {tags && (
              <>
                <span
                  className="h-2.5 w-px shrink-0 bg-border-base"
                  aria-hidden
                />
                <span className="min-w-0 text-[#999999] dark:text-text-3">
                  {tags}
                </span>
              </>
            )}
          </div>
        </div>
        <span className="inline-flex items-center gap-1">{status}</span>
        <div className="flex min-w-[73px] shrink-0 items-center justify-end">
          {actionsContent}
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
