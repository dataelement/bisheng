import { Button, Dropdown, DropdownItem } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import { FileIcon, type FileType } from "@/components/bs-icons/file";
import { TableCell, TableRow } from "@/components/bs-ui/table";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { StatusIndicator } from "./KnowledgeFileStatus";

interface SpaceDirectoryRowProps {
  item: KnowledgeSpaceChild;
  open: boolean;
  actions: readonly string[];
  loading: boolean;
  error: boolean;
  onMenu: (open: boolean) => void;
  onOpen: () => void;
  onPreview: () => void;
  onRename: () => void;
  onDownload: () => void;
}
export function SpaceDirectoryRow({
  item,
  open,
  actions,
  loading,
  error,
  onMenu,
  onOpen,
  onPreview,
  onRename,
  onDownload,
}: SpaceDirectoryRowProps) {
  const { t } = useTranslation("knowledge");
  const folder = item.file_type === 0;
  const known = folder || item.file_type === 1;
  return (
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-2">
          {folder ? (
            <Outlined.FolderClose aria-hidden="true" />
          ) : (
            <FileIcon
              type={
                (item.file_name.split(".").pop()?.toLowerCase() ??
                  "txt") as FileType
              }
            />
          )}
          <Button
            variant="link"
            disabled={!known}
            onClick={folder ? onOpen : onPreview}
          >
            {item.file_name}
          </Button>
        </div>
      </TableCell>
      <TableCell>{item.update_time?.replace("T", " ") || "--"}</TableCell>
      <TableCell>
        {!folder && typeof item.status === "number" && (
          <StatusIndicator
            status={item.status}
            remark={item.remark ?? undefined}
          />
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
                {loading && (
                  <DropdownItem disabled>{t("loading")}</DropdownItem>
                )}
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
      </TableCell>
    </TableRow>
  );
}
