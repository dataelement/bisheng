import WebLinkImportDialog from "./WebLinkImportDialog";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import { useKnowledgeBatch } from "../hooks/useKnowledgeBatch";
import { BatchOperationDialog } from "./BatchOperationDialog";
import { BatchTagDraftDialog } from "./BatchTagDraftDialog";
import { MoveDialog } from "./MoveDialog";
import type { MoveSelection } from "@/controllers/API/knowledgeMove";
import { Button, EmptyStateIllustration, StateView, toast } from "@bisheng/ui";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { knowledgeSpaceApi, type KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { knowledgeFilesApi, type SpaceFilePreview } from "@/controllers/API/knowledgeFiles";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { isErrorEnvelope } from "@bisheng/api-client";
import { SpaceDirectoryOverlays } from "./SpaceDirectoryOverlays";
import { SpaceDirectoryLoading } from "./SpaceDirectoryLoading";
import { SpaceDirectoryLoadMore } from "./SpaceDirectoryLoadMore";
import { KnowledgeScopeUnavailable } from "./KnowledgeScopeUnavailable";
import { KnowledgeDeletionDialog } from "./KnowledgeDeletionDialog";
import { useDirectoryDeletion } from "../hooks/useDirectoryDeletion";
import { useDirectoryDownloadPermissions } from "../hooks/useDirectoryDownloadPermissions";
import { useDirectorySelectionActions } from "../hooks/useDirectorySelectionActions";
import { SpaceDirectoryRow } from "./SpaceDirectoryRow";
import { SpaceDirectoryToolbar } from "./SpaceDirectoryToolbar";
import { SpaceDirectoryView, type DirectorySortField, type DirectoryViewMode } from "./SpaceDirectoryView";
import { useWorkspaceViewMode } from "./useWorkspaceViewMode";
export { StatusIndicator } from "./KnowledgeFileStatus";
export interface FilesProps {
  toolbarTarget?: HTMLDivElement | null;
  presentation?: "workspace";
  scope?: KnowledgeQueryScope;
  spaceId?: number;
  parentId?: number | null;
  onOpenFolder?: (id: number) => void;
  onOpenFile?: (item: KnowledgeSpaceChild) => void;
  // The old route is migrated separately; its flags never authorize SPACE rows.
  onPreview?: (id: string) => void;
  canEditKb?: boolean;
  canDeleteKb?: boolean;
}
interface DirectoryProps extends FilesProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
}
type Epoch = { prefix: readonly unknown[] };
type RowLifetime = { retired: boolean };
type Target = Edit & { item: KnowledgeSpaceChild };
type Menu = {
  token: Target;
  actions: string[];
  loading: boolean;
  error: boolean;
};
type Edit = {
  epoch: Epoch;
  item?: KnowledgeSpaceChild;
  rowLifetime?: RowLifetime;
};
type Preview = { token: Target; data?: SpaceFilePreview };
const validId = (id: unknown): id is number =>
  typeof id === "number" && Number.isSafeInteger(id) && id > 0;
const rowKey = (item: KnowledgeSpaceChild) => `${item.file_type}:${item.id}`;
export default function Files(props: FilesProps) {
  const { scope, spaceId, parentId } = props;
  if (
    !scope ||
    !validId(scope.tenantId) ||
    !validId(spaceId) ||
    (parentId != null && !validId(parentId))
  )
    return <KnowledgeScopeUnavailable />;
  return (
    <Directory
      key={JSON.stringify([
        scope.identityKey,
        scope.tenantId,
        scope.managementTenantId,
        scope.view,
        spaceId,
        parentId ?? null,
        props.presentation,
      ])}
      {...props}
      scope={scope}
      spaceId={spaceId}
    />
  );
}
function Directory({ scope, spaceId, parentId: initialParent, onOpenFolder, presentation, toolbarTarget, onOpenFile }: DirectoryProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const instance = useId(),
    sequence = useRef(0);
  const [searchParams] = useSearchParams();
  const [parentId, setParentId] = useState(initialParent ?? null);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [viewMode, setViewMode] = useWorkspaceViewMode(scope, presentation === "workspace");
  const [sortField, setSortField] = useState<DirectorySortField>("file_type");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [statuses, setStatuses] = useState<number[]>(() =>
    searchParams.get("fileStatus") === "abnormal" ? [3, 6, 7] : [],
  );
  const [draftStatuses, setDraftStatuses] = useState(statuses);
  const [filterOpen, setFilterOpen] = useState(false);
  const { identityKey, tenantId, managementTenantId, view } = scope;
  const base = useMemo(
    () => knowledgeQueryKeys.space({ identityKey, tenantId, managementTenantId, view }, spaceId),
    [identityKey, tenantId, managementTenantId, view, spaceId],
  );
  const epoch = useMemo(
    () => ({
      prefix: [
        ...base,
        "directory",
        instance,
        ++sequence.current,
        parentId,
        keyword,
        statuses,
        page,
        sortField,
        sortDirection,
      ],
    }),
    [base, instance, parentId, keyword, statuses, page, sortField, sortDirection],
  );
  const current = useRef<Epoch | null>(epoch);
  current.current = epoch;
  const isDirectoryCurrent = useCallback(() => current.current === epoch, [epoch]);
  const menuToken = useRef<Target | null>(null),
    editToken = useRef<Edit | null>(null),
    previewToken = useRef<Target | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState<Edit | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [container, setContainer] = useState<{
    epoch: Epoch;
    actions: string[];
  } | null>(null);
  useEffect(
    () => () => {
      if (current.current === epoch) current.current = null;
      if (menuToken.current?.epoch === epoch) menuToken.current = null;
      if (editToken.current?.epoch === epoch) editToken.current = null;
      if (previewToken.current?.epoch === epoch) previewToken.current = null;
    },
    [epoch],
  );
  const filters = statuses.length ? { file_status: statuses } : {};
  const sorting = presentation === "workspace" ? { order_field: sortField, order_sort: sortDirection } : {};
  const ordinary = useInfiniteQuery({
    queryKey: [...epoch.prefix, "children"],
    queryFn: async ({ pageParam }) => {
      const result = await knowledgeSpaceApi.listChildren(spaceId, {
        parent_id: parentId,
        page_size: 40,
        ...filters,
        ...sorting,
        ...(typeof pageParam === "string" ? { cursor: pageParam } : {}),
      });
      if (presentation === "workspace" && typeof pageParam === "string" && result.has_more && result.next_cursor === pageParam)
        throw new Error("Knowledge directory pagination cursor did not advance");
      return result;
    },
    getNextPageParam: (result) => (result.has_more ? (result.next_cursor ?? undefined) : undefined),
    enabled: !keyword,
    keepPreviousData: false,
    cacheTime: 0,
  });
  const search = useQuery({
    queryKey: [...epoch.prefix, "search"],
    queryFn: () =>
      knowledgeFilesApi.searchSpaceChildren(spaceId, {
        parent_id: parentId,
        keyword,
        page,
        page_size: 40,
        ...filters,
        ...sorting,
      }),
    enabled: !!keyword,
    keepPreviousData: false,
    cacheTime: 0,
  });
  const active = keyword ? search : ordinary;
  const hasMore = keyword ? search.data?.has_more : ordinary.hasNextPage;
  const rows = useMemo(
    () => [
      ...new Map(
        (keyword
          ? (search.data?.data ?? [])
          : (ordinary.data?.pages.flatMap((result) => result.data) ?? [])
        ).map((item) => [item.id, item]),
      ).values(),
    ],
    [keyword, search.data, ordinary.data],
  );
  const downloadIds = useDirectoryDownloadPermissions({
    prefix: epoch.prefix,
    spaceId,
    pages: keyword ? (search.data ? [search.data] : []) : (ordinary.data?.pages ?? []),
  });
  const rowLifetimes = useRef(new Map<string, RowLifetime>());
  const rowKeys = new Set(rows.map(rowKey));
  for (const [key, lifetime] of rowLifetimes.current) {
    if (!rowKeys.has(key)) {
      lifetime.retired = true;
      rowLifetimes.current.delete(key);
    }
  }
  for (const key of rowKeys)
    if (!rowLifetimes.current.has(key)) rowLifetimes.current.set(key, { retired: false });
  const isCurrent = (token: Edit | Target) =>
    current.current === token.epoch &&
    (!token.item || (!!token.rowLifetime && !token.rowLifetime.retired));
  useEffect(() => {
    for (const ref of [menuToken, editToken, previewToken])
      if (ref.current?.rowLifetime?.retired) ref.current = null;
    setMenu((value) => (value?.token.rowLifetime?.retired ? null : value));
    setEdit((value) => (value?.rowLifetime?.retired ? null : value));
    setPreview((value) => (value?.token.rowLifetime?.retired ? null : value));
  }, [rows]);
  useEffect(() => {
    if (active.error) showApiError(active.error);
  }, [active.error]);
  useEffect(() => {
    const type = parentId === null ? "knowledge_space" : "folder";
    void getMyResourcePermissionsApi(type, String(parentId ?? spaceId), { showError: false })
      .then((result) => {
        if (current.current === epoch) setContainer({ epoch, actions: result.actions });
      })
      .catch((error) => {
        if (current.current === epoch && !(isErrorEnvelope(error) && error.status_code === 25022))
          showApiError(error);
      });
  }, [epoch, parentId, spaceId]);

  const handleMenu = async (item: KnowledgeSpaceChild, open: boolean) => {
    if (!open) {
      menuToken.current = null;
      setMenu(null);
      return;
    }
    if (item.file_type !== 0 && item.file_type !== 1) return;
    const rowLifetime = rowLifetimes.current.get(rowKey(item));
    if (!rowLifetime || current.current !== epoch) return;
    const token = { epoch, item, rowLifetime };
    menuToken.current = token;
    setMenu({ token, actions: [], loading: true, error: false });
    try {
      const result = await getMyResourcePermissionsApi(
        item.file_type === 0 ? "folder" : "knowledge_file",
        String(item.id),
      );
      if (menuToken.current === token && isCurrent(token))
        setMenu({
          token,
          actions: result.actions,
          loading: false,
          error: false,
        });
    } catch (error) {
      if (menuToken.current === token && isCurrent(token)) {
        setMenu({ token, actions: [], loading: false, error: true });
        showApiError(error);
      }
    }
  };
  const closeEdit = () => {
    editToken.current = null;
    setEdit(null);
  };
  const handleEdit = (item?: KnowledgeSpaceChild) => {
    if (
      item &&
      !(menu?.token.item.id === item.id && menu.actions.includes("rename") && isCurrent(menu.token))
    )
      return;
    if (!item && !(container?.epoch === epoch && container.actions.includes("create_folder")))
      return;
    const token = {
      epoch,
      item,
      rowLifetime: item ? rowLifetimes.current.get(rowKey(item)) : undefined,
    };
    editToken.current = token;
    setEdit(token);
    setName(item?.file_name ?? "");
    menuToken.current = null;
    setMenu(null);
  };
  const handleSave = async () => {
    const token = editToken.current;
    if (!token || !isCurrent(token) || saving === token || !name.trim()) return;
    const body = { name };
    setSaving(token);
    try {
      if (!token.item)
        await knowledgeFilesApi.createSpaceFolder(spaceId, {
          ...body,
          ...(parentId === null ? {} : { parent_id: parentId }),
        });
      else if (token.item.file_type === 0)
        await knowledgeFilesApi.renameSpaceFolder(spaceId, token.item.id, body);
      else await knowledgeFilesApi.renameSpaceFile(spaceId, token.item.id, body);
      if (editToken.current !== token || !isCurrent(token)) return;
      // Report the write as soon as it lands: the refreshed list may drop this
      // row (current search/filter), which would otherwise end the flow silently.
      toast.show({
        type: "success",
        message: t(token.item ? "renameSuccess" : "f118.folder_created"),
      });
      await client.invalidateQueries({ queryKey: base });
      if (editToken.current === token && isCurrent(token)) closeEdit();
    } catch (error) {
      if (editToken.current === token && isCurrent(token)) showApiError(error);
    } finally {
      if (editToken.current === token && isCurrent(token)) setSaving(null);
    }
  };
  const closePreview = () => {
    previewToken.current = null;
    setPreview(null);
  };
  const handlePreview = async (item: KnowledgeSpaceChild) => {
    if (onOpenFile) { onOpenFile(item); return; }
    const rowLifetime = rowLifetimes.current.get(rowKey(item));
    if (!rowLifetime || current.current !== epoch) return;
    const token = { epoch, item, rowLifetime };
    previewToken.current = token;
    setPreview({ token });
    try {
      const data = await knowledgeFilesApi.getSpaceFilePreview(spaceId, item.id);
      if (previewToken.current === token && isCurrent(token)) setPreview({ token, data });
    } catch (error) {
      if (previewToken.current === token && isCurrent(token)) {
        closePreview();
        showApiError(error);
      }
    }
  };
  const handleDownload = async (item: KnowledgeSpaceChild) => {
    const token = { epoch, item, rowLifetime: rowLifetimes.current.get(rowKey(item)) };
    if (item.file_type !== 1 || !downloadIds.has(item.id) || !isCurrent(token)) return;
    try {
      const data = await knowledgeFilesApi.getSpaceFileDownload(spaceId, item.id);
      if (!isCurrent(token) || !data.original_url) return;
      const anchor = document.createElement("a");
      anchor.href = data.original_url;
      anchor.download = item.file_name;
      anchor.rel = "noopener";
      anchor.click();
      anchor.remove();
    } catch (error) {
      if (isCurrent(token)) showApiError(error);
    }
  };
  const visibleEdit = edit && isCurrent(edit) ? edit : null;
  const visiblePreview = preview && isCurrent(preview.token) ? preview : null;
  const {
    deletion,
    selectedKeys,
    selectedRows,
    selectionError,
    handleSelection,
    remove,
    references,
  } = useDirectoryDeletion({
    spaceId,
    epoch,
    scopeKey: JSON.stringify([...base, parentId, keyword, statuses, page, sortField, sortDirection]),
    rows,
    isCurrent: isDirectoryCurrent,
    onDeleted: () => client.invalidateQueries({ queryKey: base }),
  });
  const selectedActions = useDirectorySelectionActions({ prefix: epoch.prefix, rows: selectedRows });
  const batch = useKnowledgeBatch(JSON.stringify([...base, parentId, selectedKeys]));
  const [batchTagsOpen, setBatchTagsOpen] = useState(false);
  const [move, setMove] = useState<MoveSelection[] | null>(null);
  const [webLinkOpen, setWebLinkOpen] = useState(false);
  const runBatch = async (
    operation: "download" | "tag" | "retry",
    tag_ids?: number[],
    new_tag_names?: string[],
    items = selectedRows,
  ) => {
    setBatchTagsOpen(false);
    const outcome = await batch.open({
      spaceId,
      operation,
      items: items.map((item) => ({
        id: item.id,
        type: item.file_type === 0 ? "folder" : "file",
        name: item.file_name,
      })),
      ...(operation === "tag" ? { tag_ids, new_tag_names } : {}),
    });
    if (outcome && current.current === epoch && operation !== "download")
      await client.invalidateQueries({ queryKey: base });
  };
  const containerActions = container?.epoch === epoch ? container.actions : [];
  const renderRow = (item: KnowledgeSpaceChild, layout?: DirectoryViewMode) => {
    const itemMenu =
      menu && menu.token.epoch === epoch && menu.token.item.id === item.id ? menu : null;
    return (
      <SpaceDirectoryRow
        key={item.id}
        layout={layout}
        scope={scope}
        spaceId={spaceId}
        parentId={parentId}
        item={item}
        open={!!itemMenu}
        actions={itemMenu?.actions ?? []}
        loading={itemMenu?.loading ?? false}
        error={itemMenu?.error ?? false}
        onMenu={(open) => {
          void handleMenu(item, open);
        }}
        selected={selectedKeys.includes(rowKey(item))}
        onSelect={(checked) => {
          void handleSelection(item, checked);
        }}
        onDelete={() => {
          if (itemMenu?.actions.includes("delete") && isCurrent(itemMenu.token))
            void remove([item]);
        }}
        onReferences={() => {
          if (itemMenu?.actions.includes("delete") && isCurrent(itemMenu.token))
            references([item]);
        }}
        onRename={() => handleEdit(item)}
        onMove={() => setMove([{ id: item.id, type: item.file_type === 0 ? "folder" : "file" }])}
        onRetry={() => { void runBatch("retry", undefined, undefined, [item]); }}
        onChanged={() => client.invalidateQueries({ queryKey: base })}
        canDownload={downloadIds.has(item.id)}
        onDownload={() => {
          void handleDownload(item);
        }}
        onOpen={() => {
          if (onOpenFolder) onOpenFolder(item.id);
          else {
            setParentId(item.id);
            setKeyword("");
            setPage(1);
          }
        }}
        onPreview={() => {
          void handlePreview(item);
        }}
      />
    );
  };
  const workspace = presentation === "workspace";
  const scrollPaging = workspace && !keyword && ordinary.hasNextPage;
  const directoryEmpty = !active.isInitialLoading && !active.error && !rows.length && !hasMore;
  const directoryStatus = (
    <>
      {active.isInitialLoading && <SpaceDirectoryLoading fill={workspace} />}
      {directoryEmpty && (workspace ? (
        <StateView size="page" title={t("f118.directory_empty")} image={<EmptyStateIllustration />} />
      ) : <p>{t("f118.directory_empty")}</p>)}
      {!!active.error && !scrollPaging && (
        <Button
          className={workspace ? "mx-4 my-2" : undefined}
          onClick={() => void active.refetch()}
        >
          {t("retry")}
        </Button>
      )}
      {scrollPaging ? (
        <SpaceDirectoryLoadMore key={sequence.current} directory={ordinary} isCurrent={isDirectoryCurrent} />
      ) : !keyword && ordinary.hasNextPage && (
        <Button
          disabled={ordinary.isFetchingNextPage}
          onClick={() => void ordinary.fetchNextPage()}
        >
          {t("f118.more_files")}
        </Button>
      )}
      {!!keyword && (
        <div className={`flex justify-end gap-2${workspace ? " p-4" : ""}`}>
          <Button
            disabled={page === 1 || search.isFetching}
            onClick={() => setPage((value) => value - 1)}
          >
            {t("pagination.prev", { ns: "bs" })}
          </Button>
          <Button
            disabled={!search.data?.has_more || search.isFetching}
            onClick={() => setPage((value) => value + 1)}
          >
            {t("pagination.next", { ns: "bs" })}
          </Button>
        </div>
      )}
    </>
  );
  return (
    <div className={workspace ? "relative flex min-h-0 min-w-0 flex-1 flex-col" : "relative space-y-4"}>
      {move && <MoveDialog scope={scope} spaceId={spaceId} parentId={parentId} items={move} onClose={() => setMove(null)} />}
      {selectionError === epoch && <p role="alert">{t("deletion.reason_no_permission")}</p>}
      <SpaceDirectoryToolbar
        toolbarTarget={toolbarTarget}
        compact={workspace}
        spaceId={spaceId}
        parentId={parentId}
        keyword={keyword}
        onKeywordChange={(value) => {
          setKeyword(value);
          setPage(1);
        }}
        canCreateFolder={containerActions.includes("create_folder")}
        onCreateFolder={() => handleEdit()}
        canUpload={containerActions.includes("upload_file")}
        onWebLink={() => setWebLinkOpen(true)}
        onBatchDownload={selectedActions.canDownload ? () => {
          void runBatch("download");
        } : undefined}
        onBatchRetry={selectedActions.canRetry ? () => {
          void runBatch("retry");
        } : undefined}
        onBatchTag={selectedActions.canTag ? () => setBatchTagsOpen(true) : undefined}
        onMove={selectedActions.canMove ? () => setMove(selectedRows.map(item => ({ id: item.id, type: item.file_type === 0 ? "folder" : "file" }))) : undefined}
        selectedCount={selectedRows.length}
        onDeleteSelected={selectedActions.canDelete ? () => {
          void remove(selectedRows);
        } : undefined}
        onReferences={selectedActions.canDelete ? () => references(selectedRows) : undefined}
      />
      <SpaceDirectoryView
        workspace={workspace}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        sortField={sortField}
        sortDirection={sortDirection}
        onSort={field => {
          setSortDirection(field === sortField ? (sortDirection === "asc" ? "desc" : "asc") : field === "file_name" ? "asc" : "desc");
          setSortField(field);
          setPage(1);
        }}
        keyword={keyword}
        onKeywordChange={value => { setKeyword(value); setPage(1); }}
        allSelected={rows.some(item => item.file_type === 0 || item.file_type === 1) && rows.every(item => (item.file_type !== 0 && item.file_type !== 1) || selectedKeys.includes(rowKey(item)))}
        someSelected={selectedKeys.length > 0}
        canSelect={rows.some(item => item.file_type === 0 || item.file_type === 1)}
        onSelectAll={checked => rows.filter(item => item.file_type === 0 || item.file_type === 1).forEach(item => handleSelection(item, checked))}
        filter={{
          open: filterOpen,
          onOpenChange: setFilterOpen,
          selected: statuses,
          draft: draftStatuses,
          onDraftChange: setDraftStatuses,
          onApply: () => { setStatuses([...draftStatuses]); setPage(1); setFilterOpen(false); },
          onReset: () => { setStatuses([]); setDraftStatuses([]); setPage(1); setFilterOpen(false); },
        }}
        rows={rows}
        renderRow={renderRow}
        footer={workspace ? directoryStatus : undefined}
      />
      {!workspace && directoryStatus}
      <SpaceDirectoryOverlays
        instance={instance}
        editOpen={!!visibleEdit}
        editingItem={visibleEdit?.item}
        name={name}
        setName={setName}
        saving={saving === visibleEdit}
        closeEdit={closeEdit}
        handleSave={handleSave}
        previewOpen={!!visiblePreview}
        previewItem={visiblePreview?.token.item}
        previewData={visiblePreview?.data}
        closePreview={closePreview}
      />
      <WebLinkImportDialog
        knowledgeId={String(spaceId)} parentId={parentId}
        scopeKey={JSON.stringify([...base, parentId])}
        open={knowledgeUploadCapabilities.webLink && webLinkOpen && containerActions.includes("upload_file")}
        onOpenChange={setWebLinkOpen}
        onImported={() => { void client.invalidateQueries({ queryKey: base }); }}
      />
      <KnowledgeDeletionDialog operation={deletion} />
      <BatchOperationDialog operation={batch} />
      <BatchTagDraftDialog
        spaceId={spaceId}
        availableTags={selectedRows.flatMap((item) => item.tags ?? [])}
        open={batchTagsOpen && selectedActions.canTag}
        onClose={() => setBatchTagsOpen(false)}
        onReview={(ids, names) => {
          void runBatch("tag", ids, names);
        }}
      />
    </div>
  );
}
