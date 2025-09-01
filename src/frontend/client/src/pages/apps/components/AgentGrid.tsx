"use client"

import type React from "react"
import { useEffect, useState } from "react"
import { AgentCard } from "./AgentCard"
import { Button } from "~/components"
import { ChevronDown, Loader2 } from "lucide-react"
import { getHomeLabelApi, getChatOnlineApi, getFrequently, getUncategorized, removeFromFrequentlyUsed } from "~/api/apps"

interface Agent {
  id: string
  name: string
  description: string
  icon: string
  category: string
  type: number
  userId: string
}

interface AgentGridProps {
  favorites: string[] | null
  onAddToFavorites: (type: number, id: string) => void
  onRemoveFromFavorites: (userId: string, type: number, id: string) => void
  sectionRefs: React.MutableRefObject<Record<string, HTMLElement | null>>
  refreshTrigger: number
  onCardClick: (agent: Agent) => void
}

interface Category {
  value: string
  label: string
  selected: boolean
}

export function AgentGrid({ favorites, onAddToFavorites, onRemoveFromFavorites, sectionRefs, refreshTrigger, onCardClick }: AgentGridProps) {
  const [categories, setCategories] = useState<Category[]>([])
  const [agentsByCategory, setAgentsByCategory] = useState<Record<string, Agent[]>>({})
  const [uncategorizedAgents, setUncategorizedAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState<Record<string, boolean>>({})
  const [uncategorizedLoading, setUncategorizedLoading] = useState(false)
  const [pagination, setPagination] = useState<Record<string, { page: number; total: number; hasMore: boolean }>>({})
  const [uncategorizedPagination, setUncategorizedPagination] = useState({ page: 1, total: 0, hasMore: true })
  const [categoriesLoading, setCategoriesLoading] = useState(true)
  const [allAgents, setAllAgents] = useState<Agent[]>([])
  const [frequentlyUsedPagination, setFrequentlyUsedPagination] = useState({ page: 1, total: 0, hasMore: true }) // 新增：常用助手分页
  const [frequentlyUsedLoading, setFrequentlyUsedLoading] = useState(false) // 新增：常用助手加载状态

  const isFavorite = (agentId: string): boolean => {
    return favorites ? favorites.includes(agentId) : false
  }

  const fetchFrequentlyUsed = async (pageNum: number = 1) => {
    setFrequentlyUsedLoading(true)
    try {
      const result = await getFrequently(pageNum, 8) // 添加分页参数
      console.log("常用助手数据:", result.data)

      const agents: Agent[] = result.data.map((item: any) => ({
        id: item.id.toString(),
        type: item.flow_type,
        name: item.name,
        description: item.description || "暂无描述",
        icon: "🤖",
        userId: item.user_id.toString(),
        category: "frequently_used"
      }))

      setAllAgents(prev =>
        pageNum === 1 ? agents : [...prev, ...agents]
      )

      // 设置分页信息
      const hasMore = agents.length === 8
      setFrequentlyUsedPagination({
        page: pageNum,
        total: result.total,
        hasMore
      })
    } catch (error) {
      console.error("获取常用助手失败:", error)
    } finally {
      setFrequentlyUsedLoading(false)
    }
  }

  useEffect(() => {
    fetchFrequentlyUsed(1) // 初始加载第一页
  }, [refreshTrigger])

  const fetchCategoryTags = async () => {
    try {
      setCategoriesLoading(true)
      const tags = await getHomeLabelApi()
      console.log("获取到的分类标签:", tags.data)

      const categoryList = tags.data.map((tag: any) => ({
        label: tag.name,
        value: tag.id.toString(),
        selected: true
      }))

      setCategories(categoryList)

      const initialPagination: Record<string, { page: number; total: number; hasMore: boolean }> = {}
      const initialLoading: Record<string, boolean> = {}

      categoryList.forEach((category: Category) => {
        initialPagination[category.value] = { page: 1, total: 0, hasMore: true }
        initialLoading[category.value] = true
      })

      setPagination(initialPagination)
      setLoading(initialLoading)

      categoryList.forEach((category: Category) => {
        fetchAgentsForCategory(category.value, 1)
      })

      fetchUncategorizedAgents(1)
    } catch (error) {
      console.error("获取分类失败:", error)
    } finally {
      setCategoriesLoading(false)
    }
  }

  const fetchAgentsForCategory = async (categoryId: string, pageNum: number) => {
    setLoading(prev => ({ ...prev, [categoryId]: true }))

    try {
      console.log(`获取分类 ${categoryId} 的数据，页码: ${pageNum}`)

      const result = await getChatOnlineApi(
        pageNum,
        "",
        parseInt(categoryId),
      )

      console.log(`分类 ${categoryId} 获取到的数据:`, result)

      const agents: Agent[] = result.data.map((item: any) => ({
        id: item.id.toString(),
        type: item.flow_type,
        name: item.name,
        description: item.description || "暂无描述",
        icon: "🤖",
        userId: item.user_id.toString(),
        category: categoryId
      }))

      setAgentsByCategory(prev => ({
        ...prev,
        [categoryId]: pageNum === 1
          ? agents
          : [...(prev[categoryId] || []), ...agents]
      }))

      const hasMore = agents.length === 8

      setPagination(prev => ({
        ...prev,
        [categoryId]: {
          page: pageNum,
          total: result.total,
          hasMore
        }
      }))
    } catch (error) {
      console.error(`获取分类 ${categoryId} 的助手失败:`, error)
    } finally {
      setLoading(prev => ({ ...prev, [categoryId]: false }))
    }
  }

  const fetchUncategorizedAgents = async (pageNum: number) => {
    setUncategorizedLoading(true)

    try {
      console.log(`获取未分类数据，页码: ${pageNum}`)

      const result = await getUncategorized(pageNum, 8)

      console.log(`未分类获取到的数据:`, result)

      const agents: Agent[] = result.data.map((item: any) => ({
        id: item.id.toString(),
        type: item.flow_type,
        name: item.name,
        description: item.description || "暂无描述",
        icon: "🤖",
        userId: item.user_id.toString(),
        category: "uncategorized"
      }))

      setUncategorizedAgents(prev =>
        pageNum === 1 ? agents : [...prev, ...agents]
      )

      const hasMore = agents.length === 8

      setUncategorizedPagination({
        page: pageNum,
        total: result.total,
        hasMore
      })
    } catch (error) {
      console.error("获取未分类助手失败:", error)
    } finally {
      setUncategorizedLoading(false)
    }
  }

  const loadMore = (categoryId: string) => {
    if (categoryId === "frequently_used") {
      const nextPage = frequentlyUsedPagination.page + 1
      fetchFrequentlyUsed(nextPage)
    } else if (categoryId === "uncategorized") {
      const nextPage = uncategorizedPagination.page + 1
      fetchUncategorizedAgents(nextPage)
    } else {
      const nextPage = (pagination[categoryId]?.page || 1) + 1
      fetchAgentsForCategory(categoryId, nextPage)
    }
  }

  const handleRemoveFromFavorites = async (userId: string, type: number, id: string) => {
    try {
      await removeFromFrequentlyUsed(userId, type, id)
      onRemoveFromFavorites(userId, type, id)
      // 重新加载第一页常用助手
      fetchFrequentlyUsed(1)
    } catch (error) {
      console.error("移除常用助手失败:", error)
    }
  }

  const handleAddToFavorites = async (type: number, id: string) => {
    try {
      await onAddToFavorites(type, id)
      // 重新加载第一页常用助手
      fetchFrequentlyUsed(1)
    } catch (error) {
      console.error("添加常用助手失败:", error)
    }
  }

  useEffect(() => {
    fetchCategoryTags()
    fetchFrequentlyUsed(1)
  }, [refreshTrigger])

  const sections = [
    {
      id: "frequently_used",
      name: "常用",
      agents: allAgents,
      isFavoriteSection: true,
      pagination: frequentlyUsedPagination,
      loading: frequentlyUsedLoading
    },
    ...categories.map(category => ({
      id: category.value,
      name: category.label,
      agents: agentsByCategory[category.value] || [],
      isFavoriteSection: false,
      pagination: pagination[category.value] || { page: 1, total: 0, hasMore: false },
      loading: loading[category.value] || false
    })),
    {
      id: "uncategorized",
      name: "未分类",
      agents: uncategorizedAgents,
      isFavoriteSection: false,
      pagination: uncategorizedPagination,
      loading: uncategorizedLoading
    }
  ]

  return (
    <div className="space-y-8">
      {sections.map((section) => {
        if (section.id === "frequently_used" && section.agents.length === 0) {
          return null
        }

        if (section.id === "uncategorized" && section.agents.length === 0) {
          return null
        }

        const categoryPagination = section.pagination
        const categoryLoading = section.loading

        return (
          <section
            key={section.id}
            className="relative"
            ref={(el) => {
              sectionRefs.current[section.id] = el
            }}
          >
            <h2 className="text-base font-medium mb-4 text-blue-600">{section.name}</h2>

            {categoryLoading && section.agents.length === 0 ? (
              <div className="flex justify-center items-center h-32">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            ) : (
              <>
                <div className="grid grid-cols-4 gap-2">
                  {section.agents.map((agent) => (
                    <AgentCard
                      key={agent.id}
                      agent={agent}
                      onClick={() => onCardClick(agent)}
                      isFavorite={isFavorite(agent.id)}
                      showRemove={section.isFavoriteSection}
                      onAddToFavorites={() => handleAddToFavorites(agent.type, agent.id)}
                      onRemoveFromFavorites={() => handleRemoveFromFavorites(agent.userId, agent.type, agent.id)}
                    />
                  ))}
                </div>

                {categoryPagination.hasMore && (
                  <div className="flex justify-end mt-6">
                    <Button
                      variant="default"
                      onClick={() => loadMore(section.id)}
                      className="h-7 px-2 text-xs"
                      disabled={categoryLoading}
                    >
                      {categoryLoading ? (
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