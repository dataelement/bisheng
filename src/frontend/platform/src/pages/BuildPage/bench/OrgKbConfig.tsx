// src/pages/BuildPage/bench/OrgKbConfig.tsx
//
// v2.5 Module D 组织知识库配置面板。
// 两栏布局：左侧为已配置的知识库（拖拽排序、是否默认勾选、删除），
// 右侧为全部文档知识库（按更新时间倒序），支持按名称/描述模糊搜索。
// 结果以 OrgKbConfig 数组持久化进 WorkstationConfig.orgKbs。
import { BookIcon } from "@/components/bs-icons/knowledge";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { SearchInput } from "@/components/bs-ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { readFileLibDatabase } from "@/controllers/API";
import { AlignJustify, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { DragDropContext, Draggable, Droppable } from "react-beautiful-dnd";
import { useTranslation } from "react-i18next";

export interface OrgKbConfig {
    id: number;
    name: string;
    type?: number;
    default_checked: boolean;
    sort_order: number;
}

interface KnowledgeBase {
    id: number;
    name: string;
    description?: string;
    type: number;
    update_time?: string;
}

interface Props {
    orgKbs: OrgKbConfig[];
    onChange: (next: OrgKbConfig[]) => void;
}

function normalise(list: OrgKbConfig[]): OrgKbConfig[] {
    return list.map((kb, i) => ({ ...kb, sort_order: i }));
}

function KbTypeIcon() {
    return <BookIcon className="w-4 h-4 shrink-0" />;
}

export default function OrgKbConfig({ orgKbs, onChange }: Props) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [search, setSearch] = useState("");
    const [list, setList] = useState<KnowledgeBase[]>([]);
    const [loading, setLoading] = useState(false);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const fetchKbs = async (name: string) => {
        setLoading(true);
        try {
            const doc: any = await readFileLibDatabase({ page: 1, pageSize: 100, name, type: 0 });
            const merged = ((doc?.data || []) as KnowledgeBase[]).map((k) => ({ ...k, type: 0 }));
            merged.sort((a, b) => {
                const ta = a.update_time ? new Date(a.update_time).getTime() : 0;
                const tb = b.update_time ? new Date(b.update_time).getTime() : 0;
                return tb - ta;
            });
            setList(merged);
        } catch {
            toast({ variant: "error", description: t("bench.fetchKbFailed") });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => fetchKbs(search.trim()), 250);
        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
        };
    }, [search]);

    const selectedIds = useMemo(() => new Set(orgKbs.map((k) => k.id)), [orgKbs]);

    // Client-side description filter (server only searches name).
    const filteredList = useMemo(() => {
        const q = search.trim().toLowerCase();
        if (!q) return list;
        return list.filter(
            (kb) =>
                kb.name?.toLowerCase().includes(q) ||
                (kb.description || "").toLowerCase().includes(q),
        );
    }, [list, search]);

    const toggleAdd = (kb: KnowledgeBase) => {
        if (selectedIds.has(kb.id)) {
            onChange(normalise(orgKbs.filter((k) => k.id !== kb.id)));
            return;
        }
        onChange(
            normalise([
                ...orgKbs,
                {
                    id: kb.id,
                    name: kb.name,
                    type: kb.type,
                    default_checked: false,
                    sort_order: orgKbs.length,
                },
            ]),
        );
    };

    const handleDefaultCheckedChange = (kbId: number, defaultChecked: boolean) => {
        onChange(
            orgKbs.map((k) => (k.id === kbId ? { ...k, default_checked: defaultChecked } : k)),
        );
    };

    const handleRemove = (kbId: number) => {
        onChange(normalise(orgKbs.filter((k) => k.id !== kbId)));
    };

    const handleDragEnd = (result: any) => {
        if (!result.destination) return;
        if (result.destination.index === result.source.index) return;
        const next = [...orgKbs];
        const [moved] = next.splice(result.source.index, 1);
        next.splice(result.destination.index, 0, moved);
        onChange(normalise(next));
    };

    return (
        <div className="mt-2">
            <p className="text-sm text-muted-foreground mb-2">
                {t("bench.configureOrgKbs", "配置组织知识库")}
            </p>
            <div className="flex gap-4">
                {/* Selected panel */}
                <div className="w-1/2 flex border rounded-lg bg-white min-w-0" style={{ minHeight: 280 }}>
                    <div className="flex-1 p-4 flex flex-col min-w-0">
                        {orgKbs.length > 0 && (
                            <div className="flex items-center justify-between pb-2 text-xs text-muted-foreground">
                                <span>{t("bench.knowledgeBaseCol", "知识库")}</span>
                                <span>{t("bench.defaultChecked")}</span>
                            </div>
                        )}
                        {orgKbs.length === 0 ? (
                            <div className="flex-1 rounded-lg border-2 border-dashed bg-gray-50 flex flex-col items-center justify-center py-8 text-center">
                                <Plus className="w-6 h-6 text-gray-400 mb-2" />
                                <div className="text-sm text-gray-500 mb-1">
                                    {t("bench.noOrgKbConfigured", "暂未配置组织知识库")}
                                </div>
                                <div className="text-xs text-gray-400">
                                    {t("bench.pickFromRight", "请在右侧全部知识库中选择")}
                                </div>
                            </div>
                        ) : (
                            <DragDropContext onDragEnd={handleDragEnd}>
                                <Droppable droppableId="orgKbs">
                                    {(provided) => (
                                        <div
                                            {...provided.droppableProps}
                                            ref={provided.innerRef}
                                            className="space-y-2 overflow-y-auto"
                                            style={{ maxHeight: 320 }}
                                        >
                                            {orgKbs.map((kb, index) => (
                                                <Draggable
                                                    key={kb.id.toString()}
                                                    draggableId={kb.id.toString()}
                                                    index={index}
                                                >
                                                    {(dragProvided, snapshot) => (
                                                        <div
                                                            ref={dragProvided.innerRef}
                                                            {...dragProvided.draggableProps}
                                                            {...dragProvided.dragHandleProps}
                                                            className={`flex items-center gap-2 rounded-lg px-3 py-2 min-w-0 ${snapshot.isDragging
                                                                ? "bg-blue-50 shadow-md"
                                                                : "bg-white border"
                                                                }`}
                                                        >
                                                            <AlignJustify className="w-4 h-4 shrink-0 text-gray-400" />
                                                            <div className="text-primary">
                                                                <KbTypeIcon />
                                                            </div>
                                                            <TooltipProvider>
                                                                <Tooltip>
                                                                    <TooltipTrigger asChild>
                                                                        <span className="flex-1 min-w-0 truncate text-sm">
                                                                            {kb.name}
                                                                        </span>
                                                                    </TooltipTrigger>
                                                                    <TooltipContent>
                                                                        <p className="max-w-[240px]">{kb.name}</p>
                                                                    </TooltipContent>
                                                                </Tooltip>
                                                            </TooltipProvider>
                                                            <Checkbox
                                                                checked={kb.default_checked}
                                                                onCheckedChange={(v) =>
                                                                    handleDefaultCheckedChange(kb.id, !!v)
                                                                }
                                                            />
                                                            <button
                                                                type="button"
                                                                onClick={() => handleRemove(kb.id)}
                                                                className="text-gray-500 shrink-0"
                                                                title={t("bench.remove")}
                                                            >
                                                                <Trash2 className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    )}
                                                </Draggable>
                                            ))}
                                            {provided.placeholder}
                                        </div>
                                    )}
                                </Droppable>
                            </DragDropContext>
                        )}
                    </div>
                </div>

                {/* Full KB picker panel */}
                <div className="w-1/2 flex border rounded-lg bg-white flex-col" style={{ minHeight: 280 }}>
                    <div className="p-3 border-b">
                        <h3 className="font-medium text-sm mb-2">{t("bench.allKbs", "全部知识库")}</h3>
                        <SearchInput
                            placeholder={t("bench.searchKbName", "搜索知识库名称")}
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </div>
                    <div className="flex-1 overflow-y-auto p-2" style={{ maxHeight: 360 }}>
                        {loading && (
                            <div className="py-8 text-center text-sm text-muted-foreground">
                                {t("bench.loading")}
                            </div>
                        )}
                        {!loading && filteredList.length === 0 && (
                            <div className="py-8 text-center text-sm text-muted-foreground">
                                {t("bench.noMatchKbs")}
                            </div>
                        )}
                        {!loading &&
                            filteredList.map((kb) => {
                                const checked = selectedIds.has(kb.id);
                                return (
                                    <label
                                        key={kb.id}
                                        className="flex items-center gap-2 px-2 py-2 rounded cursor-pointer hover:bg-gray-50 min-w-0"
                                    >
                                        <Checkbox
                                            checked={checked}
                                            onCheckedChange={() => toggleAdd(kb)}
                                        />
                                        <div className="text-primary">
                                            <KbTypeIcon />
                                        </div>
                                        <TooltipProvider>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <span className="flex-1 min-w-0 truncate text-sm">
                                                        {kb.name}
                                                    </span>
                                                </TooltipTrigger>
                                                <TooltipContent>
                                                    <p className="max-w-[240px]">{kb.name}</p>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    </label>
                                );
                            })}
                    </div>
                </div>
            </div>
        </div >
    );
}
