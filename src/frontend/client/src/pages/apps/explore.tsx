import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Search, Share2, Sparkles } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getChatOnlineApi, getUncategorized } from "~/api/apps"
import { Button, Input } from "~/components/ui"
import { ConversationData, QueryKeys } from "~/data-provider/data-provider/src"
import store from "~/store"
import { addConversation, cn, generateUUID } from "~/utils"
import { AgentNavigation } from './components/AgentNavigation'

// --- 组件：装饰背景元素 ---
const DecorativeShapes = () => (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-10 left-[20%] w-4 h-4 border-2 border-blue-200 rotate-12" />
        <div className="absolute top-24 left-[25%] w-3 h-3 bg-blue-100 rounded-full" />
        <div className="absolute top-12 right-[22%] w-5 h-5 border-2 border-blue-100 rounded-sm rotate-45" />
        <div className="absolute top-28 right-[28%] text-blue-200"><Sparkles size={16} /></div>
    </div>
)

// --- 组件：智能体卡片 (广场版) ---
const ExploreCard = ({ agent, onClick }: { agent: any, onClick: (agent: any) => void }) => {
    // 简单的类型映射颜色
    const getTypeStyle = (type: string) => {
        const map: Record<string, { color: string, iconColor: string, icon: string }> = {
            '1': { color: 'bg-purple-100', iconColor: 'text-purple-500', icon: '🪄' },
            '2': { color: 'bg-blue-100', iconColor: 'text-blue-500', icon: '🔗' },
            '5': { color: 'bg-orange-100', iconColor: 'text-orange-500', icon: '🤖' },
        }
        // 默认
        return map[type] || { color: 'bg-gray-100', iconColor: 'text-gray-500', icon: '🧩' }
    }

    const style = getTypeStyle(String(agent.flow_type || agent.type));

    return (
        <div
            onClick={() => onClick(agent)}
            className="group relative flex items-start gap-4 rounded-xl border border-gray-100 bg-white p-5 transition-all hover:border-blue-400 hover:shadow-md cursor-pointer h-[120px]"
        >
            {/* 左侧图标 */}
            <div className={cn("h-12 w-12 flex-shrink-0 rounded-xl flex items-center justify-center", style.color)}>
                <div className={cn("font-bold text-xl", style.iconColor)}>
                    {style.icon}
                </div>
            </div>

            {/* 右侧内容 */}
            <div className="flex-1 min-w-0">
                <h3 className="text-base font-bold text-gray-800 mb-1">{agent.name}</h3>
                <p className="text-xs text-gray-400 line-clamp-2 leading-relaxed group-hover:opacity-0 transition-opacity">
                    {agent.description || agent.desc || '暂无描述'}
                </p>
            </div>

            {/* Hover 覆盖层：操作按钮 */}
            <div className="absolute left-[76px] right-4 bottom-4 hidden group-hover:flex gap-2 animate-in fade-in slide-in-from-bottom-2 duration-200">
                <Button variant="outline" size="sm" className="flex-1 h-8 text-xs border-gray-200 text-gray-600 hover:bg-gray-50">
                    <Share2 size={12} className="mr-1" /> 分享应用
                </Button>
                <Button size="sm" className="flex-1 h-8 text-xs bg-blue-600 hover:bg-blue-700 text-white" onClick={(e) => { e.stopPropagation(); onClick(agent); }}>
                    开始对话
                </Button>
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
    const pageSize = 20; // 建议减小单次加载量以优化体验

    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const { setConversation } = store.useCreateConversationAtom(0);

    // 修改 Fetch 函数，支持分页
    const fetchAgents = useCallback(async (query: string, categoryId: number | string, currentPage: number, isAppend: boolean) => {
        if (loading) return;
        setLoading(true);
        try {
            const result = categoryId === 'uncategorized'
                ? await getUncategorized(currentPage, pageSize)
                : await getChatOnlineApi(currentPage, query, categoryId, pageSize);

            const pageData = result.data || [];

            const formattedResults = pageData.map((item: any) => ({
                ...item,
                id: item.id || item.agentId || item.flowId
            }));

            // 如果是追加模式（滚动加载），合并数组；否则替换（切换分类/搜索）
            setAgents(prev => isAppend ? [...prev, ...formattedResults] : formattedResults);

            // 判断是否还有下一页 (根据后端返回的总数或当前返回长度判断)
            setHasMore(pageData.length === pageSize);
        } catch (error) {
            console.error("Failed to fetch agents:", error);
            if (!isAppend) setAgents([]);
        } finally {
            setLoading(false);
        }
    }, [loading]);

    // 监听：分类或搜索变化时，重置页码和列表
    useEffect(() => {
        setPage(1);
        setHasMore(true);
        // 注意：这里直接调用 fetch，isAppend 为 false
        fetchAgents(searchQuery, activeTabId, 1, false);
    }, [searchQuery, activeTabId, refreshTrigger]);

    // 监听：页码变化时（且不是第一页），执行追加加载
    useEffect(() => {
        if (page > 1) {
            fetchAgents(searchQuery, activeTabId, page, true);
        }
    }, [page]);

    // 滚动监测逻辑：利用 IntersectionObserver
    useEffect(() => {
        const observer = new IntersectionObserver((entries) => {
            const target = entries[0];
            // 当底部节点可见、且不在加载中、且还有更多数据时，增加页码
            if (target.isIntersecting && !loading && hasMore) {
                setPage(prev => prev + 1);
            }
        }, { threshold: 0.1 });

        if (loaderRef.current) {
            observer.observe(loaderRef.current);
        }

        return () => observer.disconnect();
    }, [loading, hasMore]);

    // 点击卡片进入对话
    const handleCardClick = (agent: any) => {
        const _chatId = generateUUID(32)
        const flowId = agent.id
        const flowType = agent.flow_type || agent.type

        // 新建会话
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

    return (
        <div className="h-screen bg-white pb-20 overflow-auto">
            {/* 顶部标题栏 & 过滤栏 (保持不变) */}
            <header className="relative pt-12 pb-16 text-center">
                <DecorativeShapes />
                <h1 className="text-3xl font-bold text-blue-600 mb-3 tracking-tight">探索BISHENG的智能体</h1>
                <p className="text-gray-400 text-sm">您可以在这里选择需要的智能体来进行生产与工作~</p>
            </header>

            <div className="max-w-6xl mx-auto px-6 mb-10 flex items-center justify-between">
                <AgentNavigation onCategoryChange={setActiveTabId} onRefresh={() => setRefreshTrigger(prev => prev + 1)} />
                <div className="relative w-64">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                    <Input
                        type="text"
                        placeholder="搜索应用..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="pl-10 h-10 rounded-lg border-gray-200 bg-white focus-visible:ring-blue-500"
                    />
                </div>
            </div>

            {/* 智能体网格 */}
            <main className="max-w-6xl mx-auto px-6">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                    {agents.map((agent, idx) => (
                        <ExploreCard key={`${agent.id}-${idx}`} agent={agent} onClick={handleCardClick} />
                    ))}
                </div>

                {/* 滚动触发器 & 加载状态显示 */}
                <div ref={loaderRef} className="flex justify-center py-10">
                    {loading && (
                        <div className="flex items-center gap-2 text-blue-500">
                            <Loader2 className="animate-spin" size={24} />
                            <span className="text-sm">正在加载更多智能体...</span>
                        </div>
                    )}
                    {!hasMore && agents.length > 0 && (
                        <p className="text-gray-400 text-sm">—— 已经到底啦 ——</p>
                    )}
                </div>
            </main>
        </div>
    )
}