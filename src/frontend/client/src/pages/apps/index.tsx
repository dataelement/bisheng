"use client"

import { useQueryClient } from '@tanstack/react-query'
import { Search, X } from "lucide-react"
import { useRef, useState } from "react"
import { useNavigate } from "react-router"
import { addToFrequentlyUsed, getChatOnlineApi, removeFromFrequentlyUsed } from "~/api/apps"
import { Input } from "~/components/ui"
import { useDebounce } from '~/components/ui/MultiSelect'
import { useGetBsConfig } from '~/data-provider'
import { ConversationData, QueryKeys } from "~/data-provider/data-provider/src"
import useToast from '~/hooks/useToast'
import { useLocalize } from '~/hooks'
import store from "~/store"
import { addConversation, generateUUID } from "~/utils"
import { AgentGrid } from "./components/AgentGrid"
import { AgentNavigation } from "./components/AgentNavigation"
import { SearchOverlay } from "./components/SearchOverlay"

export default function AgentCenter() {
    const [searchQuery, setSearchQuery] = useState("")
    const [favorites, setFavorites] = useState<string[]>([])
    const [isSearching, setIsSearching] = useState(false)
    const [searchResults, setSearchResults] = useState([])
    const [searchLoading, setSearchLoading] = useState(false)
    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const sectionRefs = useRef<Record<string, HTMLElement | null>>({})
    const [refreshTrigger, setRefreshTrigger] = useState(0);
    const refreshAgentData = () => {
        setRefreshTrigger(prev => prev + 1);
    }

    const { showToast } = useToast()
    const localize = useLocalize()

    const handleCategoryChange = (categoryId: string) => {
        console.log("点击的标签ID:", categoryId, "当前搜索状态:", isSearching);

        // 1. 清除搜索状态（如果有）
        const wasSearching = !!searchQuery;
        if (wasSearching) {
            setSearchQuery("");
            setIsSearching(false);
        }

        // 2. 定义核心滚动逻辑
        const performScroll = () => {
            if (categoryId === "favorites") {
                // 常用标签：直接滚动到顶部（无需依赖sectionRefs）
                scrollContainerRef.current?.scrollTo({
                    top: 0,
                    behavior: "smooth"
                });
                return;
            }

            // 其他标签：通过sectionRefs查找DOM并滚动
            const targetSection = sectionRefs.current[categoryId];
            if (targetSection && scrollContainerRef.current) {
                const containerRect = scrollContainerRef.current.getBoundingClientRect();
                const sectionRect = targetSection.getBoundingClientRect();
                const relativeTop = sectionRect.top - containerRect.top + scrollContainerRef.current.scrollTop;

                scrollContainerRef.current.scrollTo({
                    top: relativeTop - 20,
                    behavior: "smooth"
                });
            } else {
                console.log("未找到目标分区，但已尝试滚动");
            }
        };

        // 3. 分场景处理
        if (!wasSearching) {
            // 场景1：非搜索状态（AgentGrid已渲染）→ 立即滚动
            performScroll();
        } else {
            // 场景2：从搜索状态切换（AgentGrid需要重新渲染）→ 监听DOM变化后滚动
            const container = scrollContainerRef.current;
            if (!container) return;

            // 停止之前的监听（避免重复）
            let observer: MutationObserver | null = null;

            observer = new MutationObserver((mutations, obs) => {
                // 检查目标分区是否已挂载
                const targetExists = categoryId === "favorites"
                    ? true  // 常用标签无需检查DOM
                    : !!sectionRefs.current[categoryId];

                if (targetExists) {
                    performScroll(); // 执行滚动
                    obs.disconnect(); // 完成后断开
                    observer = null;
                }
            });

            // 监听滚动容器的DOM变化（AgentGrid渲染会改变子元素）
            observer.observe(container, {
                childList: true,    // 监听子元素增减
                subtree: true       // 监听所有后代
            });

            // 安全超时：5秒后强制停止监听（防内存泄漏）
            setTimeout(() => {
                if (observer) {
                    observer.disconnect();
                    // 超时后仍尝试一次滚动（极端情况保底）
                    performScroll();
                }
            }, 2000);
        }
    };

// 修改handleSearchChange函数，实现多页数据加载
const handleSearchChange = async (query: string) => {
    if (query.trim()) {
        setIsSearching(true);
        setSearchLoading(true);
        let allResults: any[] = []; // 存储所有页的结果
        let currentPage = 1;
        const pageSize = 8; // 每页条数（和接口保持一致）

        try {
            // 循环加载所有页数据
            while (true) {
                // 调用接口，禁用默认限制（或按实际需要调整）
                const result = await getChatOnlineApi(
                    currentPage, 
                    query, 
                    -1, 
                    true // 禁用默认限制，或根据接口逻辑调整
                );
                
                const pageData = result.data || [];
                allResults = [...allResults, ...pageData];

                // 终止条件：当前页数据不足一页，说明已加载完所有数据
                if (pageData.length < pageSize) {
                    break;
                }

                currentPage++; // 加载下一页
            }

            // 处理可能的id字段映射（确保id存在）
            const formattedResults = allResults.map(item => ({
                ...item,
                id: item.id || item.agentId || item.flowId // 兼容不同字段名
            }));

            setSearchResults(formattedResults);
        } catch (error) {
            console.error("搜索失败:", error);
            setSearchResults([]);
        } finally {
            setSearchLoading(false);
        }
    } else {
        setIsSearching(false);
        setSearchResults([]);
    }
};

    const handleSearch = useDebounce(handleSearchChange, 360, false)

    const handleSearchClear = () => {
        setSearchQuery("")
        setIsSearching(false)
        setSearchResults([])
    }

    const addToFavorites = async (type: string, id: string) => {
        let mappedType: string;
        if (type === '1') {
            mappedType = 'flow';
        } else if (type === '5') {
            mappedType = 'assistant';
        } else {
            mappedType = 'workflow';
        }


        const res = await addToFrequentlyUsed(mappedType, id);
        console.log(res);
        if (res.status_code === 500) {
            showToast({
                status: 'success',
                message: localize('com_agent_added_success'),
            });
        }
        // 成功时更新收藏列表
        setFavorites(res.data);
        return res;

    }


    const removeFromFavorites = async (userId: string, type: string, id: string) => {
        let mappedType: string;
        if (type === '1') {
            mappedType = 'flow';
        } else if (type === '5') {
            mappedType = 'assistant';
        } else {
            mappedType = 'workflow';
        }
        const res = await removeFromFrequentlyUsed(userId, mappedType, id);
    }

    const clearAllConversations = store.useClearConvoState();
    const { setConversation } = store.useCreateConversationAtom(0);
    const queryClient = useQueryClient();

    const navigate = useNavigate();
    const handleCardClick = (agent) => {
        console.log('agent :>> ', agent);

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

    const { data: bsConfig } = useGetBsConfig()

    return (
        <div className="min-h-screen bg-background">
            {/* Fixed Header */}
            <div className="sticky top-0 z-40 bg-background">
                <div className="container mx-auto px-6 py-6">
                    <div className="mt-2">
                        <h1 className="text-blue-600 text-[32px] truncate max-w-[600px] font-medium mb-2">{bsConfig?.applicationCenterWelcomeMessage || localize('com_app_center_welcome')}</h1>
                        <p className="text-muted-foreground text-base truncate max-w-[600px]">{bsConfig?.applicationCenterDescription || localize('com_app_center_description')}</p>
                    </div>
                    <div className="mt-12 flex items-start justify-between">
                        <AgentNavigation onCategoryChange={handleCategoryChange} onRefresh={refreshAgentData} />
                        <div className="relative w-80 min-w-48">
                            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-blue-500 w-4 h-4" />
                            <Input
                                type="text"
                                placeholder={localize('com_agent_search_placeholder')}
                                value={searchQuery}
                                onChange={(e) => {
                                    setSearchQuery(e.target.value)
                                    handleSearch(e.target.value)
                                }}
                                className="pl-10 pr-10 h-10 rounded-full"
                            />
                            {searchQuery && (
                                <button
                                    onClick={handleSearchClear}
                                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-muted-foreground hover:text-foreground"
                                >
                                    <X className="w-4 h-4" />
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* Scrollable Content */}
            <div className="relative" style={{ height: "calc(100vh - 200px)" }}>
                <div ref={scrollContainerRef} className="container mx-auto px-6 py-6 pb-96 h-full overflow-y-auto scrollbar-hide">
                    
                        <AgentGrid
                            favorites={favorites}
                            onAddToFavorites={addToFavorites}
                            onRemoveFromFavorites={removeFromFavorites}
                            sectionRefs={sectionRefs}
                            refreshTrigger={refreshTrigger}
                            onCardClick={handleCardClick}
                        />
                     {isSearching &&(
                        <SearchOverlay
                            query={searchQuery}
                            results={searchResults}
                            loading={searchLoading}
                            favorites={favorites}
                            onAddToFavorites={addToFavorites}
                            onRemoveFromFavorites={removeFromFavorites}
                            onClose={handleSearchClear}
                            onCardClick={handleCardClick}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}