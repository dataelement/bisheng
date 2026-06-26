import {
    getAuthorizedKnowledgeSpaceOptionsApi,
    getKnowledgeSpaceChildrenApi,
    getKnowledgeSpaceFolderStatsApi,
    KnowledgeSpaceChild,
    KnowledgeSpaceSummary,
} from "@/controllers/API/knowledgeSpace";
import { Check, ChevronRight, Database, FileText, Folder, Loader2, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
    MAX_RUNTIME_KNOWLEDGE_FILES,
    RuntimeKnowledgeItem,
    RuntimeKnowledgeSelection,
    RuntimeKnowledgeSource,
} from "./userSelectedKnowledge";

interface UserSelectedKnowledgePickerProps {
    disabled?: boolean;
    value?: RuntimeKnowledgeSelection | null;
    onChange: (value: RuntimeKnowledgeSelection | null) => void;
    showConfirm?: boolean;
    confirmDisabled?: boolean;
    confirmLabel?: string;
    onConfirm?: () => void;
    onCancel?: () => void;
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
    onCancel,
}: UserSelectedKnowledgePickerProps) {
    const [keyword, setKeyword] = useState("");
    const [spaceList, setSpaceList] = useState<SourceItem[]>([]);
    const [sourceLoading, setSourceLoading] = useState(false);
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
        setSourceLoading(true);
        getAuthorizedKnowledgeSpaceOptionsApi({ page: 1, page_size: 80, keyword, order_by: "name" })
            .then((res) => {
                if (canceled) return;
                setSpaceList((res.data || []).map((item: KnowledgeSpaceSummary) => ({
                    source_type: "space",
                    source_id: toId(item.id),
                    source_name: item.name || "",
                    level: item.space_level || item.space_kind || "personal",
                })));
            })
            .finally(() => !canceled && setSourceLoading(false));
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
            const existingSourceId = prev[0]?.source_id;
            if (existingSourceId && Number(existingSourceId) !== Number(runtimeItem.source_id)) {
                return [runtimeItem];
            }
            return prev.some((one) => itemKey(one) === key)
                ? prev.filter((one) => itemKey(one) !== key)
                : [...prev, runtimeItem];
        });
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
        loadSpaceChildren(source, null);
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
            return <div className="flex items-center gap-2 px-3 py-2 text-xs text-[#8a9ab8]"><Loader2 className="h-4 w-4 animate-spin" />加载中...</div>;
        }
        if (!items.length) {
            return <div className="px-3 py-2 text-xs text-[#8a9ab8]">暂无可选文件</div>;
        }
        return items.map((item) => {
            const key = itemKey(item);
            const selected = selectedItemKeys.has(key);
            const expandedFolder = expanded[key];
            return (
                <div key={key}>
                    <div
                        className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors hover:bg-[#f3f7ff] ${selected ? "bg-[#eef5ff] text-[#1f65f2]" : "text-[#344563]"}`}
                        style={{ paddingLeft: 14 + depth * 18 }}
                    >
                        {item.isFolder ? (
                            <button type="button" className="flex h-5 w-5 items-center justify-center text-[#6f86aa]" onClick={() => handleToggleExpandFolder(item)}>
                                <ChevronRight className={`h-4 w-4 ${expandedFolder ? "rotate-90" : ""}`} />
                            </button>
                        ) : <span className="h-5 w-5" />}
                        <input type="checkbox" className="h-4 w-4 rounded border-[#9db5d8] text-[#2d6ef5]" checked={selected} disabled={disabled} onChange={() => handleToggleItem(item)} />
                        {item.isFolder ? <Folder className="h-4 w-4 shrink-0 text-[#6f86aa]" /> : <FileText className="h-4 w-4 shrink-0 text-[#6f86aa]" />}
                        <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => handleToggleItem(item)}>{item.name}</button>
                        {item.isFolder && <span className="text-[11px] text-[#8a9ab8]">{folderStats[key] ?? item.successFileCount ?? 0}</span>}
                    </div>
                    {item.isFolder && expandedFolder && renderScopeItems(item, item.id, depth + 1)}
                </div>
            );
        });
    };

    const renderSource = (source: SourceItem) => {
        const key = sourceKey(source);
        const selected = isSameSource(wholeSource, source);
        const hasSelectedScope = selectedItems.some((item) => Number(item.source_id) === Number(source.source_id));
        return (
            <div key={key} className="rounded-xl border border-[#dbe5f5] bg-white transition-colors hover:border-[#b9d2f6] hover:bg-[#f8fbff]">
                <div className={`flex items-center gap-3 px-3 py-3 ${selected || hasSelectedScope ? "rounded-xl border border-[#6ca2ff] bg-[#f7fbff]" : ""}`}>
                    <input type="checkbox" className="h-5 w-5 rounded border-[#8fb4f6] text-[#2d6ef5]" checked={selected} disabled={disabled} onChange={() => handleToggleWholeSource(source)} />
                    <Database className="h-4 w-4 shrink-0 text-[#2d6ef5]" />
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => handleToggleExpandSource(source)}>
                        <span className="block truncate text-sm font-semibold text-[#1d2b46]">{source.source_name}</span>
                        <span className="mt-1 flex items-center gap-1 text-xs text-[#7e8fa8]">
                            <ChevronRight className={`h-3 w-3 ${expanded[key] ? "rotate-90" : ""}`} />
                            展开目录（可多选子项）
                        </span>
                    </button>
                    <button type="button" className="flex h-7 w-7 items-center justify-center rounded-md text-[#6f86aa] hover:bg-[#edf4ff]" onClick={() => handleToggleExpandSource(source)}>
                        {childrenLoading[childrenKey(source, null)] ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className={`h-4 w-4 ${expanded[key] ? "rotate-90" : ""}`} />}
                    </button>
                </div>
                {expanded[key] && <div className="border-t border-[#edf2fa] py-1">{renderScopeItems(source, null, 1)}</div>}
            </div>
        );
    };

    const overLimit = effectiveFileCount > MAX_RUNTIME_KNOWLEDGE_FILES;
    const selectedText = wholeSource ? "整空间" : `${effectiveFileCount} / ${MAX_RUNTIME_KNOWLEDGE_FILES}`;

    return (
        <div className="w-full rounded-2xl border border-[#dbe7fb] bg-white p-4 shadow-[0_18px_44px_rgba(15,23,42,0.14)]">
            <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                    <div className="text-sm font-semibold text-[#1d2b46]">自选知识范围</div>
                    <div className="mt-1 text-xs text-[#6f86aa]">选择 1 个知识空间，可限定文件/文件夹，文件最多 20 个</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                    <div className={`text-xs ${overLimit ? "text-red-500" : "text-[#6f86aa]"}`}>{wholeSource || selectedItems.length ? `已选范围：${selectedText}` : "未选择"}</div>
                    {onCancel && (
                        <button type="button" className="flex h-6 w-6 items-center justify-center rounded-md text-[#8a9ab8] hover:bg-[#eef4ff] hover:text-[#2d6ef5]" onClick={onCancel} aria-label="关闭">
                            <X size={14} />
                        </button>
                    )}
                </div>
            </div>
            <div className="relative mb-3">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a9ab8]" />
                <input
                    className="h-9 w-full rounded-md border border-[#d8e4f5] bg-[#fbfdff] pl-9 pr-2 text-sm outline-none placeholder:text-[#8a9ab8] focus:border-[#7fb0ff]"
                    value={keyword}
                    disabled={disabled}
                    placeholder="搜索知识空间名称"
                    onChange={(event) => setKeyword(event.target.value)}
                />
            </div>
            <div className="max-h-[360px] min-h-[220px] space-y-2 overflow-auto rounded-xl border border-[#edf2fa] bg-white p-2">
                {sourceLoading && <div className="flex items-center gap-2 p-3 text-sm text-[#8a9ab8]"><Loader2 className="h-4 w-4 animate-spin" />加载中...</div>}
                {!sourceLoading && Object.keys(groupedSpaces).map((level) => (
                    <div key={level} className="space-y-2">
                        <div className="px-1 text-xs text-[#8a9ab8]">{SPACE_LEVEL_LABELS[level] || level}</div>
                        <div className="space-y-2">{groupedSpaces[level].map(renderSource)}</div>
                    </div>
                ))}
                {!sourceLoading && !spaceList.length && <div className="p-3 text-sm text-[#8a9ab8]">暂无匹配的知识空间</div>}
            </div>
            {showConfirm && (
                <div className="mt-3 flex justify-end gap-2">
                    {onCancel && (
                        <button type="button" className="inline-flex h-8 items-center gap-1 rounded-md border border-[#d8e0f0] px-3 text-xs font-medium text-[#5a6a88] hover:bg-[#eef4ff] hover:text-[#2d6ef5]" onClick={onCancel}>
                            <X size={14} />
                            取消
                        </button>
                    )}
                    <button type="button" className="inline-flex h-8 items-center gap-1 rounded-md bg-[#2d6ef5] px-3 text-xs font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50" disabled={disabled || confirmDisabled} onClick={onConfirm}>
                        <Check size={14} />
                        {confirmLabel}
                    </button>
                </div>
            )}
        </div>
    );
}
