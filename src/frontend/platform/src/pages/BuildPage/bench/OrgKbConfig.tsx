import { Button, SearchInput, notification } from '@bisheng/ui';

import { Checkbox } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
// src/pages/BuildPage/bench/OrgKbConfig.tsx
//

import { BookIcon } from "@/components/bs-icons/knowledge";


import { readFileLibDatabase } from "@/controllers/API";
import { Tooltip, TooltipProvider } from "@bisheng/ui";

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

    const [search, setSearch] = useState("");
    const [list, setList] = useState<KnowledgeBase[]>([]);
    const [loading, setLoading] = useState(false);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const fetchKbs = async (name: string) => {
        setLoading(true);
        try {
            const doc: any = await readFileLibDatabase({ cursor: null, pageSize: 100, name, type: 0, action: "use" });
            const merged = ((doc?.data || []) as KnowledgeBase[]).map((k) => ({ ...k, type: 0 }));
            merged.sort((a, b) => {
                const ta = a.update_time ? new Date(a.update_time).getTime() : 0;
                const tb = b.update_time ? new Date(b.update_time).getTime() : 0;
                return tb - ta;
            });
            setList(merged);
        } catch {
            notification.open({ type: "error", description: String(t("bench.fetchKbFailed") ?? '') });
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
            (kb) => kb.name?.toLowerCase().includes(q) || (kb.description || "").toLowerCase().includes(q),
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
        onChange(orgKbs.map((k) => (k.id === kbId ? { ...k, default_checked: defaultChecked } : k)));
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
        <div className="mt-2 min-w-0 max-w-full">
            <p className="text-sm text-muted-foreground mb-2">{t("bench.configureOrgKbs")}</p>
            <div className="flex min-w-0 w-full max-w-full gap-4">
                {/* Selected panel */}
                <div className="flex w-1/2 min-w-0 max-w-[50%] border rounded-lg bg-white" style={{ minHeight: 280 }}>
                    <div className="flex-1 p-4 flex flex-col min-w-0">
                        {orgKbs.length > 0 && (
                            <div className="flex items-center justify-between pb-2 text-xs text-muted-foreground">
                                <span>{t("bench.knowledgeBaseCol")}</span>
                                <span>{t("bench.defaultChecked")}</span>
                            </div>
                        )}
                        {orgKbs.length === 0 ? (
                            <div className="flex-1 rounded-lg border-2 border-dashed bg-gray-50 flex flex-col items-center justify-center py-8 text-center">
                                <Outlined.Plus className="w-6 h-6 text-gray-400 mb-2" />
                                <div className="text-sm text-gray-500 mb-1">{t("bench.noOrgKbConfigured")}</div>
                                <div className="text-xs text-gray-400">{t("bench.pickFromRight")}</div>
                            </div>
                        ) : (
                            <DragDropContext onDragEnd={handleDragEnd}>
                                <Droppable droppableId="orgKbs">
                                    {(provided) => (
                                        <div
                                            {...provided.droppableProps}
                                            ref={provided.innerRef}
                                            className="space-y-2 overflow-x-hidden overflow-y-auto"
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
                                                            className={`flex items-center gap-2 rounded-lg px-3 py-2 min-w-0 ${
                                                                snapshot.isDragging
                                                                    ? "bg-blue-50 shadow-md"
                                                                    : "bg-white border"
                                                            }`}
                                                        >
                                                            <Outlined.Drag className="w-4 h-4 shrink-0 text-gray-400" />
                                                            <div className="shrink-0 text-primary">
                                                                <KbTypeIcon />
                                                            </div>
                                                            <TooltipProvider>
                                                                <Tooltip
                                                                    content={
                                                                        <>
                                                                            <p className="max-w-[240px] break-words">
                                                                                {kb.name}
                                                                            </p>
                                                                        </>
                                                                    }
                                                                >
                                                                    <span className="block min-w-0 flex-1 truncate text-sm">
                                                                        {kb.name}
                                                                    </span>
                                                                </Tooltip>
                                                            </TooltipProvider>
                                                            <Checkbox
                                                                className="shrink-0"
                                                                checked={kb.default_checked}
                                                                onCheckedChange={(v) =>
                                                                    handleDefaultCheckedChange(kb.id, !!v)
                                                                }
                                                            />
                                                            <Button type="button" variant="text" onClick={() => handleRemove(kb.id)} className="shrink-0" title={t("bench.remove")} color="default">
                                                                <Outlined.Delete className="w-4 h-4" />
                                                            </Button>
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
                <div
                    className="flex w-1/2 min-w-0 max-w-[50%] flex-col overflow-hidden border rounded-lg bg-white"
                    style={{ minHeight: 280 }}
                >
                    <div className="shrink-0 border-b p-3 min-w-0">
                        <h3 className="mb-2 text-sm font-medium">{t("bench.allKbs")}</h3>
                        <SearchInput placeholder={t("bench.searchKbName")} value={search} onChange={(e) => setSearch(e.target.value)} className={"w-full min-w-0 max-w-full"} />
                    </div>
                    <div className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-2" style={{ maxHeight: 360 }}>
                        {loading && (
                            <div className="py-8 text-center text-sm text-muted-foreground">{t("bench.loading")}</div>
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
                                        className="flex min-w-0 max-w-full cursor-pointer items-center gap-2 rounded px-2 py-2 hover:bg-gray-50"
                                    >
                                        <Checkbox
                                            className="shrink-0"
                                            checked={checked}
                                            onCheckedChange={() => toggleAdd(kb)}
                                        />
                                        <div className="shrink-0 text-primary">
                                            <KbTypeIcon />
                                        </div>
                                        <TooltipProvider>
                                            <Tooltip
                                                content={
                                                    <>
                                                        <p className="max-w-[240px] break-words">{kb.name}</p>
                                                    </>
                                                }
                                            >
                                                <span className="block min-w-0 max-w-full flex-1 truncate text-sm">
                                                    {kb.name}
                                                </span>
                                            </Tooltip>
                                        </TooltipProvider>
                                    </label>
                                );
                            })}
                    </div>
                </div>
            </div>
        </div>
    );
}
