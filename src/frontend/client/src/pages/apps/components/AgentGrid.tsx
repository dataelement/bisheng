"use client"

import { ChevronDown, Loader2 } from "lucide-react"
import type React from "react"
import { useEffect, useMemo, useState } from "react"
import { useRecoilState } from "recoil"
import { getChatOnlineApi, getFrequently, getHomeLabelApi, getUncategorized } from "~/api/apps"
import { Button } from "~/components"
import { addCommonlyAppState } from ".."
import { AgentCard } from "./AgentCard"

// 智能体类型定义
interface Agent {
  id: string
  name: string
  description: string
  logo: string
  category: string
  flow_type: number
  user_id: string
}

// 组件Props类型
interface AgentGridProps {
  favorites: string[] | null
  onAddToFavorites: (type: number, id: string) => void
  onRemoveFromFavorites: (userId: string, type: number, id: string) => void
  sectionRefs: React.MutableRefObject<Record<string, HTMLElement | null>>
  refreshTrigger: number
  onCardClick: (agent: Agent) => void
  onSectionMounted: (id: string, element: HTMLElement | null) => void // 新增回调函数
}

// 分类标签类型
interface Category {
  value: string
  label: string
  selected: boolean
}

// 分页状态类型（含预请求字段）
interface Pagination {
  page: number // 当前已加载到的页码
  hasMore: boolean // 是否有下一页（基于预请求结果）
  preloadedNextPage: Agent[] | null // 预请求的下一页数据（缓存）
  isPreloading: boolean // 是否正在预请求下一页（防重复）
}

export function AgentGrid({
  favorites,
  onAddToFavorites,
  onRemoveFromFavorites,
  sectionRefs,
  refreshTrigger,
  onCardClick,
  onSectionMounted // 新增回调函数
}: AgentGridProps) {
  const pageSize = 8 // 固定单页容量
  const [categories, setCategories] = useState<Category[]>([])
  const [agentsByCategory, setAgentsByCategory] = useState<Record<string, Agent[]>>({})
  const [uncategorizedAgents, setUncategorizedAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState<Record<string, boolean>>({}) // 分类加载状态
  const [uncategorizedLoading, setUncategorizedLoading] = useState(false) // 未分类加载状态
  const [allAgents, setAllAgents] = useState<Agent[]>([]) // 常用智能体数据
  const [frequentlyUsedLoading, setFrequentlyUsedLoading] = useState(false) // 常用加载状态
  const [commonlyApp, addCommonlyApp] = useRecoilState(addCommonlyAppState)

  // 分页状态初始化（含预请求字段）
  const [pagination, setPagination] = useState<Record<string, Pagination>>({})
  const [uncategorizedPagination, setUncategorizedPagination] = useState<Pagination>({
    page: 1,
    hasMore: false,
    preloadedNextPage: null,
    isPreloading: false
  })
  const [frequentlyUsedPagination, setFrequentlyUsedPagination] = useState<Pagination>({
    page: 1,
    hasMore: false,
    preloadedNextPage: null,
    isPreloading: false
  })

  // 判断是否为常用智能体
  const isFavorite = (agentId: string): boolean => {
    return favorites ? favorites.includes(agentId) : false
  }

  // 通用预请求函数：请求下一页数据并更新状态
  const preloadNextPage = async (
    categoryType: "frequently" | "uncategorized" | "category",
    categoryId?: string, // 分类ID（仅分类数据需要）
    currentPage: number = 1
  ) => {
    const nextPageNum = currentPage + 1
    // 避免重复预请求
    if (categoryType === "frequently" && frequentlyUsedPagination.isPreloading) return
    if (categoryType === "uncategorized" && uncategorizedPagination.isPreloading) return
    if (categoryType === "category" && categoryId && pagination[categoryId]?.isPreloading) return

    // 标记为正在预请求
    if (categoryType === "frequently") {
      setFrequentlyUsedPagination(prev => ({ ...prev, isPreloading: true }))
    } else if (categoryType === "uncategorized") {
      setUncategorizedPagination(prev => ({ ...prev, isPreloading: true }))
    } else if (categoryType === "category" && categoryId) {
      setPagination(prev => ({
        ...prev,
        [categoryId]: { ...(prev[categoryId] || initialPagination), isPreloading: true }
      }))
    }

    try {
      // 不同类型的预请求逻辑
      let nextPageData: Agent[] = []
      if (categoryType === "frequently") {
        const res = await getFrequently(nextPageNum, pageSize)
        nextPageData = res.data || []
      } else if (categoryType === "uncategorized") {
        const res = await getUncategorized(nextPageNum, pageSize)
        nextPageData = res.data || []
      } else if (categoryType === "category" && categoryId) {
        const res = await getChatOnlineApi(nextPageNum, "", parseInt(categoryId))
        nextPageData = res.data || []
      }

      // 预请求结果：有数据→hasMore=true，无数据→hasMore=false
      const hasMore = nextPageData.length > 0

      // 更新分页状态（存储预请求数据）
      if (categoryType === "frequently") {
        setFrequentlyUsedPagination(prev => ({
          ...prev,
          hasMore: hasMore,
          preloadedNextPage: nextPageData,
          isPreloading: false
        }))
      } else if (categoryType === "uncategorized") {
        setUncategorizedPagination(prev => ({
          ...prev,
          hasMore: hasMore,
          preloadedNextPage: nextPageData,
          isPreloading: false
        }))
      } else if (categoryType === "category" && categoryId) {
        setPagination(prev => ({
          ...prev,
          [categoryId]: {
            ...(prev[categoryId] || initialPagination),
            hasMore: hasMore,
            preloadedNextPage: nextPageData,
            isPreloading: false
          }
        }))
      }
    } catch (error) {
      console.error(`预请求${categoryType}下一页失败:`, error)
      // 失败默认认为无下一页
      if (categoryType === "frequently") {
        setFrequentlyUsedPagination(prev => ({ ...prev, hasMore: false, isPreloading: false }))
      } else if (categoryType === "uncategorized") {
        setUncategorizedPagination(prev => ({ ...prev, hasMore: false, isPreloading: false }))
      } else if (categoryType === "category" && categoryId) {
        setPagination(prev => ({
          ...prev,
          [categoryId]: { ...(prev[categoryId] || initialPagination), hasMore: false, isPreloading: false }
        }))
      }
    }
  }

  // 初始分页配置
  const initialPagination: Pagination = {
    page: 1,
    hasMore: false,
    preloadedNextPage: null,
    isPreloading: false
  }

  // 1. 加载常用智能体（含预请求）
  const fetchFrequentlyUsed = async (targetPage: number = 1) => {
    setFrequentlyUsedLoading(true);
    try {
      let allLoadedAgents: Agent[] = [];

      // 步骤2：加载「第1页到目标页码」的所有数据（确保数据最新且完整）
      for (let page = 1; page <= targetPage; page++) {
        const res = await getFrequently(page, pageSize);
        const pageAgents = res.data || [];
        allLoadedAgents = [...allLoadedAgents, ...pageAgents];
      }

      // 步骤3：更新数据（覆盖为最新的完整数据）
      setAllAgents(allLoadedAgents);

      // 步骤4：保持分页状态（页码不变），并重新预请求下一页
      setFrequentlyUsedPagination(prev => ({
        ...prev,
        page: targetPage, // 保持当前页码
        preloadedNextPage: null // 清空已使用的预请求数据，避免重复
      }));

      // 步骤5：重新预请求下一页（确保「显示更多」按钮状态正确）
      preloadNextPage("frequently", undefined, targetPage);

    } catch (error) {
      console.error("获取常用助手失败:", error);
    } finally {
      setFrequentlyUsedLoading(false);
    }
  };

  // 2. 加载分类标签
  const fetchCategoryTags = async () => {
    try {
      const res = await getHomeLabelApi()
      const categoryList = (res.data || []).map((tag: any) => ({
        label: tag.name,
        value: tag.id.toString(),
        selected: true
      }))
      setCategories(categoryList)

      // 初始化分类分页状态
      const initPagination: Record<string, Pagination> = {}
      categoryList.forEach((category: Category) => {
        initPagination[category.value] = { ...initialPagination }
      })
      setPagination(initPagination)

      // 加载每个分类的第1页数据
      categoryList.forEach((category: Category) => {
        fetchAgentsForCategory(category.value, 1)
      })

      // 加载未分类数据
      fetchUncategorizedAgents(1)
    } catch (error) {
      console.error("获取分类失败:", error)
    }
  }

  // 3. 加载分类智能体（含预请求）
  const fetchAgentsForCategory = async (categoryId: string, pageNum: number = 1) => {
    setLoading(prev => ({ ...prev, [categoryId]: true }))
    try {
      const res = await getChatOnlineApi(pageNum, "", parseInt(categoryId))
      const agents = res.data || []

      // 首次加载第1页后，预请求第2页
      if (pageNum === 1) {
        preloadNextPage("category", categoryId, pageNum)
      }

      // 累加数据
      setAgentsByCategory(prev => ({
        ...prev,
        [categoryId]: pageNum === 1 ? agents : [...(prev[categoryId] || []), ...agents]
      }))

      // 更新当前页码
      setPagination(prev => ({
        ...prev,
        [categoryId]: {
          ...(prev[categoryId] || initialPagination),
          page: pageNum,
          ...(pageNum > 1 && { preloadedNextPage: null }) // 清空已使用的预请求数据
        }
      }))

      // 后续加载后，预请求新的下一页
      if (pageNum > 1) {
        preloadNextPage("category", categoryId, pageNum)
      }
    } catch (error) {
      console.error(`获取分类 ${categoryId} 失败:`, error)
    } finally {
      setLoading(prev => ({ ...prev, [categoryId]: false }))
    }
  }

  // 4. 加载未分类智能体（含预请求）
  const fetchUncategorizedAgents = async (pageNum: number = 1) => {
    setUncategorizedLoading(true)
    try {
      const res = await getUncategorized(pageNum, pageSize)
      const agents = res.data || []

      // 首次加载第1页后，预请求第2页
      if (pageNum === 1) {
        preloadNextPage("uncategorized", undefined, pageNum)
      }

      // 累加数据
      setUncategorizedAgents(prev => pageNum === 1 ? agents : [...prev, ...agents])

      // 更新当前页码
      setUncategorizedPagination(prev => ({
        ...prev,
        page: pageNum,
        ...(pageNum > 1 && { preloadedNextPage: null }) // 清空已使用的预请求数据
      }))

      // 后续加载后，预请求新的下一页
      if (pageNum > 1) {
        preloadNextPage("uncategorized", undefined, pageNum)
      }
    } catch (error) {
      console.error("获取未分类助手失败:", error)
    } finally {
      setUncategorizedLoading(false)
    }
  }

  // 5. 加载更多（优先使用预请求数据）
  const loadMore = (categoryId: string) => {
    if (categoryId === "frequently_used") {
      const { page, preloadedNextPage } = frequentlyUsedPagination
      const nextPage = page + 1
      // 有预请求数据→直接复用，无则请求
      if (preloadedNextPage && preloadedNextPage.length > 0) {
        setAllAgents(prev => [...prev, ...preloadedNextPage])
        setFrequentlyUsedPagination(prev => ({
          ...prev,
          page: nextPage,
          preloadedNextPage: null // 清空已使用的预请求数据
        }))
        // 复用后预请求新的下一页
        preloadNextPage("frequently", undefined, nextPage)
      } else {
        fetchFrequentlyUsed(nextPage)
      }
    } else if (categoryId === "uncategorized") {
      const { page, preloadedNextPage } = uncategorizedPagination
      const nextPage = page + 1
      if (preloadedNextPage && preloadedNextPage.length > 0) {
        setUncategorizedAgents(prev => [...prev, ...preloadedNextPage])
        setUncategorizedPagination(prev => ({
          ...prev,
          page: nextPage,
          preloadedNextPage: null
        }))
        preloadNextPage("uncategorized", undefined, nextPage)
      } else {
        fetchUncategorizedAgents(nextPage)
      }
    } else {
      const categoryPage = pagination[categoryId] || initialPagination
      const { page, preloadedNextPage } = categoryPage
      const nextPage = page + 1
      if (preloadedNextPage && preloadedNextPage.length > 0) {
        setAgentsByCategory(prev => ({
          ...prev,
          [categoryId]: [...(prev[categoryId] || []), ...preloadedNextPage]
        }))
        setPagination(prev => ({
          ...prev,
          [categoryId]: {
            ...categoryPage,
            page: nextPage,
            preloadedNextPage: null
          }
        }))
        preloadNextPage("category", categoryId, nextPage)
      } else {
        fetchAgentsForCategory(categoryId, nextPage)
      }
    }
  }

  // 6. 移除常用智能体
  const handleRemoveFromFavorites = async (userId: string, type: number, id: string) => {
    try {
      onRemoveFromFavorites(userId, type, id);
      await new Promise(resolve => setTimeout(resolve, 100));
      // 关键修改：传入当前页码，而非固定1
      fetchFrequentlyUsed(frequentlyUsedPagination.page);
    } catch (error) {
      console.error("移除常用助手失败:", error);
    }
  };

  // 7. 添加常用智能体
  const handleAddToFavorites = async (type: number, id: string) => {
    try {
      await onAddToFavorites(type, id);
      // 关键修改：传入当前页码，而非固定1
      fetchFrequentlyUsed(frequentlyUsedPagination.page);
    } catch (error) {
      console.error("添加常用助手失败:", error);
    }
  };
  useEffect(() => {
    if (commonlyApp) {
      handleAddToFavorites(commonlyApp.type, commonlyApp.id)
      addCommonlyApp(null)
    }
  }, [commonlyApp])

  // 8. 初始化加载+刷新触发
  useEffect(() => {
    fetchCategoryTags()
    fetchFrequentlyUsed(1)
  }, [refreshTrigger])

  // 构建分区数据
  const sections = useMemo(() => [
    // 常用智能体
    {
      id: "frequently_used",
      name: "常用智能体",
      agents: allAgents,
      isFavoriteSection: true,
      pagination: frequentlyUsedPagination,
      loading: frequentlyUsedLoading
    },
    // 分类智能体
    ...categories.map(category => ({
      id: category.value,
      name: category.label,
      agents: agentsByCategory[category.value] || [],
      isFavoriteSection: false,
      pagination: pagination[category.value] || initialPagination,
      loading: loading[category.value] || false
    })),
    // 未分类智能体
    {
      id: "uncategorized",
      name: "未分类",
      agents: uncategorizedAgents,
      isFavoriteSection: false,
      pagination: uncategorizedPagination,
      loading: uncategorizedLoading
    }
  ].filter(section => {
    return section.id !== "frequently_used" || section.id !== "uncategorized" || true;
  }), [allAgents, agentsByCategory, categories, frequentlyUsedLoading, frequentlyUsedPagination,
    loading, pagination, uncategorizedAgents, uncategorizedLoading, uncategorizedPagination])

  return (
    <div className="space-y-8">
      {sections.map((section) => {
        const { id, name, agents, isFavoriteSection, pagination, loading } = section
        return (
          <section
            key={id}
            id={id}
            className="relative"
            ref={(el) => {
              sectionRefs.current[id] = el
            }}          >
            {/* 分区标题 */}
            <h2 className={`text-base font-medium mb-4 text-blue-600 ${id === 'frequently_used' && 'hidden'}`}>{name}</h2>

            {/* 加载状态（仅空数据时显示） */}
            {loading && agents.length === 0 ? (
              <div className="flex justify-center items-center h-32">
                <Loader2 className="h-6 w-6 animate-spin text-blue-600" />
              </div>
            ) : (
              <>
                {/* 智能体卡片列表 */}
                <div className="grid grid-cols-4 gap-3">
                  {agents.map((agent) => (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      onClick={() => onCardClick(agent)}
                      isFavorite={isFavorite(agent.id)}
                      showRemove={isFavoriteSection}
                      onAddToFavorites={() => addCommonlyApp({ type: agent.flow_type, id: agent.id })}
                      onRemoveFromFavorites={() => handleRemoveFromFavorites(agent.user_id, agent.flow_type, agent.id)}
                    />
                  ))}
                </div>

                {/* 展示更多按钮（基于预请求结果判断） */}
                {!loading && pagination.hasMore && (
                  <div className="flex justify-end mt-6">
                    <Button
                      variant="default"
                      onClick={() => loadMore(id)}
                      className="h-8 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white"
                      disabled={loading}
                    >
                      {loading ? (
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                      ) : (
                        <ChevronDown size={14} className="mr-1" />
                      )}
                      展示更多
                    </Button>
                  </div>
                )}
              </>
            )}
          </section>
        )
      })}
    </div>
  )
}