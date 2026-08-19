// @ts-strict-ignore
"use client"

import { ChevronDown, Loader2 } from "lucide-react"
import type React from "react"
import { useEffect, useMemo, useState } from "react"
import { useRecoilState } from "recoil"
import { getChatOnlineApi, getFrequently, getHomeLabelApi, getUncategorized } from "~/api/apps"
import { Button } from "~/components"
import { useLocalize } from "~/hooks"
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

// 分页状态类型
// - frequently_used 仍用页码 + 预请求（/app/used 未改，返回 {list,total}）
// - uncategorized / category 改为游标瀑布流：cursor 由后端返回，hasMore 直接读响应
interface Pagination {
  page: number // 当前已加载到的页码（仅 frequently_used 使用）
  hasMore: boolean // 是否有下一页
  preloadedNextPage: Agent[] | null // 预请求的下一页数据（仅 frequently_used 使用）
  isPreloading: boolean // 是否正在预请求下一页（防重复，仅 frequently_used）
  cursor?: string | null // 下一页游标（仅 uncategorized / category 使用）
}

const uncategorizedPageSize = 24

export function AgentGrid({
  favorites,
  onAddToFavorites,
  onRemoveFromFavorites,
  sectionRefs,
  refreshTrigger,
  onCardClick,
  onSectionMounted // 新增回调函数
}: AgentGridProps) {
  const localize = useLocalize()
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

  // 预请求函数：仅用于「常用」列表（/app/used 仍是页码分页、返回 {list,total}）。
  // uncategorized / category 已改为游标瀑布流，hasMore 直接来自后端响应，无需预请求探测。
  const preloadNextPage = async (
    categoryType: "frequently",
    _categoryId?: string,
    currentPage: number = 1
  ) => {
    const nextPageNum = currentPage + 1
    if (frequentlyUsedPagination.isPreloading) return

    setFrequentlyUsedPagination(prev => ({ ...prev, isPreloading: true }))
    try {
      const res = await getFrequently(nextPageNum, pageSize)
      const nextPageData: Agent[] = res.data?.list || []
      const hasMore = nextPageData.length > 0
      setFrequentlyUsedPagination(prev => ({
        ...prev,
        hasMore,
        preloadedNextPage: nextPageData,
        isPreloading: false
      }))
    } catch (error) {
      console.error(`预请求${categoryType}下一页失败:`, error)
      setFrequentlyUsedPagination(prev => ({ ...prev, hasMore: false, isPreloading: false }))
    }
  }

  // 初始分页配置
  const initialPagination: Pagination = {
    page: 1,
    hasMore: false,
    preloadedNextPage: null,
    isPreloading: false,
    cursor: null
  }

  // 1. 加载常用智能体（含预请求）
  const fetchFrequentlyUsed = async (targetPage: number = 1) => {
    setFrequentlyUsedLoading(true);
    try {
      let allLoadedAgents: Agent[] = [];

      // 步骤2：加载「第1页到目标页码」的所有数据（确保数据最新且完整）
      for (let page = 1; page <= targetPage; page++) {
        const res = await getFrequently(page, pageSize);
        const pageAgents = res.data?.list || [];
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

      // 加载每个分类的首屏数据（游标首页）
      categoryList.forEach((category: Category) => {
        fetchAgentsForCategory(category.value)
      })

      // 加载未分类数据（游标首页）
      fetchUncategorizedAgents()
    } catch (error) {
      console.error("获取分类失败:", error)
    }
  }

  // 3. 加载分类智能体（游标瀑布流）。cursor=null 表示首屏。
  const fetchAgentsForCategory = async (categoryId: string, cursor: string | null = null, append = false) => {
    setLoading(prev => ({ ...prev, [categoryId]: true }))
    try {
      const res = await getChatOnlineApi(cursor, "", parseInt(categoryId))
      const agents = res.list || []

      setAgentsByCategory(prev => ({
        ...prev,
        [categoryId]: append ? [...(prev[categoryId] || []), ...agents] : agents
      }))

      setPagination(prev => ({
        ...prev,
        [categoryId]: {
          ...(prev[categoryId] || initialPagination),
          cursor: res.nextCursor,
          hasMore: !!res.hasMore
        }
      }))
    } catch (error) {
      console.error(`获取分类 ${categoryId} 失败:`, error)
    } finally {
      setLoading(prev => ({ ...prev, [categoryId]: false }))
    }
  }

  // 4. 加载未分类智能体（游标瀑布流）。cursor=null 表示首屏。
  const fetchUncategorizedAgents = async (cursor: string | null = null, append = false) => {
    setUncategorizedLoading(true)
    try {
      const res = await getUncategorized(cursor, uncategorizedPageSize)
      const agents = res.list || []

      setUncategorizedAgents(prev => append ? [...prev, ...agents] : agents)

      setUncategorizedPagination(prev => ({
        ...prev,
        cursor: res.nextCursor,
        hasMore: !!res.hasMore
      }))
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
      // 游标瀑布流：用后端返回的下一页游标续拉。
      fetchUncategorizedAgents(uncategorizedPagination.cursor ?? null, true)
    } else {
      const categoryPage = pagination[categoryId] || initialPagination
      fetchAgentsForCategory(categoryId, categoryPage.cursor ?? null, true)
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
      name: localize('com_app_frequently_used'),
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
      name: localize('com_app_uncategorized'),
      agents: uncategorizedAgents,
      isFavoriteSection: false,
      pagination: uncategorizedPagination,
      loading: uncategorizedLoading
    }
  ].filter(section => {
    return section.id !== "frequently_used" || section.id !== "uncategorized" || true;
  }), [allAgents, agentsByCategory, categories, frequentlyUsedLoading, frequentlyUsedPagination,
    loading, pagination, uncategorizedAgents, uncategorizedLoading, uncategorizedPagination, localize])

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
                      className="h-8 px-3 text-xs rounded-md bg-blue-600 hover:bg-blue-700 text-white btn-brand-primary"
                      disabled={loading}
                    >
                      {loading ? (
                        <Loader2 className="h-3 w-3 animate-spin mr-1" />
                      ) : (
                        <ChevronDown size={14} className="mr-1" />
                      )}
                      {localize('com_show_more')}
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