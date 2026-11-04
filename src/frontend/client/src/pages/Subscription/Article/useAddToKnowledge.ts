import { useLocalize, useScrollRevealRef } from "~/hooks";
import useMediaQuery from "~/hooks/useMediaQuery";
import { useCallback, useEffect, useRef, useState } from "react";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { generateUUID, getFullWidthLength } from "~/utils";
import {
  getManagedSpacesApi,
  getMineSpacesApi,
  getSpaceChildrenApi,
  createFolderApi,
  addArticleToKnowledgeApi,
  FileType,
} from "~/api/knowledge";
import { mapTree, filterTree, findNode } from "./KnowledgePickerTree";
import type {
  KnowledgeNode,
  AddToKnowledgeModalProps,
} from "./AddToKnowledgeModal";

export function useAddToKnowledge(
  {
    open,
    onOpenChange,
    articleId,
    mode = "article",
    onSyncSelect,
    dataSourceApi,
  }: AddToKnowledgeModalProps,
  localize: ReturnType<typeof useLocalize>,
  showToast: ReturnType<typeof useToastContext>["showToast"],
) {
  const treeScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const duplicateListScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const isFullScreenLayout = useMediaQuery("(max-width: 575px)");
  const isChannelSyncFullScreen = mode === "channel_sync" && isFullScreenLayout;
  const isChannelSyncCentered = mode === "channel_sync" && !isFullScreenLayout;
  const isArticleFullScreen = mode === "article" && isFullScreenLayout;
  const [tree, setTree] = useState<KnowledgeNode[]>([]);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [spacesLoading, setSpacesLoading] = useState(false);
  // Duplicate file detection state
  const [duplicateFiles, setDuplicateFiles] = useState<
    Array<{ name: string; path: string }>
  >([]);
  const [showDuplicate, setShowDuplicate] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<{
    spaceId: string;
    parentFolderId: string | null;
  } | null>(null);
  const articleDialogContentRef = useRef<HTMLDivElement | null>(null);
  const actionFooterRef = useRef<HTMLDivElement | null>(null);

  const loadOptions = useRef({ dataSourceApi, mode, localize, showToast });
  loadOptions.current = { dataSourceApi, mode, localize, showToast };

  // Filtered tree by search
  const displayTree = search.trim() ? filterTree(tree, search) : tree;
  const isSearchMode = !!search.trim();

  // ─── Load spaces list on open ──────────────────────────────
  useEffect(() => {
    if (!open) return;
    const { dataSourceApi, mode, localize, showToast } = loadOptions.current;
    setSpacesLoading(true);
    // F028: dataSourceApi (if provided by the workstation conversation-
    // export flow) takes precedence. Otherwise fall back to the mode-

    // order_by=update_time per TC-017); article keeps managed scope so
    // existing callers are untouched.
    const loader = dataSourceApi
      ? dataSourceApi()
      : mode === "channel_sync"
        ? getMineSpacesApi({ order_by: "update_time" })
        : getManagedSpacesApi();
    loader
      .then((spaces) => {
        const nodes: KnowledgeNode[] = spaces.map((s) => ({
          id: s.id,
          name: s.name,
          type: "space" as const,
          level: 1,
          parentId: null,
          spaceId: s.id,
          children: [],
          childrenLoaded: false,
        }));
        setTree(nodes);
      })
      .catch(() =>
        showToast({
          message: localize("com_subscription.load_space_list_failed"),
          severity: NotificationSeverity.WARNING,
        }),
      )
      .finally(() => setSpacesLoading(false));
  }, [open]);

  // ─── Lazy-load children on expand ─────────────────────────
  const loadChildren = useCallback(
    async (nodeId: string) => {
      const node = findNode(tree, nodeId);
      if (!node || node.childrenLoaded || node.childrenLoading) return;

      // Mark loading
      setTree((prev) =>
        mapTree(
          prev,
          (n) => n.id === nodeId,
          (n) => ({ ...n, childrenLoading: true }),
        ),
      );

      try {
        const parentId = node.type === "space" ? undefined : nodeId;
        const res = await getSpaceChildrenApi({
          space_id: node.spaceId,
          parent_id: parentId,
          page_size: 200,
        });

        // Only keep folders for the tree
        const folderChildren: KnowledgeNode[] = res.data
          .filter((f) => f.type === FileType.FOLDER)
          .map((f) => ({
            id: f.id,
            name: f.name,
            type: "folder" as const,
            level: node.level + 1,
            parentId: nodeId,
            spaceId: node.spaceId,
            children: [],
            childrenLoaded: false,
          }));

        setTree((prev) =>
          mapTree(
            prev,
            (n) => n.id === nodeId,
            (n) => ({
              ...n,
              // Merge: keep any locally-created "new-folder-*" nodes AND add API results
              children: [
                ...(n.children?.filter((c) => c.id.startsWith("new-folder-")) ??
                  []),
                ...folderChildren,
              ],
              childrenLoaded: true,
              childrenLoading: false,
            }),
          ),
        );
      } catch {
        setTree((prev) =>
          mapTree(
            prev,
            (n) => n.id === nodeId,
            (n) => ({ ...n, childrenLoading: false }),
          ),
        );
      }
    },
    [tree],
  );

  const toggleExpand = useCallback(
    (id: string) => {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
          // Trigger lazy-load
          loadChildren(id);
        }
        return next;
      });
    },
    [loadChildren],
  );

  const handleSelect = (id: string) => {
    if (editingId) return;
    setSelectedId(id);
  };

  /** Create folder via API */
  const handleAddFolder = async (
    parentId: string,
    parentLevel: number,
    spaceId: string,
  ) => {
    if (parentLevel >= 10) {
      showToast({
        message: localize("com_subscription.folder_depth_limit"),
        severity: NotificationSeverity.WARNING,
      });
      return;
    }
    const code = generateUUID(12).toLocaleUpperCase();
    const tempId = `new-folder-${Date.now()}`;
    const defaultName = localize("com_subscription.unnamed_folder_code", {
      code,
    });

    // Optimistic UI: insert a temporary node
    const tempNode: KnowledgeNode = {
      id: tempId,
      name: defaultName,
      type: "folder",
      level: parentLevel + 1,
      parentId,
      spaceId,
      children: [],
      childrenLoaded: true,
    };

    setTree((prev) =>
      mapTree(
        prev,
        (n) => n.id === parentId,
        (n) => ({
          ...n,
          children: [...(n.children ?? []), tempNode],
        }),
      ),
    );
    setExpandedIds((prev) => new Set([...prev, parentId]));
    setEditingId(tempId);
    setSelectedId(tempId);
  };

  /** Save folder name — creates via API */
  const handleSaveEdit = async (id: string, name: string) => {
    if (getFullWidthLength(name) > 50) {
      showToast({
        message: localize("com_subscription.folder_name_too_long"),
        severity: NotificationSeverity.WARNING,
      });
      return;
    }

    const node = findNode(tree, id);
    if (!node) return;

    // If it's a newly created temp node, call createFolder API
    if (id.startsWith("new-folder-")) {
      try {
        // Determine the real parent_id: if parent is a space, parent_id is null
        const parentNode = node.parentId ? findNode(tree, node.parentId) : null;
        const apiParentId = parentNode?.type === "space" ? null : node.parentId;

        const created = await createFolderApi(node.spaceId, {
          name,
          parent_id: apiParentId,
        });

        // Replace temp node with real node
        setTree((prev) =>
          mapTree(
            prev,
            (n) => n.id === id,
            () => ({
              id: created.id,
              name: created.name || name,
              type: "folder" as const,
              level: node.level,
              parentId: node.parentId,
              spaceId: node.spaceId,
              children: [],
              childrenLoaded: true,
            }),
          ),
        );
        setSelectedId(created.id);
      } catch {
        showToast({
          message: localize("com_subscription.create_folder_failed"),
          severity: NotificationSeverity.WARNING,
        });
        // Remove the temp node
        setTree((prev) => {
          function removeNode(nodes: KnowledgeNode[]): KnowledgeNode[] {
            return nodes
              .filter((n) => n.id !== id)
              .map((n) => ({
                ...n,
                children: n.children ? removeNode(n.children) : [],
              }));
          }
          return removeNode(prev);
        });
      }
    } else {
      // Just update name in local tree (rename not needed here)
      setTree((prev) =>
        mapTree(
          prev,
          (n) => n.id === id,
          (n) => ({ ...n, name }),
        ),
      );
    }
    setEditingId(null);
  };

  /** Cancel editing (remove newly created temp node) */
  const handleCancelEdit = () => {
    if (editingId?.startsWith("new-folder-")) {
      function removeNode(nodes: KnowledgeNode[]): KnowledgeNode[] {
        return nodes
          .filter((n) => n.id !== editingId)
          .map((n) => ({
            ...n,
            children: n.children ? removeNode(n.children) : [],
          }));
      }
      setTree((prev) => removeNode(prev));
      if (selectedId === editingId) setSelectedId(null);
    }
    setEditingId(null);
  };

  /** Confirm — add article to selected space/folder */
  const handleConfirm = async (forceReplace = false) => {
    // v2.5 Module D — channel-sync mode: report selection back to caller,
    // no article upload.
    if (mode === "channel_sync") {
      if (!selectedId) return;
      const node = findNode(tree, selectedId);
      if (!node) return;
      const spaceNode = findNode(tree, node.spaceId) || node;
      // Compose folder path from ancestors (excluding the space root).
      const buildPath = (): string | null => {
        if (node.type === "space") return null;
        const chain: string[] = [];
        let cur: KnowledgeNode | null = node;
        while (cur && cur.id !== node.spaceId) {
          chain.unshift(cur.name);
          cur = cur.parentId ? (findNode(tree, cur.parentId) ?? null) : null;
        }
        return chain.length ? chain.join("/") : null;
      };
      onSyncSelect?.({
        knowledgeSpaceId: node.spaceId,
        knowledgeSpaceName: spaceNode.name || "",
        folderId: node.type === "space" ? null : selectedId,
        folderPath: buildPath(),
      });
      onOpenChange(false);
      return;
    }

    if (!articleId) return;

    // If forcing replace from the duplicate dialog, use pending params
    const spaceId =
      forceReplace && pendingConfirm
        ? pendingConfirm.spaceId
        : (() => {
            if (!selectedId) return null;
            const node = findNode(tree, selectedId);
            return node?.spaceId || null;
          })();
    const parentFolderId =
      forceReplace && pendingConfirm
        ? pendingConfirm.parentFolderId
        : (() => {
            if (!selectedId) return null;
            const node = findNode(tree, selectedId);
            if (!node) return null;
            return node.type === "space" ? null : selectedId;
          })();

    if (!spaceId) {
      setIsConfirming(false);
      return;
    }

    setIsConfirming(true);
    try {
      await addArticleToKnowledgeApi(
        spaceId,
        [String(articleId)],
        parentFolderId,
        forceReplace || undefined,
      );
      showToast({
        message: localize("com_subscription.added_to_space_success"),
        severity: NotificationSeverity.SUCCESS,
      });
      setShowDuplicate(false);
      setPendingConfirm(null);
      setDuplicateFiles([]);
      onOpenChange(false);
    } catch (err: unknown) {
      const response =
        err && typeof err === "object" && "response" in err
          ? err.response
          : undefined;
      const errData =
        response && typeof response === "object" && "data" in response
          ? response.data
          : undefined;
      const envelope =
        errData && typeof errData === "object"
          ? (errData as {
              data?: { duplicate_files?: unknown };
              duplicate_files?: unknown;
            })
          : undefined;
      const dupFiles =
        envelope?.data?.duplicate_files ?? envelope?.duplicate_files;
      if (Array.isArray(dupFiles) && dupFiles.length > 0) {
        setDuplicateFiles(
          dupFiles.map((value: unknown) => {
            const file =
              value && typeof value === "object"
                ? (value as Record<string, unknown>)
                : {};
            return {
              name: String(file.name || file.file_name || ""),
              path: String(file.path || file.file_path || ""),
            };
          }),
        );
        setPendingConfirm({ spaceId, parentFolderId });
        setShowDuplicate(true);
      }
    } finally {
      setIsConfirming(false);
    }
  };

  // Reset on close
  const handleOpenChange = (val: boolean) => {
    if (!val) {
      setSearch("");
      setSelectedId(null);
      setEditingId(null);
      setExpandedIds(new Set());
      setTree([]);
      setShowDuplicate(false);
      setDuplicateFiles([]);
      setPendingConfirm(null);
    }
    onOpenChange(val);
  };

  const isEmpty = !spacesLoading && tree.length === 0;

  const titleLabel =
    mode === "channel_sync"
      ? localize("com_subscription.select_knowledge_space")
      : localize("com_subscription.add_to_knowledge_space");

  const goBackToChannelForm = () => handleOpenChange(false);

  // Desktop centered dialogs (article + channel-sync) share the same fixed
  // h-[80vh]/max-h-[600px] shell. On short viewports a fixed-height tree pushed
  // the footer flush against the bottom edge; letting the tree flex lets it
  // shrink so the footer keeps its normal padding.
  const isChannelSyncFullScreenFooter =
    mode === "channel_sync" && isChannelSyncFullScreen;

  return {
    treeScrollRevealRef,
    duplicateListScrollRevealRef,
    isFullScreenLayout,

    isChannelSyncFullScreen,
    isChannelSyncCentered,
    isArticleFullScreen,

    search,
    setSearch,
    selectedId,
    expandedIds,
    editingId,
    isConfirming,
    spacesLoading,
    duplicateFiles,
    setDuplicateFiles,
    showDuplicate,
    setShowDuplicate,
    setPendingConfirm,
    articleDialogContentRef,
    actionFooterRef,
    displayTree,
    isSearchMode,
    toggleExpand,
    handleSelect,
    handleAddFolder,
    handleSaveEdit,
    handleCancelEdit,
    handleConfirm,
    handleOpenChange,
    isEmpty,
    titleLabel,
    goBackToChannelForm,

    isChannelSyncFullScreenFooter,
    open,
    onOpenChange,
    mode,
    localize,
  };
}
