import WebLinkImportDialog from "./WebLinkImportDialog";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import { useKnowledgeBatch } from "../hooks/useKnowledgeBatch";
import { BatchOperationDialog } from "./BatchOperationDialog";
import { BatchTagDraftDialog } from "./BatchTagDraftDialog";
import { Button } from "@bisheng/ui";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { knowledgeSpaceApi, type KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { knowledgeFilesApi, type SpaceFilePreview } from "@/controllers/API/knowledgeFiles";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { FileStatusFilter } from "./FileStatusFilter";
import { SpaceDirectoryOverlays } from "./SpaceDirectoryOverlays";
import { KnowledgeDeletionDialog } from "./KnowledgeDeletionDialog";
import { useDirectoryDeletion } from "../hooks/useDirectoryDeletion";
import { SpaceDirectoryRow } from "./SpaceDirectoryRow";
import { SpaceDirectoryToolbar } from "./SpaceDirectoryToolbar";
export { StatusIndicator } from "./KnowledgeFileStatus";
export interface FilesProps {
  scope?: KnowledgeQueryScope;
  spaceId?: number;
  parentId?: number | null;
  onOpenFolder?: (id: number) => void;
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
  const { t } = useTranslation("knowledge");
  const { scope, spaceId, parentId } = props;
  if (
    !scope ||
    !validId(spaceId) ||
    !validId(scope.tenantId) ||
    (parentId != null && !validId(parentId))
  )
    return <div role="status">{t("f118.scope_unavailable")}</div>;
  return (
    <Directory
      key={JSON.stringify([
        scope.identityKey,
        scope.tenantId,
        scope.managementTenantId,
        scope.view,
        spaceId,
        parentId ?? null,
      ])}
      {...props}
      scope={scope}
      spaceId={spaceId}
    />
  );
}
function Directory({ scope, spaceId, parentId: initialParent, onOpenFolder }: DirectoryProps) {
  const { t } = useTranslation("knowledge");
  const client = useQueryClient();
  const instance = useId(),
    sequence = useRef(0);
  const [searchParams] = useSearchParams();
  const [parentId, setParentId] = useState(initialParent ?? null);
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
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
      ],
    }),
    [base, instance, parentId, keyword, statuses, page],
  );
  const current = useRef<Epoch | null>(epoch);
  current.current = epoch;
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
  const ordinary = useInfiniteQuery({
    queryKey: [...epoch.prefix, "children"],
    queryFn: ({ pageParam }) =>
      knowledgeSpaceApi.listChildren(spaceId, {
        parent_id: parentId,
        page_size: 40,
        ...filters,
        ...(typeof pageParam === "string" ? { cursor: pageParam } : {}),
      }),
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
    void getMyResourcePermissionsApi(type, String(parentId ?? spaceId))
      .then((result) => {
        if (current.current === epoch) setContainer({ epoch, actions: result.actions });
      })
      .catch((error) => {
        if (current.current === epoch) showApiError(error);
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
      await client.invalidateQueries({ queryKey: token.epoch.prefix });
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
    const token = menu?.token;
    if (
      !token ||
      token.item.id !== item.id ||
      !menu.actions.includes("download") ||
      !isCurrent(token)
    )
      return;
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
    scopeKey: JSON.stringify([...base, parentId, keyword, statuses, page]),
    rows,
    isCurrent: () => current.current === epoch,
    onDeleted: () => client.invalidateQueries({ queryKey: base }),
  });
  const batch = useKnowledgeBatch(JSON.stringify([...base, parentId, selectedKeys]));
  const [batchTagsOpen, setBatchTagsOpen] = useState(false);
  const [webLinkOpen, setWebLinkOpen] = useState(false);
  const runBatch = async (
    operation: "download" | "tag" | "retry",
    tag_ids?: number[],
    new_tag_names?: string[],
  ) => {
    setBatchTagsOpen(false);
    const outcome = await batch.open({
      spaceId,
      operation,
      items: selectedRows.map((item) => ({
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
  return (
    <div className="relative space-y-4">
      {selectionError === epoch && <p role="alert">{t("deletion.reason_no_permission")}</p>}
      <SpaceDirectoryToolbar
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
        onBatchDownload={() => {
          void runBatch("download");
        }}
        onBatchRetry={() => {
          void runBatch("retry");
        }}
        onBatchTag={() => setBatchTagsOpen(true)}
        selectedCount={selectedRows.length}
        onDeleteSelected={() => {
          void remove(selectedRows);
        }}
        onReferences={selectedRows.length ? () => references(selectedRows) : undefined}
      />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("fileName")}</TableHead>
            <TableHead>{t("updateTime")}</TableHead>
            <TableHead>
              <span className="inline-flex items-center gap-1">
                {t("status")}
                <FileStatusFilter
                  open={filterOpen}
                  onOpenChange={setFilterOpen}
                  selected={statuses}
                  draft={draftStatuses}
                  onDraftChange={setDraftStatuses}
                  onApply={() => {
                    setStatuses([...draftStatuses]);
                    setPage(1);
                    setFilterOpen(false);
                  }}
                  onReset={() => {
                    setStatuses([]);
                    setDraftStatuses([]);
                    setPage(1);
                    setFilterOpen(false);
                  }}
                />
              </span>
            </TableHead>
            <TableHead className="text-right">{t("operations")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((item) => {
            const itemMenu =
              menu && menu.token.epoch === epoch && menu.token.item.id === item.id ? menu : null;
            return (
              <SpaceDirectoryRow
                key={item.id}
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
          })}
        </TableBody>
      </Table>
      {active.isInitialLoading && <p role="status">{t("f118.loading_directory")}</p>}
      {!active.isInitialLoading && !active.error && !rows.length && !hasMore && (
        <p>{t("f118.directory_empty")}</p>
      )}
      {!!active.error && (
        <Button
          onClick={() => {
            void active.refetch();
          }}
        >
          {t("retry")}
        </Button>
      )}
      {!keyword && ordinary.hasNextPage && (
        <Button
          disabled={ordinary.isFetchingNextPage}
          onClick={() => {
            void ordinary.fetchNextPage();
          }}
        >
          {t("f118.more_files")}
        </Button>
      )}
      {!!keyword && (
        <div className="flex justify-end gap-2">
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
        open={batchTagsOpen}
        onClose={() => setBatchTagsOpen(false)}
        onReview={(ids, names) => {
          void runBatch("tag", ids, names);
        }}
      />
    </div>
  );
}
