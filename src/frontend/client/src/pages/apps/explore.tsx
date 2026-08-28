import { ArrowLeft } from "lucide-react"
import type { AppItem } from "~/@types/app"
import { LoadingIcon } from "~/components/ui/icon/Loading"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useToastContext } from "~/Providers"
import { getChatOnlineApi, getUncategorized } from "~/api/apps"
import { NotificationSeverity } from "~/common"
import { Button } from "~/components/ui/Button"
import { EmptyStateIllustration } from "~/components/illustrations"
import { useLocalize, useMediaQuery } from "~/hooks"
import { useGetBsConfig } from "~/hooks/queries/data-provider"
import { cn, copyText } from "~/utils"
import { getAppShareUrl } from './appUtils'
import { AgentCard } from './components/AgentCard'
import { AgentNavigation } from './components/AgentNavigation'
import { AppSearchBar } from './components/AppSearchBar'

const appFlowOriginKey = (flowId: string) => `app-flow-origin:${flowId}`;
const appLastOriginKey = 'app-last-origin';

function extractAppPage(result: unknown) {
    const wrapper = result as { data?: unknown };
    const payload = wrapper?.data ?? result;
    const page = payload as { data?: unknown; list?: unknown; total?: unknown };
    const data = Array.isArray(payload)
        ? payload
        : Array.isArray(page?.data)
            ? page.data
            : Array.isArray(page?.list)
                ? page.list
                : [];
    const rawTotal = Array.isArray(payload) ? undefined : page?.total;
    const total = Number(rawTotal);
    return {
        data,
        total: rawTotal !== undefined && rawTotal !== null && Number.isFinite(total) ? total : undefined,
    };
}

function mergeAgentsById<T extends { id?: unknown }>(existing: T[], incoming: T[]) {
    const seenIds = new Set(existing.map((agent) => String(agent.id)));
    return [
        ...existing,
        ...incoming.filter((agent) => {
            const id = String(agent.id);
            if (seenIds.has(id)) return false;
            seenIds.add(id);
            return true;
        }),
    ];
}

export default function ExplorePlaza() {
    // Null until the navigation has its tags and can say which tab is the
    // default; fetching before that would show one tab's apps and then swap.
    const [activeTabId, setActiveTabId] = useState<number | string | null>(null)
    const [searchQuery, setSearchQuery] = useState("")
    const [agents, setAgents] = useState<AppItem[]>([])
    const [loading, setLoading] = useState(false)
    const [loadingMore, setLoadingMore] = useState(false)
    const [loadError, setLoadError] = useState(false)
    const [loadMoreError, setLoadMoreError] = useState(false)
    const [navigationError, setNavigationError] = useState(false)
    const [refreshTrigger, setRefreshTrigger] = useState(0)

    // --- 新增滚动加载相关状态 ---
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(true);
    const agentsRef = useRef<AppItem[]>([]);
    const requestSeqRef = useRef(0);
    const mainRef = useRef<HTMLElement | null>(null);
    const loaderRef = useRef<HTMLDivElement>(null);
    const loadMoreLockRef = useRef(false);
    const pageSize = 20;

    const navigate = useNavigate()
    const { showToast } = useToastContext()
    const localize = useLocalize()
    const { data: bsConfig } = useGetBsConfig()
    const isAtLeast768 = useMediaQuery('(min-width: 768px)')
    const isAtLeast1024 = useMediaQuery('(min-width: 1024px)')
    const bannerTitle = bsConfig?.applicationCenterWelcomeMessage?.trim() || localize('com_app_center_welcome')
    const bannerDescription = bsConfig?.applicationCenterDescription?.trim() || localize('com_app_center_description')

    const exploreCols = useMemo(() => {
        // md: 2 列（与应用中心一致）；lg+: 3 列（应用中心 4 列减 1）
        if (isAtLeast1024) return 3;
        if (isAtLeast768) return 2;
        return 1;
    }, [isAtLeast768, isAtLeast1024]);

    const fetchAgents = useCallback(async (query: string, categoryId: number | string, currentPage: number, isAppend: boolean) => {
        const requestId = ++requestSeqRef.current;
        if (isAppend) {
            setLoadingMore(true);
            setLoadMoreError(false);
        } else {
            setLoading(true);
            setLoadingMore(false);
            setLoadError(false);
            setLoadMoreError(false);
            loadMoreLockRef.current = false;
            agentsRef.current = [];
            setAgents([]);
        }

        try {
            const result = categoryId === 'uncategorized'
                ? await getUncategorized(currentPage, pageSize, query)
                : await getChatOnlineApi(currentPage, query, categoryId as number, pageSize);
            if (requestId !== requestSeqRef.current) return;

            const { data: pageData, total } = extractAppPage(result);
            const formattedResults = pageData.map((item) => {
                const app = item as AppItem & { agentId?: string; flowId?: string; type?: number };
                return {
                    ...app,
                    id: app.id || app.agentId || app.flowId || '',
                    flow_type: app.flow_type ?? app.type,
                } as AppItem;
            }).filter((app) => app.id);

            const previous = isAppend ? agentsRef.current : [];
            const nextAgents = isAppend ? mergeAgentsById(previous, formattedResults) : formattedResults;
            const uniqueAddedCount = nextAgents.length - previous.length;

            if (total !== undefined && nextAgents.length < total && (pageData.length === 0 || (isAppend && uniqueAddedCount === 0))) {
                if (isAppend) setLoadMoreError(true);
                else setLoadError(true);
                setHasMore(false);
                return;
            }

            agentsRef.current = nextAgents;
            setAgents(nextAgents);
            setPage(currentPage);
            setHasMore(total !== undefined ? nextAgents.length < total : pageData.length >= pageSize);
        } catch (error) {
            console.error("Failed to fetch agents:", error);
            if (requestId !== requestSeqRef.current) return;
            if (isAppend) {
                setLoadMoreError(true);
            } else {
                agentsRef.current = [];
                setAgents([]);
                setLoadError(true);
            }
            setHasMore(false);
        } finally {
            if (requestId === requestSeqRef.current) {
                if (isAppend) setLoadingMore(false);
                else setLoading(false);
            }
        }
    }, [pageSize]);

    const handleCategoryChange = useCallback((categoryId: number | string) => {
        setNavigationError(false);
        setActiveTabId(categoryId);
    }, []);

    const handleNavigationLoadError = useCallback(() => {
        setNavigationError(true);
    }, []);

    useEffect(() => {
        if (activeTabId === null) return;
        setHasMore(true);
        loadMoreLockRef.current = false;
        fetchAgents(searchQuery, activeTabId, 1, false);
    }, [searchQuery, activeTabId, refreshTrigger, fetchAgents]);

    useEffect(() => {
        if (!loadingMore) {
            loadMoreLockRef.current = false;
        }
    }, [loadingMore]);

    useEffect(() => {
        const root = mainRef.current;
        const target = loaderRef.current;
        if (!root || !target) return;

        const observer = new IntersectionObserver((entries) => {
            const target = entries[0];
            if (
                target.isIntersecting &&
                activeTabId !== null &&
                !loading &&
                !loadingMore &&
                hasMore &&
                !loadMoreError &&
                !loadMoreLockRef.current
            ) {
                loadMoreLockRef.current = true;
                fetchAgents(searchQuery, activeTabId, page + 1, true);
            }
        }, { root, threshold: 0, rootMargin: '400px 0px' });

        if (loaderRef.current) {
            observer.observe(loaderRef.current);
        }

        return () => observer.disconnect();
    }, [activeTabId, fetchAgents, hasMore, loadMoreError, loading, loadingMore, page, searchQuery]);

    const showLoading = loading || (activeTabId === null && !navigationError);
    const showInitialError = navigationError || (loadError && agents.length === 0);

    const handleCardClick = (agent: AppItem) => {
        const flowId = agent.id
        const flowType = agent.flow_type
        try {
            sessionStorage.setItem(appFlowOriginKey(String(flowId)), 'explore');
            sessionStorage.setItem(appLastOriginKey, 'explore');
        } catch {
            // ignore storage failures
        }
        // Enter without chatId — AppChatEntry will resolve to most recent conversation,
        // or create a new one if the user has no conversations for this app yet.
        navigate(`/app/${flowId}/${flowType}?from=explore&returnTo=%2Fapps%2Fexplore`, {
            state: { appSurfaceReturn: '/apps/explore' as const },
        });
    }

    const handleShare = async (agent: AppItem) => {
        if (agent.can_share !== true) return;
        const shareUrl = getAppShareUrl(agent.id, agent.flow_type);
        try {
            await copyText(shareUrl);
            showToast?.({
                message: localize('com_app_share_link_copied'),
                severity: NotificationSeverity.SUCCESS,
            });
        } catch {
            showToast?.({
                message: localize('com_app_share_link_copy_failed'),
                severity: NotificationSeverity.ERROR,
            });
        }
    }

    return (
        <div
            className={cn(
                'flex h-full min-h-0 w-full flex-1 flex-col items-center overflow-hidden bg-white',
                // Mobile explore is not innerScrollShell in MainLayout (h-auto shell) and
                // html/body scrolling is globally disabled (WebView bottom-strip fix in
                // index.html), so h-full/flex-1 collapse to content height and nothing can
                // scroll. Pin the page to one viewport tall on mobile so <main>'s
                // overflow-y-auto becomes the scroller (also gives empty/loading states a
                // real height to center against).
                'max-[767px]:h-[var(--bs-dvh,100dvh)]',
            )}
        >
            {/* 顶部横幅：与知识广场一致 — 跟随主题的品牌色渐变底（brand-50 → white） */}
            <div
                className="relative w-full shrink-0 overflow-hidden border-b border-[#F0F1F5] bg-blue-500/[0.05]"
            >
                {/* Decorative scattered icons — kept from the original banner art, recolored
                    via a brand-tinted mask layer so they follow the blue ⇄ green theme. */}
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0 bg-blue-200"
                    style={{
                        WebkitMaskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/apptab-icons.svg)`,
                        maskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/apptab-icons.svg)`,
                        WebkitMaskSize: "cover",
                        maskSize: "cover",
                        WebkitMaskPosition: "center",
                        maskPosition: "center",
                        WebkitMaskRepeat: "no-repeat",
                        maskRepeat: "no-repeat",
                    }}
                />
                <div className="absolute left-4 top-4 z-10">
                    <Button
                        variant="ghost"
                        onClick={() => navigate('/apps')}
                        className="h-8 w-8 rounded-md border border-border-base bg-white p-0 text-text-2 fine-pointer:hover:bg-fill-1 fine-pointer:hover:text-blue-500"
                    >
                        <ArrowLeft className="size-3.5" />
                    </Button>
                </div>
                <div className="relative mx-auto flex w-full max-w-[1000px] flex-col items-center justify-center px-5 pb-5 pt-7 text-center">
                    <h1 className="mb-1 font-['PingFang_SC'] text-[26px] font-semibold text-blue-500">
                        {bannerTitle}
                    </h1>
                    <p className="mb-3 max-w-[640px] font-['PingFang_SC'] text-[13px] leading-[22px] text-text-3">
                        {bannerDescription}
                    </p>
                </div>
            </div>

            {/* 过滤栏：桌面与原先一致；窄屏搜索独占一行（移动端始终展开搜索） */}
            <div className="w-full max-w-[1000px] shrink-0 flex items-center justify-between z-10 px-5 py-5 max-[576px]:flex-col max-[576px]:items-stretch max-[576px]:gap-3">
                <div className="order-2 max-[576px]:order-1 max-[576px]:w-full min-w-0 min-[577px]:shrink-0">
                    <AppSearchBar query={searchQuery} onSearch={setSearchQuery} />
                </div>
                <div className="order-1 max-[576px]:order-2 w-full min-w-0">
                    <AgentNavigation
                        onCategoryChange={handleCategoryChange}
                        onCategoryLoadError={handleNavigationLoadError}
                        onRefresh={() => setRefreshTrigger(prev => prev + 1)}
                    />
                </div>
            </div>

            {/* 智能体网格：滚动区占满整宽（滚动条贴最右），内容居中约束在 1000px */}
            <main ref={mainRef} className="flex min-h-0 w-full flex-1 flex-col items-center overflow-x-hidden overflow-y-auto scrollbar-os">
                <div className="flex w-full max-w-[1000px] flex-1 flex-col px-5 pb-5">
                <div
                    className="grid w-full items-start gap-4"
                    style={{ gridTemplateColumns: `repeat(${exploreCols}, minmax(0, 1fr))` }}
                >
                    {agents.map((agent, idx) => (
                        <AgentCard
                            key={`${agent.id}-${idx}`}
                            agent={agent}
                            onStartChat={handleCardClick}
                            onShare={handleShare}
                        />
                    ))}
                </div>

                {/* 滚动触发器 & 加载状态显示 */}
                <div
                    ref={loaderRef}
                    className={cn(
                        'flex w-full flex-col items-center',
                        // Empty/loading: fill the region and place content via flex spacers at a
                        // region-relative height (not viewport vh): ~40% on mobile, ~45% on PC.
                        (showLoading || showInitialError || agents.length === 0) ? 'flex-1' : 'py-10',
                    )}
                >
                    {(showLoading || showInitialError || agents.length === 0) && <div className="flex-[8] md:flex-[9]" aria-hidden />}
                    {showLoading ? (
                        <div className="flex flex-col items-center gap-3 text-blue-500">
                            <LoadingIcon className="size-20 text-primary" />
                            <span className="text-sm font-['PingFang_SC'] text-text-3">{localize('com_list_loading')}</span>
                        </div>
                    ) : showInitialError ? (
                        <p className="text-[14px] font-['PingFang_SC'] text-text-3">{localize('com_list_load_failed')}</p>
                    ) : loadingMore ? (
                        <div className="flex items-center gap-2 text-blue-500">
                            <LoadingIcon className="size-6 text-primary" />
                            <span className="text-sm font-['PingFang_SC'] text-text-3">{localize('com_list_loading_more')}</span>
                        </div>
                    ) : loadMoreError ? (
                        <p className="mt-4 text-[12px] font-['PingFang_SC'] text-text-4">{localize('com_list_load_failed')}</p>
                    ) : null}
                    {!loadMoreError && !hasMore && agents.length > 0 && (
                        <p className="text-[#a9aeb8] text-[12px] font-['PingFang_SC'] mt-4">{localize('com_list_all_loaded')}</p>
                    )}
                    {!showLoading && !showInitialError && agents.length === 0 && (
                        <div className="flex flex-col items-center">
                            <EmptyStateIllustration className="size-[120px] mb-4" />
                            <p className="text-[#a9aeb8] text-[14px] font-['PingFang_SC']">
                                {searchQuery ? localize('com_list_no_results') : localize('com_app_explore_no_agents')}
                            </p>
                        </div>
                    )}
                    {(showLoading || showInitialError || agents.length === 0) && <div className="flex-[12] md:flex-[11]" aria-hidden />}
                </div>
                </div>
            </main>
        </div>
    )
}
