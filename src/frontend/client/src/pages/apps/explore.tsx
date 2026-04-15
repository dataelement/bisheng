import { ArrowLeft, Loader2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useToastContext } from "~/Providers"
import { getChatOnlineApi, getUncategorized } from "~/api/apps"
import { NotificationSeverity } from "~/common"
import AppAvator from '~/components/Avator'
import { Button } from "~/components/ui/Button"
import { useLocalize } from "~/hooks"
import { cn, copyText } from "~/utils"
import { getAppShareUrl } from './appUtils'
import { AgentNavigation } from './components/AgentNavigation'
import { AppSearchBar } from './components/AppSearchBar'

const APP_TAB_BANNER = `${__APP_ENV__.BASE_URL || ''}/assets/channel/apptab.svg`

// --- 组件：智能体卡片 (广场版 Horizontal) ---
const ExploreCard = ({ agent, onClick, onShare }: { agent: any, onClick: (agent: any) => void, onShare: (agent: any) => void }) => {
    const localize = useLocalize();
    return (
        <div
            onClick={() => onClick(agent)}
            className={cn(
                "group relative content-stretch flex h-[80px] items-center gap-[12px] overflow-clip rounded-[8px] p-[12px] transition-all cursor-pointer",
                "border-[0.5px] border-solid border-[#EBECF0] bg-[linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)]",
                "hover:shadow-[0_8px_20px_0_rgba(117,145,212,0.12)]",
                "after:pointer-events-none after:absolute after:inset-0 after:rounded-[8px] after:border after:border-[#335CFF] after:opacity-0 after:transition-opacity group-hover:after:opacity-100",
                "hover:bg-[linear-gradient(0deg,#FFF_0%,#FFF_100%),linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)]"
            )}
        >
            {/* 左侧图标 */}
            <AppAvator
                url={agent.logo} id={agent.id as any}
                flowType={String(agent.flow_type || agent.type)}
                className="size-[48px] min-w-[48px] min-h-[48px] shrink-0 rounded-[4px]"
                iconClassName="w-6 h-6"
            />

            {/* 右侧内容 */}
            <div className="flex flex-[1_0_0] flex-col h-full items-start min-w-px relative">
                <p className="font-['PingFang_SC'] font-medium leading-[20px] text-[#212121] text-[14px] truncate w-full">
                    {agent.name}
                </p>

                {/* 描述区域：平时显示，hover时隐藏 */}
                <p className="mt-[2px] flex-[1_0_0] w-full overflow-hidden text-ellipsis whitespace-normal font-['PingFang_SC'] text-[12px] leading-[18px] text-[#A9AEB8] line-clamp-2 group-hover:hidden">
                    {agent.description || agent.desc || localize('com_app_no_description_placeholder')}
                </p>

                {/* 按纽区域：平时隐藏，hover时显示 */}
                <div className="hidden group-hover:flex flex-[1_0_0] gap-[4px] items-center justify-center min-h-px w-full mt-auto">
                    <button
                        onClick={(e) => { e.stopPropagation(); onShare(agent); }}
                        className="bg-white border border-[#ececec] flex flex-[1_0_0] h-[28px] items-center justify-center px-[10px] rounded-[6px] text-[#212121] text-[14px] font-['PingFang_SC'] hover:bg-gray-50 transition-colors"
                    >
                        {localize('com_app_share_app')}
                    </button>
                    <button
                        onClick={(e) => { e.stopPropagation(); onClick(agent); }}
                        className="bg-[#335cff] flex flex-[1_0_0] h-[28px] items-center justify-center px-[10px] rounded-[6px] text-white text-[14px] font-['PingFang_SC'] hover:bg-blue-600 transition-colors"
                    >
                        {localize('com_app_start_chat')}
                    </button>
                </div>
            </div>
        </div>
    )
}

export default function ExplorePlaza() {
    const [activeTabId, setActiveTabId] = useState<number | string>(-1)
    const [searchQuery, setSearchQuery] = useState("")
    const [agents, setAgents] = useState<any[]>([])
    const [loading, setLoading] = useState(false)
    const [loadingMore, setLoadingMore] = useState(false)
    const [refreshTrigger, setRefreshTrigger] = useState(0)

    // --- 新增滚动加载相关状态 ---
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(true);
    const loaderRef = useRef<HTMLDivElement>(null);
    const loadMoreLockRef = useRef(false);
    const pageSize = 20;

    const navigate = useNavigate()
    const { showToast } = useToastContext()
    const localize = useLocalize()

    // Modify Fetch Function
    const fetchAgents = useCallback(async (query: string, categoryId: number | string, currentPage: number, isAppend: boolean) => {
        if (loading || loadingMore) return;
        if (isAppend) setLoadingMore(true);
        else setLoading(true);
        try {
            const result = categoryId === 'uncategorized'
                ? await getUncategorized(currentPage, pageSize, query)
                : await getChatOnlineApi(currentPage, query, categoryId === -1 ? undefined : (categoryId as number), pageSize);

            const pageData = (result as any).data || [];

            const formattedResults = pageData.map((item: any) => ({
                ...item,
                id: item.id || item.agentId || item.flowId
            }));

            setAgents(prev => isAppend ? [...prev, ...formattedResults] : formattedResults);
            setHasMore(pageData.length >= pageSize);
        } catch (error) {
            console.error("Failed to fetch agents:", error);
            if (!isAppend) setAgents([]);
        } finally {
            if (isAppend) setLoadingMore(false);
            else setLoading(false);
        }
    }, [loading, loadingMore]);

    useEffect(() => {
        setPage(1);
        setHasMore(true);
        loadMoreLockRef.current = false;
        fetchAgents(searchQuery, activeTabId, 1, false);
    }, [searchQuery, activeTabId, refreshTrigger]);

    useEffect(() => {
        if (page > 1) {
            fetchAgents(searchQuery, activeTabId, page, true);
        }
    }, [page]);

    useEffect(() => {
        if (!loadingMore) {
            loadMoreLockRef.current = false;
        }
    }, [loadingMore]);

    useEffect(() => {
        const observer = new IntersectionObserver((entries) => {
            const target = entries[0];
            if (
                target.isIntersecting &&
                !loading &&
                !loadingMore &&
                hasMore &&
                !loadMoreLockRef.current
            ) {
                loadMoreLockRef.current = true;
                setPage(prev => prev + 1);
            }
        }, { threshold: 0, rootMargin: '400px 0px' });

        if (loaderRef.current) {
            observer.observe(loaderRef.current);
        }

        return () => observer.disconnect();
    }, [loading, loadingMore, hasMore]);

    const handleCardClick = (agent: any) => {
        const flowId = agent.id
        const flowType = agent.flow_type || agent.type
        // Enter without chatId — AppChatEntry will resolve to most recent conversation,
        // or create a new one if the user has no conversations for this app yet.
        navigate(`/app/${flowId}/${flowType}?from=explore`);
    }

    const handleShare = async (agent: any) => {
        const shareUrl = getAppShareUrl(agent.id, agent.flow_type || agent.type);
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
        <div className="flex w-full flex-col items-center bg-white pb-16">
            {/* 顶部横幅：背景图尺寸与知识广场（KnowledgeSquare tabbg）相同 — bg-cover + center */}
            <div
                className="relative w-full shrink-0 overflow-hidden border-b border-[#F0F1F5] bg-cover bg-center bg-no-repeat"
                style={{ backgroundImage: `url(${APP_TAB_BANNER})` }}
            >
                <div className="absolute left-5 top-5 z-10">
                    <Button
                        variant="ghost"
                        onClick={() => navigate('/apps')}
                        className="h-8 w-8 rounded-md border border-[#E5E6EB] bg-white p-0 text-[#4E5969] hover:bg-[#F7F8FA] hover:text-[#335CFF]"
                    >
                        <ArrowLeft className="size-3.5" />
                    </Button>
                </div>
                <div className="relative mx-auto flex w-full max-w-[1000px] flex-col items-center justify-center px-5 pb-5 pt-7 text-center">
                    <h1 className="mb-1 font-['PingFang_SC'] text-[26px] font-semibold text-[#335CFF]">
                        {localize('com_app_center_welcome')}
                    </h1>
                    <p className="mb-3 max-w-[640px] font-['PingFang_SC'] text-[13px] leading-[22px] text-[#86909C]">
                        {localize('com_app_center_description')}
                    </p>
                </div>
            </div>

            {/* 过滤栏 */}
            <div className="w-full max-w-[1000px] flex items-center justify-between z-10 px-5 py-5">
                <AgentNavigation onCategoryChange={setActiveTabId} onRefresh={() => setRefreshTrigger(prev => prev + 1)} />
                <AppSearchBar query={searchQuery} onSearch={setSearchQuery} />
            </div>

            {/* 智能体网格 */}
            <main className="w-full max-w-[1000px] px-5">
                <div className="grid w-full gap-[12px] grid-cols-2 [@media(min-width:768px)]:grid-cols-4">
                    {agents.map((agent, idx) => (
                        <ExploreCard key={`${agent.id}-${idx}`} agent={agent} onClick={handleCardClick} onShare={handleShare} />
                    ))}
                </div>

                {/* 滚动触发器 & 加载状态显示 */}
                <div ref={loaderRef} className="flex justify-center py-10 w-full">
                    {loading && (
                        <div className="flex items-center gap-2 text-[#335cff]">
                            <Loader2 className="animate-spin" size={24} />
                            <span className="text-sm font-['PingFang_SC']">{localize('com_app_explore_loading_more')}</span>
                        </div>
                    )}
                    {!loading && loadingMore && (
                        <div className="flex items-center gap-2 text-[#335cff]">
                            <Loader2 className="animate-spin" size={20} />
                            <span className="text-sm font-['PingFang_SC']">{localize('com_app_explore_loading_more')}</span>
                        </div>
                    )}
                    {!hasMore && agents.length > 0 && (
                        <p className="text-[#a9aeb8] text-[12px] font-['PingFang_SC'] mt-4">{localize('com_app_explore_end_of_list')}</p>
                    )}
                    {!loading && agents.length === 0 && (
                        <p className="text-[#a9aeb8] text-[14px] font-['PingFang_SC'] mt-4 py-10">{localize('com_app_explore_no_agents')}</p>
                    )}
                </div>
            </main>
        </div>
    )
}