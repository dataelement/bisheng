import { Button, Dropdown, Pagination, SearchInput, Select } from "@bisheng/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import {
  knowledgeQueryKeys,
  useKnowledgeAdminSpaces,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { FileAbnormalStatusCell } from "./components/FileAbnormalStatusCell";
import { KnowledgeTooltip } from "./components/KnowledgeTooltip";
import { SpaceMetadataPanel } from "./components/SpaceMetadataPanel";
import { useSpaceActions } from "./hooks/useSpaceActions";

interface KnowledgeSpaceAdminListProps {
  scope: KnowledgeQueryScope;
  toolbarTarget: HTMLDivElement | null;
}

export function KnowledgeSpaceAdminList({ scope, toolbarTarget }: KnowledgeSpaceAdminListProps) {
  const { t } = useTranslation("knowledge");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const selectLabels = useSelectLabels();
  const paginationLocale = usePaginationLocale();
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [fileStatus, setFileStatus] = useState("all");
  const [metadataSpaceId, setMetadataSpaceId] = useState<number | null>(null);
  const menuButtons = useRef(new Map<number, HTMLButtonElement>());
  const spaces = useKnowledgeAdminSpaces(scope, {
    page,
    page_size: pageSize,
    ...(keyword.trim() ? { keyword: keyword.trim() } : {}),
    ...(fileStatus === "abnormal" ? { has_abnormal: true } : {}),
  });
  const actions = useSpaceActions(scope, {
    onEdit: (id) => navigate(`/filelib/${id}/settings?view=admin`),
    onMetadata: setMetadataSpaceId,
  });
  const handleCloseMetadata = () => {
    setMetadataSpaceId(null);
    if (metadataSpaceId !== null) {
      requestAnimationFrame(() => menuButtons.current.get(metadataSpaceId)?.focus({ preventScroll: true }));
    }
  };
  const rows = spaces.data?.data ?? [];
  return (
    <div className="flex h-full min-h-0 flex-col px-2">
      {toolbarTarget && createPortal(
        <SearchInput
          aria-label={t("sidebar.search")}
          placeholder={t("sidebar.search")}
          value={keyword}
          onChange={(event) => {
            setKeyword(event.target.value);
            setPage(1);
          }}
        />,
        toolbarTarget,
      )}
      {spaces.isError && (
        <div role="alert" className="flex items-center gap-3 p-2">
          <p>{t("sidebar.load_failed")}</p>
          <Button variant="text" onClick={() => { void spaces.refetch(); }}>
            {t("retry")}
          </Button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <Table noScroll aria-label={t("f118.manage_spaces")}>
          <TableHeader>
            <TableRow>
              <TableHead>{t("f118.space_name")}</TableHead>
              <TableHead>{t("updateTime")}</TableHead>
              <TableHead>{t("lib.createUser", { ns: "bs" })}</TableHead>
              <TableHead>
                <div className="flex items-center gap-2">
                  {t("fileStatus")}
                  <Select
                    {...selectLabels}
                    options={[
                      { label: t("fileStatusFilterAll"), value: "all" },
                      { label: t("fileStatusAbnormal"), value: "abnormal" },
                    ]}
                    value={fileStatus}
                    onChange={(value) => {
                      setFileStatus(value === "abnormal" ? "abnormal" : "all");
                      setPage(1);
                    }}
                    trigger={
                      <Button
                        size="small"
                        variant="text"
                        color={fileStatus === "abnormal" ? "primary" : "default"}
                        iconOnly
                        aria-label={t("fileStatusFilterLabel", {
                          value: t(fileStatus === "abnormal" ? "fileStatusAbnormal" : "fileStatusFilterAll"),
                        })}
                      >
                        <Outlined.Filter aria-hidden="true" />
                      </Button>
                    }
                  />
                </div>
              </TableHead>
              <TableHead className="text-right">{t("operations")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id} hoverable={false}>
                <TableCell className="max-w-[500px]">
                  <div className="flex items-center gap-2">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-fill-2 text-text-2">
                      <Outlined.Books size={16} aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <KnowledgeTooltip content={row.name}>
                        <div className="truncate font-medium">{row.name}</div>
                      </KnowledgeTooltip>
                      {row.description && (
                        <KnowledgeTooltip content={row.description}>
                          <div className="truncate text-xs text-text-2">{row.description}</div>
                        </KnowledgeTooltip>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-text-2">{row.update_time?.replace("T", " ") || "--"}</TableCell>
                <TableCell className="text-text-2">{row.user_name || "--"}</TableCell>
                <TableCell>
                  <FileAbnormalStatusCell hasAbnormalFiles={row.has_abnormal_files} />
                </TableCell>
                <TableCell className="text-right">
                  <Dropdown align="end" onOpenChange={(open) => actions.load(row, open)} menu={actions.render(row)}>
                    <Button
                      ref={(button) => {
                        if (button) menuButtons.current.set(row.id, button);
                        else menuButtons.current.delete(row.id);
                      }}
                      variant="text"
                      color="default"
                      iconOnly
                      aria-label={t("more", { ns: "bs" })}
                    >
                      <Outlined.More aria-hidden="true" />
                    </Button>
                  </Dropdown>
                </TableCell>
              </TableRow>
            ))}
            {(spaces.isInitialLoading || (spaces.isSuccess && rows.length === 0)) && (
              <TableRow hoverable={false}>
                <TableCell colSpan={5} className="text-center text-text-2">
                  <span role="status">{t(spaces.isInitialLoading ? "f118.loading_space" : "sidebar.empty")}</span>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {spaces.data && (
        <div className="shrink-0 py-2">
          <Pagination
            locale={paginationLocale}
            current={page}
            pageSize={pageSize}
            total={spaces.data.total}
            showTotal
            showSizeChanger
            onChange={(next, size) => {
              setPage(next);
              setPageSize(size);
            }}
          />
        </div>
      )}
      {actions.dialogs}
      {metadataSpaceId !== null && (
        <SpaceMetadataPanel
          scope={scope}
          spaceId={metadataSpaceId}
          onClose={handleCloseMetadata}
          onSaved={() => {
            void queryClient.invalidateQueries({ queryKey: knowledgeQueryKeys.scope(scope) });
          }}
        />
      )}
    </div>
  );
}
