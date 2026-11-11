import {
  Button,
  Dropdown,
  DropdownItem,
  Pagination,
  SearchInput,
  Select,
  notification,
} from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { Shield } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import LoadMore from "@/components/bs-comp/loadMore";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { useLazyResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import { userContext } from "@/contexts/userContext";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  useKnowledgeAdminSpaces,
  useKnowledgeVisibleSpaces,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import type { User } from "@/types/api/user";
import { KnowledgeLibraryDialog } from "./components/KnowledgeLibraryDialog";
import { KnowledgeTooltip } from "./components/KnowledgeTooltip";
import { ProcessingDefaultsDialog } from "./components/ProcessingDefaultsDialog";
import { SpaceProcessingDialog } from "./components/SpaceProcessingDialog";
import { KnowledgeDeletionDialog } from "./components/KnowledgeDeletionDialog";
import { useKnowledgeDeletion } from "./hooks/useKnowledgeDeletion";
import { FileAbnormalStatusCell } from "./components/FileAbnormalStatusCell";

const ROW_ACTIONS = [
  "visible",
  "edit",
  "manage_permission",
  "upload_file",
  "delete",
];
interface KnowledgeFileProps {
  scope: KnowledgeQueryScope;
  toolbarTarget?: HTMLDivElement | null;
}

const pageWindow = window as Window & { LibPage?: { type: string } };

export default function KnowledgeFile({
  scope,
  toolbarTarget,
}: KnowledgeFileProps) {
  const { t } = useTranslation("knowledge"),
    navigate = useNavigate(),
    client = useQueryClient();
  const { user }: { user: Partial<User> | null } = useContext(userContext);
  const [keyword, setKeyword] = useState(""),
    [page, setPage] = useState(1),
    [pageSize, setPageSize] = useState(20);
  const [onlyAbnormal, setOnlyAbnormal] = useState(false);
  const selectLabels = useSelectLabels();
  const isAdmin = scope.view === "admin";
  const query = useMemo(
    () => ({
      page_size: pageSize,
      ...(keyword ? { keyword } : {}),
      ...(onlyAbnormal ? { has_abnormal: true } : {}),
    }),
    [pageSize, keyword, onlyAbnormal],
  );
  const ordinary = useKnowledgeVisibleSpaces(scope, query);
  const admin = useKnowledgeAdminSpaces(scope, { ...query, page });
  const active = isAdmin ? admin : ordinary;
  const rows = isAdmin
    ? (admin.data?.data ?? [])
    : (ordinary.data?.pages.flatMap((result) => result.data) ?? []);
  const paginationLocale = usePaginationLocale();
  const { identityKey, tenantId, managementTenantId, view } = scope;
  const stableScope = useMemo(
    () => ({
      identityKey,
      tenantId,
      managementTenantId,
      view,
    }),
    [identityKey, tenantId, managementTenantId, view],
  );
  const activeKey = useMemo(
    () =>
      isAdmin
        ? knowledgeQueryKeys.admin(stableScope, { ...query, page })
        : knowledgeQueryKeys.visible(stableScope, query),
    [isAdmin, stableScope, query, page],
  );
  const epoch = useMemo(() => ({ activeKey }), [activeKey]);
  const live = useRef<typeof epoch | null>(epoch);
  live.current = epoch;
  const refetch = active.refetch;
  useEffect(() => {
    live.current = epoch;
    if (identityKey && Number.isSafeInteger(tenantId) && tenantId > 0) {
      void refetch({ cancelRefetch: false }).catch((error) => {
        if (live.current === epoch) showApiError(error);
      });
    }
    return () => {
      if (live.current === epoch) live.current = null;
      void client.cancelQueries({
        queryKey: activeKey,
        exact: true,
        type: "inactive",
      });
    };
  }, [client, identityKey, tenantId, activeKey, epoch, refetch]);
  const canCreate =
    user?.is_global_super === true ||
    user?.is_child_admin === true ||
    user?.web_menu?.includes("create_knowledge") === true;
  const [processing, setProcessing] = useState<{
    row: KnowledgeSpaceInfo;
    mode: "copy" | "embedding" | "jobs" | "schema";
  } | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<KnowledgeSpaceInfo | null>(null);
  const [defaultsTarget, setDefaultsTarget] =
    useState<KnowledgeSpaceInfo | null>(null);
  const [permissionTarget, setPermissionTarget] =
    useState<KnowledgeSpaceInfo | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const handleFilter = (value: string | number | null | undefined) => {
    const next = value === "abnormal";
    if (next === onlyAbnormal) return;
    const nextQuery = {
      page_size: pageSize,
      ...(keyword ? { keyword } : {}),
      ...(next ? { has_abnormal: true } : {}),
    };
    const incoming = isAdmin
      ? knowledgeQueryKeys.admin(stableScope, { ...nextQuery, page: 1 })
      : knowledgeQueryKeys.visible(stableScope, nextQuery);
    // A previous visit to this filter must not restore its consumed cursor.
    client.removeQueries({ queryKey: incoming, exact: true, type: "inactive" });
    setOpenId(null);
    setEditTarget(null);
    setDefaultsTarget(null);
    setPermissionTarget(null);
    setProcessing(null);
    setOnlyAbnormal(next);
    setPage(1);
  };
  const filterOptions = [
    { label: t("fileStatusFilterAll"), value: "all" },
    { label: t("fileStatusAbnormal"), value: "abnormal" },
  ];
  const {
    actions,
    loading: actionLoading,
    load: loadActions,
  } = useLazyResourceActions("knowledge_space", ROW_ACTIONS);
  const hasAction = (row: KnowledgeSpaceInfo, action: string) =>
    actions[String(row.id)]?.includes(action) ?? false;
  const handleLookupError = () =>
    notification.open({
      type: "error",
      description: t("error.checkFailed", { ns: "permission" }),
    });
  const handleMenu = async (row: KnowledgeSpaceInfo, open: boolean) => {
    const id = String(row.id);
    if (!open) {
      setOpenId((current) => (current === id ? null : current));
      return;
    }
    setOpenId(id);
    const result = await loadActions(id);
    if (live.current !== epoch) return;
    if (result.hasError) {
      setOpenId((current) => (current === id ? null : current));
      handleLookupError();
    }
  };
  const handleRead = async (row: KnowledgeSpaceInfo) => {
    let allowed = row.actions?.includes("visible") || hasAction(row, "visible");
    if (!allowed) {
      const result = await loadActions(String(row.id));
      if (live.current !== epoch) return;
      if (result.hasError) {
        handleLookupError();
        return;
      }
      allowed = result.actions.includes("visible");
    }
    if (!allowed || live.current !== epoch) return;
    pageWindow.LibPage = { type: isAdmin ? "admin" : "file" };
    navigate(`/filelib/${row.id}`);
  };
  const handleRefresh = async () => {
    try {
      await refetch();
    } catch (error) {
      if (live.current === epoch) showApiError(error);
    }
  };
  const deletion = useKnowledgeDeletion(JSON.stringify([stableScope, epoch]));
  const handleDeletion = async (
    row: KnowledgeSpaceInfo,
    kind: "delete" | "clear",
    readonly = false,
  ) => {
    if (live.current !== epoch || !hasAction(row, "delete")) return;
    setOpenId(null);
    const owned = epoch;
    if (await deletion.open({ spaceId: row.id, kind }, readonly)) {
      if (live.current === owned)
        await client.invalidateQueries({
          queryKey: knowledgeQueryKeys.space(stableScope, row.id),
        });
      if (live.current === owned) await handleRefresh();
    }
  };
  const renderMenu = (row: KnowledgeSpaceInfo) => {
    if (actionLoading[String(row.id)])
      return (
        <DropdownItem disabled>
          {t("knowledgeRowActions.loading", { ns: "permission" })}
        </DropdownItem>
      );
    if (
      !hasAction(row, "edit") &&
      !hasAction(row, "manage_permission") &&
      !hasAction(row, "delete")
    )
      return (
        <DropdownItem disabled>
          {t("knowledgeRowActions.empty", { ns: "permission" })}
        </DropdownItem>
      );
    return (
      <>
        {canCreate &&
          user?.user_id === row.user_id &&
          hasAction(row, "upload_file") && (
            <DropdownItem
              onSelect={() => {
                setOpenId(null);
                setProcessing({ row, mode: "copy" });
              }}
            >
              {t("f118.processing_title_copy")}
            </DropdownItem>
          )}
        {hasAction(row, "delete") && (
          <>
            <DropdownItem
              onSelect={() => {
                void handleDeletion(row, "delete", true);
              }}
            >
              {t("deletion.references")}
            </DropdownItem>
            <DropdownItem
              danger
              onSelect={() => {
                void handleDeletion(row, "clear");
              }}
            >
              {t("deletion.clear")}
            </DropdownItem>
            <DropdownItem
              danger
              onSelect={() => {
                void handleDeletion(row, "delete");
              }}
            >
              {t("deletion.delete_space")}
            </DropdownItem>
          </>
        )}
        {hasAction(row, "manage_permission") && (
          <DropdownItem
            icon={<Shield />}
            onSelect={() => {
              setOpenId(null);
              setPermissionTarget(row);
            }}
          >
            {t("managePermission", { ns: "permission" })}
          </DropdownItem>
        )}
        {hasAction(row, "edit") && (
          <>
            <DropdownItem
              onSelect={() => {
                setOpenId(null);
                setEditTarget(row);
              }}
            >
              {t("settings")}
            </DropdownItem>
            <DropdownItem
              onSelect={() => {
                setOpenId(null);
                setProcessing({ row, mode: "schema" });
              }}
            >
              {t("f118.processing_title_schema")}
            </DropdownItem>
            <DropdownItem
              onSelect={() => {
                setOpenId(null);
                setProcessing({ row, mode: "embedding" });
              }}
            >
              {t("f118.processing_title_embedding")}
            </DropdownItem>
            <DropdownItem
              onSelect={() => {
                setOpenId(null);
                setProcessing({ row, mode: "jobs" });
              }}
            >
              {t("f118.processing_title_jobs")}
            </DropdownItem>
            <DropdownItem
              onSelect={() => {
                setOpenId(null);
                setDefaultsTarget(row);
              }}
            >
              {t("f118.defaults_title")}
            </DropdownItem>
          </>
        )}
      </>
    );
  };
  const toolbar = (
    <div className="flex items-center justify-end gap-4">
      <SearchInput
        placeholder={t("lib.searchPlaceholder", { ns: "bs" })}
        value={keyword}
        onChange={(event) => {
          setKeyword(event.target.value);
          setPage(1);
        }}
      />
      {canCreate && (
        <Button onClick={() => setCreateOpen(true)}>
          {t("create", { ns: "bs" })}
        </Button>
      )}
    </div>
  );
  return (
    <div className="relative">
      {processing && (
        <SpaceProcessingDialog
          key={JSON.stringify([scope, processing.row.id, processing.mode])}
          scope={scope}
          spaceId={processing.row.id}
          mode={processing.mode}
          includeCopies={user?.user_id === processing.row.user_id}
          open
          onOpenChange={(open) => {
            if (!open) setProcessing(null);
          }}
          onSaved={() => {
            void handleRefresh();
          }}
        />
      )}
      {toolbarTarget
        ? createPortal(toolbar, toolbarTarget)
        : toolbarTarget === undefined
          ? toolbar
          : null}
      {active.isInitialLoading && (
        <p role="status">{t("f118.loading_space")}</p>
      )}
      {active.isError && (
        <div role="alert">
          <p>{t("f118.load_failed")}</p>
          <Button
            onClick={() => {
              void handleRefresh();
            }}
          >
            {t("retry")}
          </Button>
        </div>
      )}
      <div className="h-[calc(100vh-128px-var(--license-banner-h,0px))] overflow-y-auto pb-20">
        <Table noScroll>
          <TableHeader>
            <TableRow>
              <TableHead>{t("f118.space_name")}</TableHead>
              <TableHead>{t("updateTime")}</TableHead>
              <TableHead>{t("lib.createUser", { ns: "bs" })}</TableHead>
              <TableHead>
                <div className="flex items-center">
                  {t("fileStatus")}
                  <Select
                    {...selectLabels}
                    options={filterOptions}
                    value={onlyAbnormal ? "abnormal" : "all"}
                    onChange={handleFilter}
                    trigger={
                      <button
                        type="button"
                        className="ml-3 inline-flex outline-none"
                        aria-label={t("fileStatusFilterLabel", {
                          value: t(
                            onlyAbnormal
                              ? "fileStatusAbnormal"
                              : "fileStatusFilterAll",
                          ),
                        })}
                      >
                        <Outlined.Filter
                          size={16}
                          aria-hidden
                          className={
                            onlyAbnormal ? "text-primary" : "text-gray-400"
                          }
                        />
                      </button>
                    }
                  />
                </div>
              </TableHead>
              <TableHead className="text-right">{t("operations")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.id}
                onClick={() => {
                  void handleRead(row);
                }}
              >
                <TableCell className="max-w-[200px] font-medium">
                  <div className="flex items-center gap-2">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-fill-2 text-text-2">
                      <Outlined.Books size={16} aria-hidden="true" />
                    </div>
                    <div>
                      <div className="w-[264px] max-w-[500px] truncate pt-2 text-sm font-medium">
                        {row.name}
                      </div>
                      <KnowledgeTooltip
                        side="top"
                        content={row.description || ""}
                      >
                        <div className="max-w-[500px] truncate pt-1 text-xs text-text-2">
                          {row.description || ""}
                        </div>
                      </KnowledgeTooltip>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-text-2">
                  {row.update_time?.replace("T", " ") || "--"}
                </TableCell>
                <TableCell className="max-w-[300px] break-all text-text-2">
                  {row.user_name || "--"}
                </TableCell>
                <TableCell>
                  <FileAbnormalStatusCell
                    hasAbnormalFiles={row.has_abnormal_files}
                  />
                </TableCell>
                <TableCell className="text-right">
                  <span
                    className="contents"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <Dropdown
                      align="end"
                      open={openId === String(row.id)}
                      onOpenChange={(open) => {
                        void handleMenu(row, open);
                      }}
                      menu={renderMenu(row)}
                    >
                      <Button
                        variant="text"
                        color="default"
                        size="large"
                        iconOnly
                        aria-label={t("more", { ns: "bs" })}
                      >
                        <Outlined.More />
                      </Button>
                    </Dropdown>
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!isAdmin && ordinary.hasNextPage && (
          <LoadMore
            onScrollLoad={() => {
              if (!ordinary.isFetchingNextPage)
                void ordinary.fetchNextPage().catch((error) => {
                  if (live.current === epoch) showApiError(error);
                });
            }}
          />
        )}
        {isAdmin && admin.data && (
          <Pagination
            locale={paginationLocale}
            current={page}
            pageSize={pageSize}
            total={admin.data.total}
            showTotal
            showSizeChanger
            onChange={(next, size) => {
              setPage(next);
              setPageSize(size);
            }}
          />
        )}
      </div>
      <KnowledgeDeletionDialog operation={deletion} />
      <KnowledgeLibraryDialog
        scope={scope}
        datalist={rows}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onLoadEnd={handleRefresh}
      />
      {editTarget && (
        <KnowledgeLibraryDialog
          scope={scope}
          datalist={rows}
          currentLib={{ id: editTarget.id, name: editTarget.name }}
          mode="edit"
          open
          onOpenChange={(open) => {
            if (!open) setEditTarget(null);
          }}
          onLoadEnd={handleRefresh}
        />
      )}
      {defaultsTarget && (
        <ProcessingDefaultsDialog
          scope={scope}
          spaceId={defaultsTarget.id}
          open
          onOpenChange={(open) => {
            if (!open) setDefaultsTarget(null);
          }}
        />
      )}
      {permissionTarget && (
        <PermissionDialog
          resourceType="knowledge_space"
          resourceId={String(permissionTarget.id)}
          resourceName={permissionTarget.name}
          open
          onOpenChange={(open) => {
            if (!open) setPermissionTarget(null);
          }}
        />
      )}
    </div>
  );
}
