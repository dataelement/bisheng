import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Loader2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getChatOnlineApi, getUncategorized } from "~/api/apps"
import { ConversationData, QueryKeys } from "~/types/chat"
import store from "~/store"
import { addConversation, cn, copyText, generateUUID } from "~/utils"
import { getAppShareUrl } from './appUtils'
import AppAvator from '~/components/Avator'
import { AgentNavigation } from './components/AgentNavigation'
import { AppSearchBar } from './components/AppSearchBar'
import { useToastContext } from "~/Providers";
import { Button } from "~/components/ui/Button";
import { useLocalize } from "~/hooks";
import { NotificationSeverity } from "~/common";

import { Diamond, Play, Sparkle, Cone, Circle, Cuboid } from "lucide-react"

// --- 组件：装饰背景元素 (保持一定视觉效果) ---
const DecorativeShapes = () => (
    <div className="absolute inset-0 pointer-events-none overflow-hidden flex justify-center">
        {/* 取消固定 1368px 宽度，让其直接在全宽容器中基于百分比/相对位置布局 */}
        <div className="relative w-full max-w-[1400px] h-full">
            <div className="absolute left-[65%] top-[25px] rotate-12 text-blue-200">
                <Circle size={20} className="opacity-80" />
            </div>
            <div className="absolute left-[35%] top-[70px] text-[#d0ddff]">
                <Cuboid size={24} className="opacity-80" />
            </div>
            <div className="absolute left-[32%] top-[20px] rotate-[-20deg] text-[#d0ddff]">
                <Diamond size={20} className="fill-[#d0ddff] opacity-80" />
            </div>
            <div className="absolute left-[70%] top-[60px] rotate-[20deg] text-[#335cff]">
                <Sparkle size={18} className="fill-[#335cff] opacity-40" />
            </div>
            <div className="absolute left-[26%] top-[40px] rotate-[-15deg] text-blue-300">
                <Play size={18} className="opacity-60" />
            </div>
            <div className="absolute left-[75%] top-[30px] rotate-[10deg] text-[#d0ddff]">
                <Cone size={22} className="opacity-80" />
            </div>
        </div>
    </div>
)

// --- 组件：智能体卡片 (广场版 Horizontal) ---
const ExploreCard = ({ agent, onClick, onShare }: { agent: any, onClick: (agent: any) => void, onShare: (agent: any) => void }) => {
    const localize = useLocalize();
    return (
        <div
            onClick={() => onClick(agent)}
            className={cn(
                "group relative content-stretch flex h-[80px] items-center gap-[12px] overflow-clip rounded-[8px] p-[12px] transition-all cursor-pointer",
                "border border-solid border-[#E5E6EB] bg-white",
                "hover:border-[#335CFF] hover:shadow-[0_8px_20px_0_rgba(117,145,212,0.12)]",
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
                <p className="flex-[1_0_0] font-['PingFang_SC'] leading-[20px] text-[14px] text-[#A9AEB8] w-full line-clamp-2 break-words group-hover:hidden whitespace-normal mt-[2px]">
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
    const [refreshTrigger, setRefreshTrigger] = useState(0)

    // --- 新增滚动加载相关状态 ---
    const [page, setPage] = useState(1);
    const [hasMore, setHasMore] = useState(true);
    const loaderRef = useRef<HTMLDivElement>(null);
    const pageSize = 20;

    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const { setConversation } = store.useCreateConversationAtom(0);
    const { showToast } = useToastContext()
    const localize = useLocalize()

    // Modify Fetch Function
    const fetchAgents = useCallback(async (query: string, categoryId: number | string, currentPage: number, isAppend: boolean) => {
        if (loading) return;
        setLoading(true);
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
            setLoading(false);
        }
    }, [loading]);

    useEffect(() => {
        setPage(1);
        setHasMore(true);
        fetchAgents(searchQuery, activeTabId, 1, false);
    }, [searchQuery, activeTabId, refreshTrigger]);

    useEffect(() => {
        if (page > 1) {
            fetchAgents(searchQuery, activeTabId, page, true);
        }
    }, [page]);

    useEffect(() => {
        const observer = new IntersectionObserver((entries) => {
            const target = entries[0];
            if (target.isIntersecting && !loading && hasMore) {
                setPage(prev => prev + 1);
            }
        }, { threshold: 0.1 });

        if (loaderRef.current) {
            observer.observe(loaderRef.current);
        }

        return () => observer.disconnect();
    }, [loading, hasMore]);

    const handleCardClick = (agent: any) => {
        const _chatId = generateUUID(32)
        const flowId = agent.id
        const flowType = agent.flow_type || agent.type

        queryClient.setQueryData<ConversationData>([QueryKeys.allConversations], (convoData) => {
            if (!convoData) {
                return convoData;
            }
            setConversation((prevState: any) => {
                return {
                    ...prevState,
                    conversationId: _chatId
                }
            })
            return addConversation(convoData, {
                conversationId: _chatId,
                createdAt: "",
                endpoint: null,
                endpointType: null,
                model: "",
                flowId,
                flowType: flowType,
                title: agent.name,
                tools: [],
                updatedAt: ""
            });
        });
        navigate(`/chat/${_chatId}/${flowId}/${flowType}`);
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
        <div className="h-screen bg-white pb-20 overflow-auto flex flex-col items-center">
            {/* 顶部标题栏 */}
            <div className="w-full bg-[#fafcff] flex flex-col items-center justify-center py-[32px] overflow-hidden relative shrink-0">
                {/* 返回按钮：固定在头部左上 */}
                <div className="absolute left-4 top-4 z-[20]">
                    <Button
                        variant="ghost"
                        onClick={() => navigate('/apps')}
                        className="h-7 w-7 p-0 rounded-md border border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA] hover:text-[#335cff]"
                    >
                        <ArrowLeft className="size-3.5" />
                    </Button>
                </div>

                <DecorativeShapes />
                <div className="flex flex-col items-center gap-[4px] max-w-[1000px] text-center z-10 w-full px-6">
                    <h1 className="font-['PingFang_SC'] font-semibold leading-[32px] text-[#335cff] text-[24px]">
                        {localize('com_app_center_welcome')}
                    </h1>
                    <p className="font-['PingFang_SC'] text-[#666] text-[14px] leading-[22px]">
                        {localize('com_app_center_description')}
                    </p>
                </div>
            </div>

            {/* 过滤栏 */}
            <div className="w-full max-w-[1000px] flex items-center justify-between z-10 px-6 xl:px-0 py-6">
                <AgentNavigation onCategoryChange={setActiveTabId} onRefresh={() => setRefreshTrigger(prev => prev + 1)} />
                <AppSearchBar query={searchQuery} onSearch={setSearchQuery} />
            </div>

            {/* 智能体网格 */}
            <main className="w-full max-w-[1000px] px-6 xl:px-0">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-[12px]">
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