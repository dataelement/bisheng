"use client"

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import Tip from "@/components/bs-ui/tooltip/tip"
import { userContext } from "@/contexts/userContext"
import { copyDashboard, createDashboard, deleteDashboard } from "@/controllers/API/dashboard"
import { useMiniDebounce } from "@/util/hook"
import { generateUniqueName } from "@/util/utils"
import { cn } from "@/utils"
import { ListIndentDecrease, ListIndentIncrease, SquarePlusIcon } from "lucide-react"
import type React from "react"
import { useContext, useMemo, useState } from "react"
import { useMutation, useQueryClient } from "react-query"
import { useNavigate } from "react-router-dom"
import { DashboardsQueryKey } from "../../hook"
import { Dashboard } from "../../types/dataConfig"
import { DashboardListItem } from "./DashboardListItem"
import { useTranslation } from "react-i18next"
import { ExpandIcon } from "@/components/bs-icons/expand"

interface DashboardSidebarProps {
    dashboards: Dashboard[]
    selectedId: string | null
    isCollapsed: boolean
    setIsCollapsed: (isCollapsed: boolean) => void
    onSelect: (id: string) => void
    onRename: (id: string, newTitle: string) => void
    onDefault: (id: string) => void
    onShare: (id: string) => void
}

export function DashboardSidebar({
    dashboards,
    selectedId,
    isCollapsed,
    setIsCollapsed,
    onSelect,
    onRename,
    onDefault,
    onShare
}: DashboardSidebarProps) {
    const { t } = useTranslation("dashboard")

    const [searchQuery, setSearchQuery] = useState("")
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
        onError: (msg: string) => {
            toast({
                description: msg,
                variant: "error",
            })
        },
    })
    const handleCreate = () => {
        if (dashboards.length >= 20) {
            toast({
                description: t('maxLimitReached', { count: 20 }),
                variant: "error",
            })
            return
        }

        createMutation.mutate(generateUniqueName(dashboards, 'title', t('untitledDashboard'), '(x)'))
    }


    const duplicateMutation = useMutation({
        mutationFn: copyDashboard,
        onSuccess: (newDashboard) => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            onSelect(newDashboard.id)
            // jump to new dashboard
            navigator(`/dashboard/${newDashboard.id}`)
        },
        onError: () => {
            toast({
                description: t('copyFailed'),
                variant: "error",
            })
        },
    })
    const handleDuplicate = (dashboard: Dashboard) => {
        if (dashboards.length >= 20) {
            toast({
                description: t('maxLimitReached', { count: 20 }),
                variant: "error",
            })
            return
        }

        const newTitle = generateUniqueName(dashboards, 'title', t('dashboardCopyName', { title: dashboard.title }), '(x)')
        if (newTitle.length > 200) {
            return toast({
                description: t('charLimit200b'),
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
                description: "delete error",
                variant: "error",
            })
        },
    })
    const handleDelete = (id: string) => {
        const dashboard = dashboards.find((d) => d.id === id)
        if (!dashboard) return

        bsConfirm({
            desc: t('confirmDeleteDashboard', { title: dashboard.title }),
            okTxt: t('delete'),
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
                isCollapsed ? "w-0" : "w-44 border-r",
            )}
        >
            {
                !isCollapsed && <div className="header relative flex items-center justify-between h-[52px] px-2 pr-11 border-b">
                    <p className="text-base font-bold">{t('dashboardList')}</p>
                    {
                        canCreate && <Tip content={t('addDashboard')} >
                            <Button variant="ghost" size="icon" onClick={handleCreate}><SquarePlusIcon size={16} /></Button>
                        </Tip>
                    }
                </div>
            }
            <Tip content={t('collapseList')}>
                {
                    !isCollapsed && <Button
                        variant="ghost"
                        size="icon"
                        className={"absolute top-2 z-10 hover:text-primary bg-background right-2"}
                        onClick={() => setIsCollapsed(!isCollapsed)}
                    >
                        <ExpandIcon className="h-4 w-4 rotate-180" />
                    </Button>
                }
            </Tip>


            {!isCollapsed && (
                <div className="flex flex-col p-2 gap-2">
                    <div className="relative">
                        <SearchInput
                            placeholder={t('system.boardName', { ns: 'bs' })}
                            value={searchQuery}
                            onChange={handleSearch}
                            onKeyDown={handleKeyDown}
                        />
                    </div>

                    <div className="overflow-y-auto space-y-2 h-[calc(100vh-174px)]">
                        {filteredDashboards.length === 0 ? (
                            <div className="text-center text-muted-foreground text-sm py-8">
                                {searchQuery ? t('noMatchingDashboards') : t('noDashboards')}
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
