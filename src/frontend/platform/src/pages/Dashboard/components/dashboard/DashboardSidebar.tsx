"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { userContext } from "@/contexts/userContext"
import { createDashboard, deleteDashboard, duplicateDashboard, type Dashboard } from "@/controllers/API/dashboard"
import { useMiniDebounce } from "@/util/hook"
import { cn } from "@/utils"
import { ChevronLeft, ChevronRight, Plus } from "lucide-react"
import type React from "react"
import { useContext, useMemo, useState } from "react"
import { useMutation, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { DashboardsQueryKey } from "../../hook"
import { DashboardListItem } from "./DashboardListItem"

interface DashboardSidebarProps {
    dashboards: Dashboard[]
    selectedId: string | null
    onSelect: (id: string) => void
    onRename: (id: string, newTitle: string) => void
    onShare: (id: string) => void
}

export function DashboardSidebar({
    dashboards,
    selectedId,
    onSelect,
    onRename,
    onShare
}: DashboardSidebarProps) {
    const [searchQuery, setSearchQuery] = useState("")
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { user } = useContext(userContext);
    console.log('user :>> ', user.web_menu);

    const filteredDashboards = useMemo(() => {
        if (!searchQuery.trim()) return dashboards

        return dashboards.filter((dashboard) => dashboard.title.toLowerCase().includes(searchQuery.toLowerCase()))
    }, [dashboards, searchQuery])

    const handleSearch = useMiniDebounce((e: React.ChangeEvent<HTMLInputElement>) => {
        setSearchQuery(e.target.value)
    }, 300)

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            // Search is already triggered by debounce
        }
    }
    const navigator = useNavigate()
    const { toast } = useToast()
    const queryClient = useQueryClient()
    const createMutation = useMutation({
        mutationFn: createDashboard,
        onSuccess: (res) => {
            onSelect(res.id)
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            navigator(`/dashboard/${res.id}`)
        },
        onError: () => {
            toast({
                description: "创建失败，请重试",
                variant: "error",
            })
        },
    })
    const handleCreate = () => {
        if (dashboards.length >= 20) {
            toast({
                description: "最多允许创建 20 个看板",
                variant: "error",
            })
            return
        }

        createMutation.mutate({
            title: `未命名看板`,
        })
    }


    const duplicateMutation = useMutation({
        mutationFn: duplicateDashboard,
        onSuccess: (newDashboard) => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            onSelect(newDashboard.id)
            // 跳转编辑页
        },
        onError: () => {
            toast({
                description: "复制失败",
                variant: "error",
            })
        },
    })
    const handleDuplicate = (id: string) => {
        if (dashboards.length >= 20) {
            toast({
                description: "最多允许创建 20 个看板",
                variant: "error",
            })
            return
        }

        duplicateMutation.mutate(id)
    }



    const deleteMutation = useMutation({
        mutationFn: deleteDashboard,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            if (selectedId && dashboards.length > 1) {
                const index = dashboards.findIndex((d) => d.id === selectedId)
                if (index !== -1) {
                    const nextDashboard = dashboards[index + 1] || dashboards[index - 1]
                    onSelect(nextDashboard?.id || null)
                }
            } else {
                onSelect(null)
            }
            toast({
                description: "已删除",
                variant: "success"
            })
        },
        onError: () => {
            toast({
                description: "删除失败",
                variant: "error",
            })
        },
    })
    const handleDelete = (id: string) => {
        const dashboard = dashboards.find((d) => d.id === id)
        if (!dashboard) return

        bsConfirm({
            desc: `确认删除${dashboard.title}？删除后不可恢复。`,
            okTxt: "删除",
            onOk(next) {
                deleteMutation.mutate(id)
                next()
            },
        })
    }

    return (
        <div
            className={cn(
                "relative h-full border-r bg-background transition-all duration-300",
                isCollapsed ? "w-0" : "w-52",
            )}
        >
            <Button
                variant="ghost"
                size="icon"
                className="absolute -right-3 top-4 z-10 h-6 w-6 rounded-full border bg-background"
                onClick={() => setIsCollapsed(!isCollapsed)}
            >
                {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </Button>

            {!isCollapsed && (
                <div className="flex flex-col h-full p-4 gap-4">
                    <div className="relative">
                        <SearchInput
                            placeholder="看板名称"
                            value={searchQuery}
                            onChange={handleSearch}
                            onKeyDown={handleKeyDown}
                        />
                    </div>

                    {
                        user.web_menu && <Button onClick={handleCreate} className="w-full" disabled={dashboards.length >= 20}>
                            <Plus className="h-4 w-4 mr-2" />
                            添加看板
                        </Button>
                    }

                    <div className="flex-1 overflow-y-auto space-y-1">
                        {filteredDashboards.length === 0 ? (
                            <div className="text-center text-muted-foreground text-sm py-8">
                                {searchQuery ? "未找到匹配的看板" : "暂无看板"}
                            </div>
                        ) : (
                            filteredDashboards.map((dashboard) => (
                                <DashboardListItem
                                    key={dashboard.id}
                                    dashboard={dashboard}
                                    selected={selectedId === dashboard.id}
                                    onSelect={() => onSelect(dashboard.id)}
                                    onRename={onRename}
                                    onDuplicate={handleDuplicate}
                                    onShare={onShare}
                                    onDelete={handleDelete}
                                />
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
