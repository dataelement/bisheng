import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getChatOnlineApi, getUncategorized } from "~/api/apps"
import { ConversationData, QueryKeys } from "~/data-provider/data-provider/src"
import store from "~/store"
import { addConversation, cn, generateUUID } from "~/utils"
import AppAvator from '~/components/Avator'
import { AgentNavigation } from './components/AgentNavigation'
import { AppSearchBar } from './components/AppSearchBar'
import { useToastContext } from "~/Providers";

// --- 组件：装饰背景元素 (保持一定视觉效果) ---
const DecorativeShapes = () => (
    <div className="absolute inset-0 pointer-events-none overflow-hidden flex justify-center">
        <div className="relative w-[1368px] h-full">
            <div className="absolute left-[869px] top-[28px] w-[17px] h-[17px] border-2 border-blue-200 rounded-full" />
            <div className="absolute flex items-center justify-center left-[471px] top-[72px] rotate-[128deg]">
                <div className="w-[18px] h-[18px] border-2 border-[#d0ddff] rounded-sm" />
            </div>
            <div className="absolute flex items-center justify-center left-[445px] top-[25px] rotate-[-30deg]">
                <div className="border-2 border-[#d0ddff] w-[16px] h-[16px]" />
            </div>
            <div className="absolute left-[944px] top-[45px] rotate-[26deg]">
                <div className="w-[20px] h-[10px] border-t-2 border-l-2 border-[#d0ddff]" />
            </div>
        </div>
    </div>
)

// --- 组件：智能体卡片 (广场版 Horizontal) ---
const ExploreCard = ({ agent, onClick, onShare }: { agent: any, onClick: (agent: any) => void, onShare: (agent: any) => void }) => {
    return (
        <div
            onClick={() => onClick(agent)}
            className={cn(
                "group relative border border-solid content-stretch flex gap-[12px] h-[80px] items-center overflow-clip px-[12px] py-[8px] rounded-[8px] transition-all cursor-pointer",
                "border-[#ebecf0] border-[0.5px] hover:border-[#335cff] hover:border-[1.047px] hover:shadow-[0px_8px_20px_0px_rgba(117,145,212,0.12)] bg-white",
                "bg-[linear-gradient(145.87deg,_rgb(249,251,254)_0%,_rgb(255,255,255)_50%,_rgb(249,251,254)_100%)]"
            )}
        >
            {/* 左侧图标 */}
            <AppAvator url={agent.logo} id={agent.id as any} flowType={String(agent.flow_type || agent.type)} className="size-[48px] min-w-[48px] shrink-0 rounded-[4px]" />

            {/* 右侧内容 */}
            <div className="flex flex-[1_0_0] flex-col h-full items-start min-w-px relative">
                <p className="font-['PingFang_SC'] font-medium leading-[22px] text-[#212121] text-[14px] truncate w-full">
                    {agent.name}
                </p>

                {/* 描述区域：平时显示，hover时隐藏 */}
                <p className="flex-[1_0_0] font-['PingFang_SC'] leading-[19.5px] text-[12px] text-[#a9aeb8] w-full line-clamp-2 break-words group-hover:hidden whitespace-normal mt-[2px]">
                    {agent.description || agent.desc || "暂无描述内容..."}
                </p>

                {/* 按纽区域：平时隐藏，hover时显示 */}
                <div className="hidden group-hover:flex flex-[1_0_0] gap-[4px] items-center justify-center min-h-px w-full mt-auto">
                    <button
                        onClick={(e) => { e.stopPropagation(); onShare(agent); }}
                        className="bg-white border border-[#ececec] flex flex-[1_0_0] h-[28px] items-center justify-center px-[10px] rounded-[6px] text-[#212121] text-[14px] font-['PingFang_SC'] hover:bg-gray-50 transition-colors"
                    >
                        分享应用
                    </button>
                    <button
                        onClick={(e) => { e.stopPropagation(); onClick(agent); }}
                        className="bg-[#335cff] flex flex-[1_0_0] h-[28px] items-center justify-center px-[10px] rounded-[6px] text-white text-[14px] font-['PingFang_SC'] hover:bg-blue-600 transition-colors"
                    >
                        开始对话
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

    // Modify Fetch Function
    const fetchAgents = useCallback(async (query: string, categoryId: number | string, currentPage: number, isAppend: boolean) => {
        if (loading) return;
        setLoading(true);
        try {
            const result = categoryId === 'uncategorized'
                ? await getUncategorized(currentPage, pageSize)
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

    const handleShare = (agent: any) => {
        const shareUrl = `${__APP_ENV__.BASE_URL}/share/app_${agent.id}`;
        navigator.clipboard.writeText(shareUrl).then(() => {
            showToast?.({ message: '应用链接已复制到剪贴板', severity: 'success' });
        }).catch(() => {
            showToast?.({ message: '复制应用链接失败', severity: 'error' });
        });
    }

    return (
        <div className="h-screen bg-white pb-20 overflow-auto flex flex-col items-center">
            {/* 顶部标题栏 & 过滤栏 (按 Figma 布局) */}
            <div className="w-full bg-[#fafcff] flex flex-col items-center justify-center py-[32px] overflow-hidden relative shrink-0">
                <DecorativeShapes />
                <div className="flex flex-col items-center gap-[4px] max-w-[1000px] text-center z-10 w-full mb-[32px] px-6">
                    <h1 className="font-['PingFang_SC'] font-semibold leading-[32px] text-[#335cff] text-[24px]">
                        探索BISHENG的智能体
                    </h1>
                    <p className="font-['PingFang_SC'] text-[#666] text-[14px] leading-[22px]">
                        您可以在这里选择需要的智能体来进行生产与工作~
                    </p>
                </div>
                <div className="w-full max-w-[1000px] flex items-center justify-between z-10 px-6 xl:px-0">
                    <AgentNavigation onCategoryChange={setActiveTabId} onRefresh={() => setRefreshTrigger(prev => prev + 1)} />
                    <AppSearchBar query={searchQuery} onSearch={setSearchQuery} />
                </div>
            </div>

            {/* 智能体网格 */}
            <main className="w-full max-w-[1000px] px-6 xl:px-0 mt-[14px]">
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
                            <span className="text-sm font-['PingFang_SC']">正在加载更多智能体...</span>
                        </div>
                    )}
                    {!hasMore && agents.length > 0 && (
                        <p className="text-[#a9aeb8] text-[12px] font-['PingFang_SC'] mt-4">—— 已经到底啦 ——</p>
                    )}
                    {!loading && agents.length === 0 && (
                        <p className="text-[#a9aeb8] text-[14px] font-['PingFang_SC'] mt-4 py-10">暂无找到相关的智能体</p>
                    )}
                </div>
            </main>
        </div>
    )
}