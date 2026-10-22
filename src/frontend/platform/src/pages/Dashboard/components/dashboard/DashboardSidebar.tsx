// @ts-strict-ignore
import { Button, SearchInput, notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";



import { userContext } from "@/contexts/userContext";
import { copyDashboard,createDashboard,deleteDashboard } from "@/controllers/API/dashboard";
import { useMiniDebounce } from "@/util/hook";
import { generateUniqueName } from "@/util/utils";
import { cn } from "@/utils";
import { Tooltip as Tip } from "@bisheng/ui";

import type React from "react";
import { useContext,useMemo,useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation,useQueryClient } from "react-query";
import { useNavigate } from "react-router-dom";
import { DashboardsQueryKey } from "../../hook";
import { Dashboard } from "../../types/dataConfig";
import { DashboardListItem } from "./DashboardListItem";

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
    // Permission management state
    const [permDialogOpen, setPermDialogOpen] = useState(false);
    const [permTarget, setPermTarget] = useState<{ id: string; name: string } | null>(null);
    const canCreate = useMemo(() => {
        return user.web_menu?.includes('create_dashboard') || user.role === 'admin'
    }, [user])

    // Visibility is already decided by the server list; the sidebar only narrows
    // it by the search box. Per-row edit/delete/manage permissions are resolved
    // lazily inside each item the moment the user reaches for them.
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

    const queryClient = useQueryClient()
    const createMutation = useMutation({
        mutationFn: createDashboard,
        onSuccess: (res) => {
            onSelect(res.id)
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] })
            navigator(`/dashboard/${res.id}`)
        },
        onError: (msg: string) => {
            notification.open({ type: "error", description: String(msg ?? '') })
        },
    })
    const handleCreate = () => {
        if (dashboards.length >= 20) {
            notification.open({ type: "error", description: String(t('maxLimitReached', { count: 20 }) ?? '') })
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
            notification.open({ type: "error", description: String(t('copyFailed') ?? '') })
        },
    })
    const handleDuplicate = (dashboard: Dashboard) => {
        if (dashboards.length >= 20) {
            notification.open({ type: "error", description: String(t('maxLimitReached', { count: 20 }) ?? '') })
            return
        }

        const newTitle = generateUniqueName(dashboards, 'title', t('dashboardCopyName', { title: dashboard.title }), '(x)')
        if (newTitle.length > 200) {
            return notification.open({ type: "error", description: String(t('charLimit200b') ?? '') })
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
            notification.open({ type: "error", description: String("delete error") })
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
                // Both header buttons share this row: centring them in the same
                // 52px flex line is what keeps them aligned — the collapse
                // button used to be absolutely positioned at top-2, which left
                // it 2px above the 32px add button.
                //
                // The condition also has to sit outside Tip: it reads
                // children.props, so a falsy child crashes the whole page.
                !isCollapsed && <div className="header flex items-center justify-between h-[52px] px-2 border-b">
                    <p className="text-base font-bold">{t('dashboardList')}</p>
                    <div className="flex items-center gap-1">
                        {
                            canCreate && <Tip content={t('addDashboard')} >
                                <Button variant="text" size="medium" onClick={handleCreate} color="default" iconOnly><Outlined.Plus size={16} /></Button>
                            </Tip>
                        }
                        <Tip content={t('collapseList')}>
                            <Button variant="text" size="medium" className="hover:text-primary" onClick={() => setIsCollapsed(!isCollapsed)} color="default" iconOnly>
                                <Outlined.Left className="h-4 w-4" />
                            </Button>
                        </Tip>
                    </div>
                </div>
            }


            {!isCollapsed && (
                <div className="flex flex-col p-2 gap-2">
                    <div className="relative">
                        <SearchInput placeholder={t('system.boardName', { ns: 'bs' })} value={searchQuery} onChange={handleSearch} onKeyDown={handleKeyDown} />
                    </div>

                    <div className="overflow-y-auto space-y-2 h-[calc(100vh-174px-var(--license-banner-h,0px))]">
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
                                    onPermission={(d) => { setPermTarget({ id: String(d.id), name: d.title }); setPermDialogOpen(true); }}
                                />
                            ))
                        )}
                    </div>
                </div>
            )}
        {/* Permission management dialog */}
        {permTarget && (
            <PermissionDialog
                open={permDialogOpen}
                onOpenChange={setPermDialogOpen}
                resourceType="dashboard"
                resourceId={permTarget.id}
                resourceName={permTarget.name}
            />
        )}
        </div>
    )
}
