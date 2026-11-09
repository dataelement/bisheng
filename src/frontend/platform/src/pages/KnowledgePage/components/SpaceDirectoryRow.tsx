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
  onDownload,
}: SpaceDirectoryRowProps) {
  const { t } = useTranslation("knowledge");
  const { appConfig } = useContext(locationContext);
  const folder = item.file_type === 0;
  const known = folder || item.file_type === 1;
  const historyEnabled =
    appConfig.versionManagementEnabled === true &&
    item.file_type === 1 &&
    item.is_multi_version === true;
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
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-2">
          {known && onSelect && (
            <Checkbox
              aria-label={`${t("deletion.select")} ${item.file_name}`}
              checked={selected}
              onCheckedChange={(checked) => onSelect(checked === true)}
            />
          )}
          {folder ? (
            <Outlined.FolderClose aria-hidden="true" />
          ) : (
            <FileIcon
              type={(item.file_name.split(".").pop()?.toLowerCase() ?? "txt") as FileType}
            />
          )}
          <Button variant="link" disabled={!known} onClick={folder ? onOpen : onPreview}>
            {item.file_name}
          </Button>
        </div>
      </TableCell>
      <TableCell>{item.update_time?.replace("T", " ") || "--"}</TableCell>
      <TableCell>
        {!folder && typeof item.status === "number" && (
          <StatusIndicator status={item.status} remark={item.remark ?? undefined} />
        )}
      </TableCell>
      <TableCell className="text-right">
        {known && (
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
                {!folder && !loading && !error && actions.includes("download") && (
                  <DropdownItem onSelect={onDownload}>{t("downloadOriginal")}</DropdownItem>
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
          open={epoch.enabled && history === epoch}
          onOpenChange={(next) => {
            if (!next) setHistory(null);
          }}
        />
      </TableCell>
    </TableRow>
  );
}
