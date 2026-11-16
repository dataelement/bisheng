import { Button, Checkbox, Dropdown, DropdownItem } from "@bisheng/ui";
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
  canDownload?: boolean;
  onDownload: () => void;
}
export function SpaceDirectoryRow({
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
  canDownload = false,
  onDownload,
}: SpaceDirectoryRowProps) {
  const { t } = useTranslation("knowledge");
  const { appConfig } = useContext(locationContext);
  const folder = item.file_type === 0;
  const known = folder || item.file_type === 1;
  const historyEnabled =
    appConfig.versionManagementEnabled === true &&
    item.file_type === 1;
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
    [identityKey, tenantId, managementTenantId, view, spaceId, parentId, item.id, historyEnabled],
  );
  const [history, setHistory] = useState<typeof epoch | null>(null);
  return (
    <TableRow
      data-state={selected ? "selected" : undefined}
      className="h-14 odd:bg-bg-page even:bg-fill-1 hover:bg-fill-2 data-[state=selected]:bg-blue-50 data-[state=selected]:hover:bg-blue-50"
    >
      <TableCell className="px-4 py-2">
        <div className="flex min-w-0 items-center gap-2">
          {known && onSelect && (
            <Checkbox
              aria-label={`${t("deletion.select")} ${item.file_name}`}
              checked={selected}
              onCheckedChange={(checked) => onSelect(checked === true)}
            />
          )}
          {folder ? (
            <Outlined.FolderClose className="size-8 shrink-0 text-text-2" aria-hidden="true" />
          ) : (
            <FileIcon
              className="size-8 shrink-0"
              type={(item.file_name.split(".").pop()?.toLowerCase() ?? "txt") as FileType}
            />
          )}
          <Button className="min-w-0 max-w-full justify-start px-0 text-body" variant="link" disabled={!known} onClick={folder ? onOpen : onPreview} title={item.file_name}>
            <span className="truncate">{item.file_name}</span>
          </Button>
        </div>
      </TableCell>
      <TableCell className="whitespace-nowrap text-body text-text-3 tabular-nums">{item.update_time?.replace("T", " ") || "--"}</TableCell>
      <TableCell className="whitespace-nowrap">
        {!folder && typeof item.status === "number" && (
          <StatusIndicator status={item.status} remark={item.remark ?? undefined} />
        )}
      </TableCell>
      <TableCell className="px-4 text-right whitespace-nowrap">
        <div className="flex items-center justify-end gap-2">
          {!folder && canDownload && (
            <Button variant="text" color="default" iconOnly aria-label={t("downloadOriginal")} onClick={onDownload}>
              <Outlined.Download />
            </Button>
          )}
          {known && (
            <SpaceFileTools
              scope={scope}
              spaceId={spaceId}
              fileId={item.id}
              status={item.status}
              enabled={!folder}
            >
              {(tools) => (
                <Dropdown
                  align="end"
                  open={open}
                  onOpenChange={onMenu}
                  menu={
                    <>
                      {loading && <DropdownItem disabled>{t("loading")}</DropdownItem>}
                      {error && (
                        <DropdownItem onSelect={() => queueMicrotask(() => onMenu(true))}>
                          {t("retry")}
                        </DropdownItem>
                      )}
                      {!loading && !error && actions.includes("rename") && (
                        <DropdownItem onSelect={onRename}>{t("rename")}</DropdownItem>
                      )}
                      {tools}
                      {!loading && !error && actions.includes("delete") && (
                        <>
                          <DropdownItem onSelect={onReferences}>{t("deletion.references")}</DropdownItem>
                          <DropdownItem danger onSelect={onDelete}>
                            {t("deletion.delete_items")}
                          </DropdownItem>
                        </>
                      )}
                      {historyEnabled && !loading && !error && actions.includes("visible") && (
                        <DropdownItem onSelect={() => setHistory(epoch)}>
                          {t("f118.version_history")}
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
            </SpaceFileTools>
          )}
        </div>
        <SpaceVersionHistorySheet
          scope={epoch.scope}
          spaceId={epoch.spaceId}
          parentId={epoch.parentId}
          fileId={epoch.fileId}
          hasSimilar={item.has_similar === true && item.is_multi_version !== true && item.status === 2}
          open={epoch.enabled && history === epoch}
          onOpenChange={(next) => {
            if (!next) setHistory(null);
          }}
        />
      </TableCell>
    </TableRow>
  );
}
