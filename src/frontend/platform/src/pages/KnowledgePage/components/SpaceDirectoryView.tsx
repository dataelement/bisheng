import { useCallback, useRef, type ComponentProps, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { FileStatusFilter } from "./FileStatusFilter";
import { SpaceDirectoryBrowseToolbar, type DirectoryViewMode } from "./SpaceDirectoryBrowseToolbar";
import styles from "./SpaceDirectoryView.module.css";

export type { DirectorySortField, DirectoryViewMode } from "./SpaceDirectoryBrowseToolbar";

interface SpaceDirectoryViewProps extends ComponentProps<typeof SpaceDirectoryBrowseToolbar> {
  workspace: boolean;
  rows: KnowledgeSpaceChild[];
  footer?: ReactNode;
  renderRow: (item: KnowledgeSpaceChild, layout?: DirectoryViewMode) => ReactNode;
}

/** Presentation adapted from the former client FileListView and FileListToolbar. */
export function SpaceDirectoryView({
  workspace,
  rows,
  renderRow,
  footer,
  ...toolbar
}: SpaceDirectoryViewProps) {
  const { t } = useTranslation("knowledge");
  const cleanupScroll = useRef<() => void>();
  const scrollRef = useCallback((node: HTMLDivElement | null) => {
    cleanupScroll.current?.();
    cleanupScroll.current = undefined;
    if (!node) return;
    let hideTimer: number | undefined;
    const handleScroll = () => {
      node.dataset.scrolling = "true";
      window.clearTimeout(hideTimer);
      hideTimer = window.setTimeout(() => { delete node.dataset.scrolling; }, 700);
    };
    node.addEventListener("scroll", handleScroll, { passive: true });
    cleanupScroll.current = () => {
      window.clearTimeout(hideTimer);
      node.removeEventListener("scroll", handleScroll);
      delete node.dataset.scrolling;
    };
  }, []);

  if (!workspace)
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("fileName")}</TableHead>
            <TableHead>{t("updateTime")}</TableHead>
            <TableHead>
              <span className="inline-flex items-center gap-1">
                {t("status")}
                <FileStatusFilter {...toolbar.filter} />
              </span>
            </TableHead>
            <TableHead className="text-right">{t("operations")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>{rows.map((item) => renderRow(item))}</TableBody>
      </Table>
    );
  const { viewMode } = toolbar;
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <SpaceDirectoryBrowseToolbar {...toolbar} />
      <div ref={scrollRef} className={`flex min-h-0 flex-1 flex-col overflow-y-auto ${styles.rowViewport}`}>
        <div
          className={
            viewMode === "card"
              ? `shrink-0 ${styles.cardGrid}`
              : "flex shrink-0 flex-col"
          }
          data-view-mode={viewMode}
        >
          {rows.map((item) => renderRow(item, viewMode))}
        </div>
        {footer}
      </div>
    </div>
  );
}
