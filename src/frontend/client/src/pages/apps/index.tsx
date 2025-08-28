"use client"

import { useQueryClient } from '@tanstack/react-query'
import { Search, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { addToFrequentlyUsed, getChatOnlineApi, removeFromFrequentlyUsed } from "~/api/apps"
import { Input } from "~/components/ui"
import { ConversationData, QueryKeys } from "~/data-provider/data-provider/src"
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
    // 从本地存储加载收藏列表
    useEffect(() => {
        const savedFavorites = localStorage.getItem('agent-favorites')
        if (savedFavorites) {
            setFavorites(JSON.parse(savedFavorites))
        }
    }, [])

    // 保存收藏列表到本地存储
    useEffect(() => {
        localStorage.setItem('agent-favorites', JSON.stringify(favorites))
    }, [favorites])

    const handleCategoryChange = (categoryId: string) => {
        if (searchQuery) {
            setSearchQuery("")
            setIsSearching(false)
        }

        const targetSection = sectionRefs.current[categoryId]
        if (targetSection && scrollContainerRef.current) {
            const containerTop = scrollContainerRef.current.offsetTop
            const sectionTop = targetSection.offsetTop
            const scrollTop = sectionTop - containerTop - 20

            scrollContainerRef.current.scrollTo({
                top: scrollTop,
                behavior: "smooth",
            })
        }
    }

    const handleSearchChange = async (query: string) => {
        setSearchQuery(query)

        if (query.trim()) {
            setIsSearching(true)
            setSearchLoading(true)
            try {
                const result = await getChatOnlineApi(1, query, -1)
                setSearchResults(result.data || [])
            } catch (error) {
                console.error("搜索失败:", error)
                setSearchResults([])
            } finally {
                setSearchLoading(false)
            }
        } else {
            setIsSearching(false)
            setSearchResults([])
        }
    }

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
                flowType: agent.type,
                title: agent.name,
                tools: [],
                updatedAt: ""
            });
        });
        navigate(`/chat/${_chatId}/${flowId}/10`);
    }

    return (
        <div className="min-h-screen bg-background">
            {/* Fixed Header */}
            <div className="sticky top-0 z-40 bg-background border-b">
                <div className="container mx-auto px-6 py-6">
                    <div className="mt-2">
                        <h1 className="text-blue-600 text-[32px] font-medium mb-2">探索BISHENG的智能体</h1>
                        <p className="text-muted-foreground text-base">您可以在这里选择需要的智能体来进行生产与工作～</p>
                    </div>
                    <div className="mt-12 flex items-center justify-between">
                        <AgentNavigation onCategoryChange={handleCategoryChange} onRefresh={refreshAgentData} />
                        <div className="relative w-80">
                            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-blue-500 w-4 h-4" />
                            <Input
                                type="text"
                                placeholder="搜索您需要的智能体"
                                value={searchQuery}
                                onChange={(e) => handleSearchChange(e.target.value)}
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
                <div ref={scrollContainerRef} className="container mx-auto px-6 py-6 pb-96 h-full overflow-y-auto">
                    {!isSearching ? (
                        <AgentGrid
                            favorites={favorites}
                            onAddToFavorites={addToFavorites}
                            onRemoveFromFavorites={removeFromFavorites}
                            sectionRefs={sectionRefs}
                            refreshTrigger={refreshTrigger}
                            onCardClick={handleCardClick}
                        />
                    ) : (
                        <SearchOverlay
                            query={searchQuery}
                            results={searchResults} // 传递实际搜索结果
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