"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { userContext } from "@/contexts/userContext"
import { copyDashboard, createDashboard, deleteDashboard, duplicateDashboard } from "@/controllers/API/dashboard"
import { useMiniDebounce } from "@/util/hook"
import { cn } from "@/utils"
import { ChevronLeft, ChevronRight, ListIndentDecrease, ListIndentIncrease, Plus, SquarePlusIcon } from "lucide-react"
import type React from "react"
import { useContext, useMemo, useState } from "react"
import { useMutation, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { DashboardsQueryKey } from "../../hook"
import { Dashboard } from "../../types/dataConfig"
import { DashboardListItem } from "./DashboardListItem"
import Tip from "@/components/bs-ui/tooltip/tip"
import { generateUniqueName } from "@/util/utils"

interface DashboardSidebarProps {
    dashboards: Dashboard[]
    selectedId: string | null
    onSelect: (id: string) => void
    onRename: (id: string, newTitle: string) => void
    onDefault: (id: string) => void
    onShare: (id: string) => void
}

export function DashboardSidebar({
    dashboards,
    selectedId,
    onSelect,
    onRename,
    onDefault,
    onShare
}: DashboardSidebarProps) {
    const [searchQuery, setSearchQuery] = useState("")
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { user } = useContext(userContext);

    const canCreate = useMemo(() => {
        return user.web_menu?.includes('create_dashboard') || user.role === 'admin'
    }, [user])

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

        createMutation.mutate(generateUniqueName(dashboards, 'title', `未命名看板`, '(x)'))
    }


    const duplicateMutation = useMutation({
        mutationFn: copyDashboard,
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
    const handleDuplicate = (dashboard: Dashboard) => {
        if (dashboards.length >= 20) {
            toast({
                description: "最多允许创建 20 个看板",
                variant: "error",
            })
            return
        }

        const newTitle = generateUniqueName(dashboards, 'title', `${dashboard.title}-副本`, '(x)')
        if (newTitle.length > 200) {
            return toast({
                description: "名称不能超过 200 字",
                variant: "error",
            })
        }

        duplicateMutation.mutate({ id: dashboard.id, title: newTitle })
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
                "relative h-full bg-background transition-all duration-300 rounded-tl-md",
                isCollapsed ? "w-0" : "w-44  border-r",
            )}
        >
            {
                !isCollapsed && <div className="header relative flex items-center justify-between h-[52px] px-2 pr-11 border-b">
                    <p className="text-base font-bold">看板列表</p>
                    {
                        canCreate && <Tip content={"添加看板"} >
                            <Button variant="ghost" size="icon" onClick={handleCreate}><SquarePlusIcon size={16} /></Button>
                        </Tip>
                    }
                </div>
            }
            <Tip content={isCollapsed ? "展开列表" : "收起列表"} >
                <Button
                    variant={isCollapsed ? "outline" : "ghost"}
                    size="icon"
                    className={"absolute top-2 z-10 bg-background" + (isCollapsed ? " -right-4 size-8" : " right-2")}
                    onClick={() => setIsCollapsed(!isCollapsed)}
                >
                    {isCollapsed ? <ListIndentIncrease className="h-4 w-4" /> : <ListIndentDecrease className="h-4 w-4" />}
                </Button>
            </Tip>


            {!isCollapsed && (
                <div className="flex flex-col p-2 gap-2">
                    <div className="relative">
                        <SearchInput
                            placeholder="Search..."
                            value={searchQuery}
                            onChange={handleSearch}
                            onKeyDown={handleKeyDown}
                        />
                    </div>

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
                                    onDefault={onDefault}
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
