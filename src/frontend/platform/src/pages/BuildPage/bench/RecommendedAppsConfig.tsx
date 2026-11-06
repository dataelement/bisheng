// @ts-strict-ignore
import { Button, SearchInput, notification } from '@bisheng/ui';
import AppAvator from "@/components/bs-comp/cardComponent/avatar";



import { getChatOnlineApi, getRecommendedAppsApi } from "@/controllers/API/assistant";
import { Outlined } from "bisheng-icons";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DragDropContext, Draggable, Droppable } from "@hello-pangea/dnd";
import { useTranslation } from "react-i18next";

const MAX_RECOMMENDED_APPS = 16;

// Tab config for app types: workflow=10, assistant=5
const APP_TYPE_TABS = [
    { key: "workflow", label: "build.workflow", flowType: 10 },
    { key: "assistant", label: "build.assistant", flowType: 5 },
];

type AppItem = {
    id: string;
    name: string;
    logo?: string;
    description?: string;
    flow_type?: number;
    [key: string]: any;
};

interface RecommendedAppsConfigProps {
    selectedAppIds: string[];
    onSelectedAppsChange: (ids: string[]) => void;
}

export default function RecommendedAppsConfig({ selectedAppIds, onSelectedAppsChange }: RecommendedAppsConfigProps) {
    const { t } = useTranslation();


    // Detail cache keyed by app id; populated from init fetch, tab list loads, and clicks.
    // selectedApps is derived from selectedAppIds + this cache, so async fetches can never
    // overwrite user clicks mid-flight.
    const [appDetails, setAppDetails] = useState<Record<string, AppItem>>({});
    const [activeTab, setActiveTab] = useState("workflow");
    const [searchTerm, setSearchTerm] = useState("");
    const [appList, setAppList] = useState<AppItem[]>([]);
    const [hasMore, setHasMore] = useState(true);
    const [loading, setLoading] = useState(false);
    const listRef = useRef<HTMLDivElement>(null);
    const loadingRef = useRef(false);
    const cursorRef = useRef<string | null>(null);

    const currentFlowType = APP_TYPE_TABS.find((tab) => tab.key === activeTab)?.flowType;

    const mergeDetails = useCallback((apps: AppItem[]) => {
        if (!apps.length) return;
        setAppDetails((prev) => {
            const next = { ...prev };
            for (const app of apps) next[app.id] = app;
            return next;
        });
    }, []);

    // Load apps list from API (F027 cursor waterfall). `cursor === null` starts fresh.
    const loadApps = useCallback(
        async (cursor: string | null, reset = false) => {
            if (loadingRef.current || currentFlowType === undefined) return;
            loadingRef.current = true;
            setLoading(true);
            try {
                const res: any = await getChatOnlineApi(cursor, searchTerm, -1, currentFlowType, {
                    sortBy: "update_time",
                    searchDescription: true,
                });
                const pageData: AppItem[] = res.list || [];
                setAppList((prev) => (reset ? pageData : [...prev, ...pageData]));
                mergeDetails(pageData);
                setHasMore(!!res.hasMore);
                cursorRef.current = res.nextCursor;
            } catch (error) {
                console.error("Error loading apps:", error);
            } finally {
                loadingRef.current = false;
                setLoading(false);
            }
        },
        [searchTerm, currentFlowType, mergeDetails],
    );

    // Reset and reload when tab or search changes
    useEffect(() => {
        setAppList([]);
        setHasMore(true);
        cursorRef.current = null;
        loadApps(null, true);
    }, [activeTab, searchTerm, loadApps]);

    // Scroll to bottom loads more
    const handleScroll = useCallback(() => {
        if (!listRef.current || !hasMore || loading) return;
        const { scrollTop, scrollHeight, clientHeight } = listRef.current;
        if (scrollTop + clientHeight >= scrollHeight - 20) {
            loadApps(cursorRef.current);
        }
    }, [hasMore, loading, loadApps]);

    // On mount (or once ids become available) fetch details for already-configured apps.
    const initializedRef = useRef(false);
    useEffect(() => {
        if (initializedRef.current) return;
        if (!selectedAppIds || selectedAppIds.length === 0) return;
        initializedRef.current = true;
        getRecommendedAppsApi()
            .then((res: any) => {
                const apps: AppItem[] = Array.isArray(res) ? res : res?.data || [];
                mergeDetails(apps);
            })
            .catch(() => {
                /* keep existing cache */
            });
    }, [selectedAppIds, mergeDetails]);

    // Derived: selected apps preserve parent-specified order; unresolved ids are skipped until
    // their details appear in the cache.
    const selectedApps = useMemo(
        () => selectedAppIds.map((id) => appDetails[id]).filter(Boolean) as AppItem[],
        [selectedAppIds, appDetails],
    );
    const selectedIdSet = useMemo(() => new Set(selectedAppIds), [selectedAppIds]);
    const isAtLimit = selectedAppIds.length >= MAX_RECOMMENDED_APPS;

    const toggleApp = (app: AppItem) => {
        mergeDetails([app]);
        if (selectedIdSet.has(app.id)) {
            onSelectedAppsChange(selectedAppIds.filter((id) => id !== app.id));
            return;
        }
        if (isAtLimit) {
            notification.open({ type: "warning", description: String(t("publicPages.recommendedAppLimit", { max: MAX_RECOMMENDED_APPS })) });
            return;
        }
        onSelectedAppsChange([...selectedAppIds, app.id]);
    };

    const removeApp = (index: number) => {
        const next = [...selectedAppIds];
        next.splice(index, 1);
        onSelectedAppsChange(next);
    };

    const handleDragEnd = (result: any) => {
        if (!result.destination || result.destination.index === result.source.index) return;
        const next = [...selectedAppIds];
        const [moved] = next.splice(result.source.index, 1);
        next.splice(result.destination.index, 0, moved);
        onSelectedAppsChange(next);
    };

    return (
        <div className="mb-6">
            <p className="text-lg font-bold mb-2">{t("publicPages.recommendedApps")}</p>
            <div className="flex gap-4">
                {/* Left panel: selected apps */}
                <div className="w-1/3 flex border rounded-lg bg-white">
                    <div className="flex-1 p-4">
                        <h3 className="text-[16px] font-medium">{t("publicPages.selectedApps")}</h3>
                        {selectedApps.length === 0 ? (
                            <div className="mt-4 border-2 border-dashed border-gray-200 rounded-lg bg-gray-50 flex flex-col items-center justify-center py-6 px-4 text-center">
                                <div className="mb-2">
                                    <Outlined.Plus className="w-6 h-6 text-gray-400" />
                                </div>
                                <div className="text-sm font-medium text-gray-500 mb-1">
                                    {t("publicPages.noConfiguredApps")}
                                </div>
                                <div className="text-xs text-gray-400">{t("publicPages.pickAppsFromRight")}</div>
                            </div>
                        ) : (
                            <DragDropContext onDragEnd={handleDragEnd}>
                                <Droppable droppableId="recommendedApps">
                                    {(provided) => (
                                        <div
                                            {...provided.droppableProps}
                                            ref={provided.innerRef}
                                            className="space-y-2 mt-2 flex-1 overflow-y-auto"
                                            style={{ maxHeight: "300px" }}
                                        >
                                            {selectedApps.map((app, index) => (
                                                <Draggable
                                                    key={app.id.toString()}
                                                    draggableId={app.id.toString()}
                                                    index={index}
                                                >
                                                    {(provided, snapshot) => (
                                                        <div
                                                            ref={provided.innerRef}
                                                            {...provided.draggableProps}
                                                            {...provided.dragHandleProps}
                                                            className={`flex items-center justify-between p-3 py-2 rounded-lg ${
                                                                snapshot.isDragging
                                                                    ? "bg-blue-50 shadow-md"
                                                                    : "bg-white border"
                                                            }`}
                                                        >
                                                            <div className="flex items-center min-w-0">
                                                                <Outlined.Drag className="w-4 h-4 mr-2 text-gray-400 flex-shrink-0" />
                                                                <AppAvator
                                                                    id={app.name}
                                                                    url={app.logo}
                                                                    flowType={app.flow_type}
                                                                    className="w-6 h-6 mr-2 flex-shrink-0"
                                                                />
                                                                <span className="truncate max-w-[140px] text-sm">
                                                                    {app.name}
                                                                </span>
                                                            </div>
                                                            <Button type="button" variant="text" onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    removeApp(index);
                                                                }} className="ml-2 flex-shrink-0" color="default">
                                                                <Outlined.Close className="w-4 h-4" />
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

                {/* Right panel: app selector */}
                <div className="w-2/3 flex border rounded-lg bg-white overflow-hidden">
                    {/* Category tabs */}
                    <div className="w-1/3 border-r bg-gray-50 flex flex-col">
                        <div className="p-2 border-b">
                            <h3 className="font-medium">{t("publicPages.allApps")}</h3>
                        </div>
                        <div className="relative p-2 border-b">
                            <SearchInput placeholder={t("publicPages.searchApps")} value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} />
                        </div>
                        <div className="flex-1 overflow-y-auto p-2">
                            <div className="space-y-1">
                                {APP_TYPE_TABS.map((tab) => (
                                    <Button type="button" variant="text" key={tab.key} className={`flex items-center justify-start w-full text-left p-2 rounded ${
                                            activeTab === tab.key ? "bg-blue-100 text-blue-600" : "hover:bg-gray-100"
                                        }`} onClick={() => setActiveTab(tab.key)} color="default">
                                        <AppAvator
                                            id={tab.flowType}
                                            url=""
                                            flowType={tab.flowType}
                                            className="w-5 h-5 bg-gray-400"
                                        />
                                        <span className="ml-2">{t(tab.label)}</span>
                                    </Button>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* App list */}
                    <div
                        ref={listRef}
                        className="w-2/3 flex flex-col overflow-y-auto"
                        style={{ height: "400px" }}
                        onScroll={handleScroll}
                    >
                        {appList.length > 0 ? (
                            <div className="p-2 space-y-1">
                                {appList.map((app) => {
                                    const isSelected = selectedIdSet.has(app.id);
                                    const isDisabled = !isSelected && isAtLimit;
                                    const limitTip = t("publicPages.recommendedAppLimit", { max: MAX_RECOMMENDED_APPS });
                                    return (
                                        <div
                                            key={app.id}
                                            title={isDisabled ? limitTip : undefined}
                                            className={`flex items-start gap-2 p-2 rounded hover:bg-gray-50 ${
                                                isDisabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
                                            }`}
                                            onClick={() => {
                                                if (isDisabled) {
                                                    notification.open({ type: "warning", description: String(limitTip ?? '') });
                                                    return;
                                                }
                                                toggleApp(app);
                                            }}
                                        >
                                            {/* Checkbox */}
                                            <div
                                                className={`w-4 h-4 mt-0.5 border rounded flex items-center justify-center flex-shrink-0 ${
                                                    isSelected
                                                        ? "bg-primary border-primary"
                                                        : isDisabled
                                                          ? "border-gray-200 bg-gray-100"
                                                          : "border-gray-300"
                                                }`}
                                            >
                                                {isSelected && (
                                                    <Outlined.Check className="w-3 h-3" style={{ color: "white" }} />
                                                )}
                                            </div>
                                            {/* App icon */}
                                            <AppAvator
                                                id={app.name}
                                                url={app.logo}
                                                flowType={app.flow_type}
                                                className="w-6 h-6 flex-shrink-0"
                                            />
                                            {/* App info */}
                                            <div className="min-w-0 flex-1">
                                                <p className="text-sm font-medium truncate">{app.name}</p>
                                                {app.description && (
                                                    <p className="text-xs text-gray-500 truncate mt-0.5">
                                                        {app.description}
                                                    </p>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                                {loading && (
                                    <div className="text-center text-xs text-gray-400 py-2">{t("loading")}</div>
                                )}
                            </div>
                        ) : loading ? (
                            <div className="flex-1 flex justify-center items-center">
                                <span className="text-sm text-gray-400">{t("loading")}</span>
                            </div>
                        ) : (
                            <div className="flex-1 flex justify-center items-center text-sm text-gray-500">
                                {t("publicPages.noApps")}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
