import { readFileByLibDatabase, readFileLibDatabase } from "@/controllers/API";
import {
    getAuthorizedKnowledgeSpaceOptionsApi,
    getKnowledgeSpaceChildrenApi,
    getKnowledgeSpaceFolderStatsApi,
    KnowledgeSpaceChild,
    KnowledgeSpaceSummary,
} from "@/controllers/API/knowledgeSpace";
import { ChevronRight, Database, FileText, Folder, Loader2, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
    MAX_RUNTIME_KNOWLEDGE_FILES,
    RuntimeKnowledgeItem,
    RuntimeKnowledgeSelection,
    RuntimeKnowledgeSource,
    RuntimeKnowledgeSourceType,
} from "./userSelectedKnowledge";
import { Button } from "@/components/bs-ui/button";

interface UserSelectedKnowledgePickerProps {
    disabled?: boolean;
    value?: RuntimeKnowledgeSelection | null;
    onChange: (value: RuntimeKnowledgeSelection | null) => void;
    showConfirm?: boolean;
    confirmDisabled?: boolean;
    confirmLabel?: string;
    onConfirm?: () => void;
}

interface SourceItem extends RuntimeKnowledgeSource {
    level?: string;
}

interface ScopeItem extends RuntimeKnowledgeItem {
    isFolder: boolean;
    status?: number | string;
    successFileCount?: number;
    fileLevelPath?: string;
}

const SPACE_LEVEL_LABELS: Record<string, string> = {
    public: "公共空间",
    department: "部门空间",
    team: "团队空间",
    personal: "个人空间",
};

const toId = (value: any): number => Number(value || 0);
const sourceKey = (source: Pick<RuntimeKnowledgeSource, "source_type" | "source_id">) => `${source.source_type}-${source.source_id}`;
const itemKey = (item: RuntimeKnowledgeItem) => `${item.source_type}-${item.source_id}-${item.ref_type}-${item.id}`;
const childrenKey = (source: Pick<RuntimeKnowledgeSource, "source_type" | "source_id">, parentId?: number | null) =>
    `${sourceKey(source)}-${parentId || "root"}`;
const isSameSource = (left?: RuntimeKnowledgeSource | null, right?: RuntimeKnowledgeSource | null) =>
    !!left && !!right && left.source_type === right.source_type && Number(left.source_id) === Number(right.source_id);

function isSuccessFile(item: ScopeItem): boolean {
    return !item.isFolder && (item.status === 2 || item.status === "2" || item.status === "success" || item.status === undefined);
}

function normalizeKnowledgeFile(raw: any, source: SourceItem): ScopeItem {
    const fileType = raw.file_type ?? raw.fileType;
    const isFolder = raw.type === "folder" || Number(fileType) === 0;
    return {
        source_type: source.source_type,
        source_id: source.source_id,
        source_name: source.source_name,
        ref_type: isFolder ? "folder" : "file",
        id: toId(raw.id),
        name: raw.file_name || raw.name || "",
        isFolder,
        status: raw.status,
        fileLevelPath: raw.file_level_path ?? raw.fileLevelPath ?? "",
    };
}

function normalizeSpaceChild(raw: KnowledgeSpaceChild, source: SourceItem): ScopeItem {
    const fileType = raw.file_type;
    const isFolder = raw.type === "folder" || fileType === 0 || fileType === "0";
    return {
        source_type: source.source_type,
        source_id: source.source_id,
        source_name: source.source_name,
        ref_type: isFolder ? "folder" : "file",
        id: toId(raw.id),
        name: raw.name || raw.file_name || "",
        isFolder,
        status: raw.status,
        successFileCount: Number(raw.visible_success_file_num ?? raw.success_file_num ?? 0),
    };
}

function knowledgeParentKey(item: ScopeItem): string {
    const parts = String(item.fileLevelPath || "").split("/").filter(Boolean);
    return parts.length ? parts[parts.length - 1] : "root";
}

function knowledgeFolderPrefix(item: ScopeItem): string {
    return `${item.fileLevelPath || ""}/${item.id}`;
}

function sortScopeItems(items: ScopeItem[]): ScopeItem[] {
    return [...items].sort((left, right) => {
        if (left.isFolder !== right.isFolder) return left.isFolder ? -1 : 1;
        return left.name.localeCompare(right.name);
    });
}

export default function UserSelectedKnowledgePicker({
    disabled,
    value,
    onChange,
    showConfirm = false,
    confirmDisabled = false,
    confirmLabel = "确认",
    onConfirm,
}: UserSelectedKnowledgePickerProps) {
    const [keyword, setKeyword] = useState("");
    const [knowledgeList, setKnowledgeList] = useState<SourceItem[]>([]);
    const [spaceList, setSpaceList] = useState<SourceItem[]>([]);
    const [activeTab, setActiveTab] = useState<RuntimeKnowledgeSourceType>(
        value?.mode === "source"
            ? value.whole_source?.source_type || "knowledge"
            : value?.items?.[0]?.source_type || "knowledge",
    );
    const [sourceLoading, setSourceLoading] = useState({ knowledge: false, space: false });
    const [childrenByKey, setChildrenByKey] = useState<Record<string, ScopeItem[]>>({});
    const [expanded, setExpanded] = useState<Record<string, boolean>>({});
    const [childrenLoading, setChildrenLoading] = useState<Record<string, boolean>>({});
    const [folderStats, setFolderStats] = useState<Record<string, number>>({});
    const [wholeSource, setWholeSource] = useState<RuntimeKnowledgeSource | null>(
        value?.mode === "source" ? value.whole_source : null,
    );
    const [selectedItems, setSelectedItems] = useState<RuntimeKnowledgeItem[]>(
        value?.mode === "items" ? value.items : [],
    );

    useEffect(() => {
        if (!value) {
            setWholeSource(null);
            setSelectedItems([]);
        }
    }, [value]);

    useEffect(() => {
        let canceled = false;
        setSourceLoading({ knowledge: true, space: true });
        readFileLibDatabase({ pageSize: 80, name: keyword, type: 0, permissionId: "use_kb" })
            .then((res) => {
                if (canceled) return;
                setKnowledgeList((res.data || []).map((item) => ({
                    source_type: "knowledge" as RuntimeKnowledgeSourceType,
                    source_id: toId(item.id),
                    source_name: item.name || "",
                })));
            })
            .finally(() => !canceled && setSourceLoading((prev) => ({ ...prev, knowledge: false })));
        getAuthorizedKnowledgeSpaceOptionsApi({ page: 1, page_size: 80, keyword, order_by: "name" })
            .then((res) => {
                if (canceled) return;
                setSpaceList((res.data || []).map((item: KnowledgeSpaceSummary) => ({
                    source_type: "space" as RuntimeKnowledgeSourceType,
                    source_id: toId(item.id),
                    source_name: item.name || "",
                    level: item.space_level || item.space_kind || "personal",
                })));
            })
            .finally(() => !canceled && setSourceLoading((prev) => ({ ...prev, space: false })));
        return () => {
            canceled = true;
        };
    }, [keyword]);

    const effectiveFileCount = useMemo(() => {
        return selectedItems.reduce((sum, item) => {
            if (item.ref_type === "file") return sum + 1;
            return sum + (folderStats[itemKey(item)] ?? 0);
        }, 0);
    }, [selectedItems, folderStats]);

    useEffect(() => {
        if (wholeSource) {
            onChange({
                mode: "source",
                whole_source: wholeSource,
                items: [],
                effective_file_count: null,
            });
            return;
        }
        if (selectedItems.length) {
            onChange({
                mode: "items",
                whole_source: null,
                items: selectedItems,
                effective_file_count: effectiveFileCount,
            });
            return;
        }
        onChange(null);
    }, [wholeSource, selectedItems, effectiveFileCount]);

    const selectedItemKeys = useMemo(() => new Set(selectedItems.map(itemKey)), [selectedItems]);
    const groupedSpaces = useMemo(() => {
        return spaceList.reduce<Record<string, SourceItem[]>>((groups, item) => {
            const key = item.level || "personal";
            groups[key] = groups[key] || [];
            groups[key].push(item);
            return groups;
        }, {});
    }, [spaceList]);

    const handleToggleWholeSource = (source: SourceItem) => {
        if (disabled) return;
        const runtimeSource: RuntimeKnowledgeSource = {
            source_type: source.source_type,
            source_id: source.source_id,
            source_name: source.source_name,
        };
        setWholeSource((prev) => isSameSource(prev, runtimeSource) ? null : runtimeSource);
        setSelectedItems([]);
    };

    const handleChangeTab = (tab: RuntimeKnowledgeSourceType) => {
        if (disabled || tab === activeTab) return;
        setActiveTab(tab);
        setWholeSource(null);
        setSelectedItems([]);
    };

    const handleToggleItem = (item: ScopeItem) => {
        if (disabled || (!item.isFolder && !isSuccessFile(item))) return;
        const runtimeItem: RuntimeKnowledgeItem = {
            source_type: item.source_type,
            source_id: item.source_id,
            source_name: item.source_name,
            ref_type: item.ref_type,
            id: item.id,
            name: item.name,
        };
        setWholeSource(null);
        setSelectedItems((prev) => {
            const key = itemKey(runtimeItem);
            return prev.some((one) => itemKey(one) === key)
                ? prev.filter((one) => itemKey(one) !== key)
                : [...prev, runtimeItem];
        });
    };

    const loadKnowledgeChildren = (source: SourceItem) => {
        const rootKey = childrenKey(source, null);
        if (childrenByKey[rootKey] || childrenLoading[rootKey]) return;
        setChildrenLoading((prev) => ({ ...prev, [rootKey]: true }));
        readFileByLibDatabase({ id: source.source_id, page: 1, pageSize: 1000 } as any)
            .then((res) => {
                const items = (res.data || [])
                    .map((raw) => normalizeKnowledgeFile(raw, source))
                    .filter((item) => item.isFolder || isSuccessFile(item));
                const nextChildren: Record<string, ScopeItem[]> = {};
                items.forEach((item) => {
                    const parent = knowledgeParentKey(item);
                    const key = parent === "root" ? rootKey : childrenKey(source, Number(parent));
                    nextChildren[key] = nextChildren[key] || [];
                    nextChildren[key].push(item);
                });
                const nextStats: Record<string, number> = {};
                items.filter((item) => item.isFolder).forEach((folder) => {
                    const prefix = knowledgeFolderPrefix(folder);
                    nextStats[itemKey(folder)] = items.filter((item) =>
                        !item.isFolder
                        && isSuccessFile(item)
                        && (item.fileLevelPath === prefix || String(item.fileLevelPath || "").startsWith(`${prefix}/`))
                    ).length;
                });
                Object.keys(nextChildren).forEach((key) => {
                    nextChildren[key] = sortScopeItems(nextChildren[key]);
                });
                setChildrenByKey((prev) => ({ ...prev, ...nextChildren, [rootKey]: nextChildren[rootKey] || [] }));
                setFolderStats((prev) => ({ ...prev, ...nextStats }));
            })
            .finally(() => setChildrenLoading((prev) => ({ ...prev, [rootKey]: false })));
    };

    const loadSpaceChildren = (source: SourceItem, parentId: number | null) => {
        const key = childrenKey(source, parentId);
        if (childrenByKey[key] || childrenLoading[key]) return;
        setChildrenLoading((prev) => ({ ...prev, [key]: true }));
        getKnowledgeSpaceChildrenApi({
            space_id: source.source_id,
            parent_id: parentId,
            page_size: 100,
            order_field: "file_type",
            order_sort: "asc",
        })
            .then((res) => {
                const items = (res.data || []).map((raw) => normalizeSpaceChild(raw, source));
                setChildrenByKey((prev) => ({ ...prev, [key]: sortScopeItems(items) }));
                const folders = items.filter((item) => item.isFolder);
                if (folders.length) {
                    getKnowledgeSpaceFolderStatsApi({
                        space_id: source.source_id,
                        folder_ids: folders.map((item) => item.id),
                    }).then((stats) => {
                        setFolderStats((prev) => ({
                            ...prev,
                            ...Object.fromEntries(stats.map((item) => [
                                itemKey({
                                    source_type: source.source_type,
                                    source_id: source.source_id,
                                    source_name: source.source_name,
                                    ref_type: "folder",
                                    id: Number(item.folder_id),
                                    name: "",
                                }),
                                Number(item.visible_success_file_num || item.success_file_num || 0),
                            ])),
                        }));
                    });
                }
            })
            .finally(() => setChildrenLoading((prev) => ({ ...prev, [key]: false })));
    };

    const handleToggleExpandSource = (source: SourceItem) => {
        const key = sourceKey(source);
        const next = !expanded[key];
        setExpanded((prev) => ({ ...prev, [key]: next }));
        if (!next) return;
        if (source.source_type === "knowledge") {
            loadKnowledgeChildren(source);
        } else {
            loadSpaceChildren(source, null);
        }
    };

    const handleToggleExpandFolder = (item: ScopeItem) => {
        const key = itemKey(item);
        const next = !expanded[key];
        setExpanded((prev) => ({ ...prev, [key]: next }));
        if (next && item.source_type === "space") {
            loadSpaceChildren(item, item.id);
        }
    };

    const renderScopeItems = (source: SourceItem, parentId: number | null, depth: number) => {
        const key = childrenKey(source, parentId);
        const items = childrenByKey[key] || [];
        const loading = childrenLoading[key];
        if (loading) {
            return <div className="flex items-center gap-2 px-2 py-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />加载中...</div>;
        }
        if (!items.length) {
            return <div className="px-2 py-2 text-sm text-muted-foreground">暂无可选文件</div>;
        }
        return items.map((item) => {
            const key = itemKey(item);
            const selected = selectedItemKeys.has(key);
            const expandedFolder = expanded[key];
            return (
                <div key={key}>
                    <div className={`flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted ${selected ? "bg-primary/10 text-primary" : ""}`} style={{ paddingLeft: 10 + depth * 18 }}>
                        {item.isFolder ? (
                            <button type="button" className="flex h-5 w-5 items-center justify-center" onClick={() => handleToggleExpandFolder(item)}>
                                <ChevronRight className={`h-4 w-4 ${expandedFolder ? "rotate-90" : ""}`} />
                            </button>
                        ) : <span className="h-5 w-5" />}
                        <input type="checkbox" checked={selected} disabled={disabled} onChange={() => handleToggleItem(item)} />
                        {item.isFolder ? <Folder className="h-4 w-4 shrink-0" /> : <FileText className="h-4 w-4 shrink-0" />}
                        <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => handleToggleItem(item)}>{item.name}</button>
                        {item.isFolder && <span className="text-xs text-muted-foreground">{folderStats[key] ?? item.successFileCount ?? 0}</span>}
                    </div>
                    {item.isFolder && expandedFolder && renderScopeItems(item, item.id, depth + 1)}
                </div>
            );
        });
    };

    const renderSource = (source: SourceItem) => {
        const key = sourceKey(source);
        const selected = isSameSource(wholeSource, source);
        return (
            <div key={key} className="border-b last:border-b-0">
                <div className={`flex items-center gap-2 px-2 py-2 text-sm hover:bg-muted ${selected ? "bg-primary/10 text-primary" : ""}`}>
                    <button type="button" className="flex h-5 w-5 items-center justify-center" onClick={() => handleToggleExpandSource(source)}>
                        {childrenLoading[childrenKey(source, null)] ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className={`h-4 w-4 ${expanded[key] ? "rotate-90" : ""}`} />}
                    </button>
                    <input type="checkbox" checked={selected} disabled={disabled} onChange={() => handleToggleWholeSource(source)} />
                    <Database className="h-4 w-4 shrink-0" />
                    <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => handleToggleExpandSource(source)}>
                        {source.source_name}
                    </button>
                </div>
                {expanded[key] && renderScopeItems(source, null, 1)}
            </div>
        );
    };

    const overLimit = effectiveFileCount > MAX_RUNTIME_KNOWLEDGE_FILES;
    const selectedText = wholeSource ? "整库/整空间" : `${effectiveFileCount} / ${MAX_RUNTIME_KNOWLEDGE_FILES}`;

    return (
        <div className="mb-2 rounded-md border bg-background p-2 shadow-sm">
            <div className="mb-2 flex items-center justify-between">
                <div>
                    <div className="text-sm font-medium">自选知识范围</div>
                    <div className="text-xs text-muted-foreground">整库限选 1 个，文件最多 20 个</div>
                </div>
                <div className={`text-xs ${overLimit ? "text-red-500" : "text-muted-foreground"}`}>已选范围：{selectedText}</div>
            </div>
            <div className="relative mb-2">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                    className="h-9 w-full rounded-md border bg-background pl-8 pr-2 text-sm outline-none"
                    value={keyword}
                    disabled={disabled}
                    placeholder="文件名搜索"
                    onChange={(event) => setKeyword(event.target.value)}
                />
            </div>
            <div role="tablist" aria-label="知识来源类型" className="mb-2 grid grid-cols-2 rounded-md bg-muted p-1">
                <button
                    type="button"
                    role="tab"
                    aria-selected={activeTab === "knowledge"}
                    className={`h-8 rounded text-sm font-medium ${activeTab === "knowledge" ? "bg-background text-primary shadow-sm" : "text-muted-foreground"}`}
                    disabled={disabled}
                    onClick={() => handleChangeTab("knowledge")}
                >
                    文档知识库
                </button>
                <button
                    type="button"
                    role="tab"
                    aria-selected={activeTab === "space"}
                    className={`h-8 rounded text-sm font-medium ${activeTab === "space" ? "bg-background text-primary shadow-sm" : "text-muted-foreground"}`}
                    disabled={disabled}
                    onClick={() => handleChangeTab("space")}
                >
                    知识空间
                </button>
            </div>
            <div className="max-h-80 overflow-auto rounded border">
                {activeTab === "knowledge" ? (
                    <>
                        {sourceLoading.knowledge && <div className="flex items-center gap-2 p-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />加载中...</div>}
                        {!sourceLoading.knowledge && knowledgeList.map(renderSource)}
                        {!sourceLoading.knowledge && !knowledgeList.length && <div className="p-2 text-sm text-muted-foreground">暂无匹配的知识库</div>}
                    </>
                ) : (
                    <>
                        {sourceLoading.space && <div className="flex items-center gap-2 p-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />加载中...</div>}
                        {!sourceLoading.space && Object.keys(groupedSpaces).map((level) => (
                            <div key={level}>
                                <div className="px-2 py-1 text-xs text-muted-foreground">{SPACE_LEVEL_LABELS[level] || level}</div>
                                {groupedSpaces[level].map(renderSource)}
                            </div>
                        ))}
                        {!sourceLoading.space && !spaceList.length && <div className="p-2 text-sm text-muted-foreground">暂无匹配的知识空间</div>}
                    </>
                )}
            </div>
            {showConfirm && (
                <div className="mt-2 flex justify-end">
                    <Button
                        type="button"
                        size="sm"
                        disabled={disabled || confirmDisabled}
                        onClick={onConfirm}
                    >
                        {confirmLabel}
                    </Button>
                </div>
            )}
        </div>
    );
}
