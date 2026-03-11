import { ChevronDown, Loader2, MessageSquare, Pin, Search, Share2, X, LayoutGrid, ArrowRight } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { getFrequently } from "~/api/apps"
import { Button } from "~/components/ui"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "~/components/ui/Tooltip2"
import { cn } from "~/utils"

const EmptyState = () => (
    <div className="flex flex-col items-center justify-center py-20 flex-1">
        <div className="mb-6 opacity-80">
            <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                    d="M60 15L98.9711 37.5V82.5L60 105L21.0289 82.5V37.5L60 15Z"
                    stroke="#3B82F6"
                    strokeWidth="2"
                    strokeDasharray="4 4"
                />
                <circle cx="60" cy="60" r="22" stroke="#3B82F6" strokeWidth="2" />
                <circle cx="60" cy="60" r="6" stroke="#3B82F6" strokeWidth="2" strokeDasharray="2 2" />
            </svg>
        </div>
        <div className="text-sm text-gray-500 flex items-center gap-1">
            暂无使用过的应用，可以前往应用广场
            <Link
                to="/apps/explore"
                className="text-blue-500 hover:text-blue-600 flex items-center font-medium transition-colors"
            >
                探索更多应用
                <ArrowRight size={14} className="ml-0.5" />
            </Link>
        </div>
    </div>
)

const SearchEmptyState = ({ query }: { query: string }) => (
    <div className="flex flex-col items-center justify-center py-20 flex-1">
        <div className="mb-6 opacity-80">
            <Search size={80} className="text-gray-300" />
        </div>
        <p className="text-sm text-gray-500">
            找不到和“
            <span className="font-semibold text-gray-700 max-w-[200px] inline-block truncate align-bottom">
                {query}
            </span>
            ”相关的应用
        </p>
    </div>
)
// --- 组件：智能体卡片 ---
const AgentCard = ({
    agent,
    isPinned,
    onTogglePin,
    onStartChat,
    onShare
}: {
    agent: any,
    isPinned: boolean,
    onTogglePin: (agent: any) => void,
    onStartChat: (agent: any) => void,
    onShare: (agent: any) => void
}) => (
    <div className="group relative flex flex-col justify-between rounded-xl border hover:border-blue-400 bg-white p-4 shadow-sm transition-all hover:shadow-md h-[190px]">
        <div className="flex justify-between items-start">
            <div className="flex gap-3 min-w-0">
                <div className="h-12 w-12 flex-shrink-0 rounded-lg bg-purple-100 flex items-center justify-center overflow-hidden">
                    {agent.logo ? (
                        <img src={agent.logo} alt={agent.name} className="h-full w-full object-cover" />
                    ) : (
                        <div className="text-purple-500 italic font-bold text-xl">✨</div>
                    )}
                </div>
                <h3 className="text-base font-bold text-gray-800 truncate mt-1">{agent.name}</h3>
            </div>
            <TooltipProvider delayDuration={200}>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <button
                            onClick={(e) => { e.stopPropagation(); onTogglePin(agent); }}
                            className={cn(
                                "p-1.5 rounded-md transition-colors",
                                isPinned ? "text-blue-600 bg-blue-50" : "text-gray-300 hover:text-gray-500 bg-gray-50/50"
                            )}
                        >
                            <Pin size={16} fill={isPinned ? "currentColor" : "none"} />
                        </button>
                    </TooltipTrigger>
                    <TooltipContent>{isPinned ? "取消置顶" : "将应用置顶"}</TooltipContent>
                </Tooltip>
            </TooltipProvider>
        </div>
        <p className="mt-3 text-sm text-gray-400 line-clamp-2 leading-relaxed">
            {agent.description || "暂无描述内容..."}
        </p>
        <div className="mt-4 flex gap-2">
            <Button variant="outline" className="flex-1 h-9 rounded-lg border-gray-200 text-gray-600 text-sm font-normal" onClick={() => onShare(agent)}>
                分享应用
            </Button>
            <Button className="flex-1 h-9 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-normal" onClick={() => onStartChat(agent)}>
                开始对话
            </Button>
        </div>
    </div>
)

export default function AppCenter({
    favorites,
    onAddToFavorites,
    onRemoveFromFavorites,
    refreshTrigger,
    onCardClick
}: any) {
    const [loading, setLoading] = useState(false)
    const [allAgents, setAllAgents] = useState<any[]>([])
    const [pinnedIds, setPinnedIds] = useState<string[]>(favorites || [])
    const [isSearchOpen, setIsSearchOpen] = useState(false)
    const [searchQuery, setSearchQuery] = useState("")
    const inputRef = useRef<HTMLInputElement>(null)

    const sortedAndFilteredAgents = useMemo(() => {
        const filtered = searchQuery
            ? allAgents.filter(agent =>
                agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                (agent.description || '').toLowerCase().includes(searchQuery.toLowerCase())
            )
            : allAgents;

        return [...filtered].sort((a, b) => {
            const bPinned = pinnedIds.includes(b.id);
            const aPinned = pinnedIds.includes(a.id);
            return (bPinned ? 1 : 0) - (aPinned ? 1 : 0);
        });
    }, [allAgents, pinnedIds, searchQuery]);

    useEffect(() => {
        const fetchAgents = async () => {
            setLoading(true)
            try {
                const res = await getFrequently(1, 24)
                setAllAgents(res.data || [])
            } finally {
                setLoading(false)
            }
        }
        fetchAgents()
    }, [refreshTrigger])

    const handleTogglePin = (agent: any) => {
        const isPinned = pinnedIds.includes(agent.id)
        if (isPinned) {
            setPinnedIds(prev => prev.filter(id => id !== agent.id))
            onRemoveFromFavorites?.(agent.user_id, agent.flow_type, agent.id)
        } else {
            setPinnedIds(prev => [...prev, agent.id])
            onAddToFavorites?.(agent.flow_type, agent.id)
        }
    }

    return (
        <div className="p-8 max-w-7xl mx-auto min-h-screen flex flex-col">
            {/* 顶部页眉 - 无论是否有数据都显示 */}
            <header className="flex justify-between items-end mb-8">
                <div className="space-y-1">
                    <h1 className="text-2xl font-bold text-blue-600">应用中心</h1>
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-gray-400">最近使用过的应用都在这里~</span>
                        <Link to="/apps/explore" className="flex items-center gap-1.5 text-sm text-gray-500 cursor-pointer hover:text-blue-500 transition-colors">
                            <LayoutGrid size={14} className="text-blue-400" />
                            <span>探索更多应用</span>
                        </Link>
                    </div>
                </div>

                <div className={cn(
                    "flex items-center bg-gray-50 border border-gray-100 rounded-lg px-3 py-1.5 transition-all",
                    isSearchOpen || searchQuery ? "w-64" : "w-10 h-10 justify-center cursor-pointer"
                )} onClick={() => !isSearchOpen && setIsSearchOpen(true)}>
                    <Search size={18} className="text-gray-400 flex-shrink-0" />
                    {(isSearchOpen || searchQuery) && (
                        <>
                            <input
                                ref={inputRef}
                                autoFocus
                                value={searchQuery}
                                onChange={e => setSearchQuery(e.target.value)}
                                className="ml-2 w-full bg-transparent outline-none text-sm"
                                placeholder="搜索应用..."
                                onBlur={() => {
                                    if (!searchQuery) {
                                        setIsSearchOpen(false)
                                    }
                                }}
                            />
                            {searchQuery && (
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        setSearchQuery('');
                                        inputRef.current?.focus();
                                    }}
                                    className="text-gray-400 hover:text-gray-600"
                                >
                                    <X size={16} />
                                </button>
                            )}
                        </>
                    )}
                </div>
            </header>

            {/* 内容区域 */}
            {loading ? (
                <div className="flex flex-1 items-center justify-center">
                    <Loader2 className="animate-spin text-blue-500" />
                </div>
            ) : sortedAndFilteredAgents.length === 0 ? (
                searchQuery ? <SearchEmptyState query={searchQuery} /> : <EmptyState />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                    {sortedAndFilteredAgents.map(agent => (
                        <AgentCard
                            key={agent.id}
                            agent={agent}
                            isPinned={pinnedIds.includes(agent.id)}
                            onTogglePin={handleTogglePin}
                            onStartChat={onCardClick}
                            onShare={() => { }}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}