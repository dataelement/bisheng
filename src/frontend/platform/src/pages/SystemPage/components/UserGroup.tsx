import { useTranslation } from "react-i18next"
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "../../../components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import { PlusIcon } from "@/components/bs-icons/plus";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { deleteUserGroupV2, listUserGroupsV2, UserGroupV2 } from "@/controllers/API/userGroups";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { message } from "@/components/bs-ui/toast/use-toast";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import {
    Table,
    TableBody,
    TableCell,
    TableFooter,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import {
    ColumnResizeHandle,
    useResizableColumns,
    type ResizableColumnDef,
} from "@/components/bs-ui/table/useResizableColumns";
import { cname } from "@/components/bs-ui/utils";
import EditUserGroup from "./EditUserGroup";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";

export default function UserGroups() {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const [userGroups, setUserGroups] = useState<UserGroupV2[]>([])
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(1)
    const [keyword, setKeyword] = useState("")
    const [loading, setLoading] = useState(false)
    const [userGroup, setUserGroup] = useState<UserGroupV2 | Record<string, never> | null>(null)
    const tempRef = useRef<UserGroupV2[]>([])
    const { appConfig } = useContext(locationContext)

    const HIDDEN_GROUP_NAMES = new Set(['Default user group', '默认用户组'])
    const PAGE_SIZE = 20

    const loadData = async (nextPage = page, nextKeyword = keyword) => {
        setLoading(true)
        try {
            const res = await listUserGroupsV2({
                page: nextPage,
                limit: PAGE_SIZE,
                keyword: nextKeyword || undefined,
            })
            const records = (res?.data ?? []).filter((ug) => !HIDDEN_GROUP_NAMES.has(ug.group_name))
            setUserGroups(records)
            tempRef.current = records
            setTotal(res?.total ?? records.length)
            setPage(nextPage)
        } finally {
            setLoading(false)
        }
    }

    const handleSearch = (e) => {
        const word = e.target.value
        setKeyword(word)
        loadData(1, word).catch(() => {
            setUserGroups([])
            tempRef.current = []
            setTotal(0)
        })
    }
    const handleDelete = (ug: UserGroupV2) => {
        bsConfirm({
            title: t("prompt"),
            desc: t('system.deleteGroup', { name: ug.group_name }),
            okTxt: t('delete'),
            onOk: async (next) => {
                try {
                    const res = await captureAndAlertRequestErrorHoc(
                        deleteUserGroupV2(ug.id).then(() => loadData()),
                    )
                    if (res === false) return
                    message({ variant: "success", description: t("deleteSuccess") })
                } finally {
                    next()
                }
            },
        })
    }

    const canDeleteGroup = (ug: UserGroupV2) => {
        if (user?.role === "admin") return true
        const isTenantScopedAdmin = user?.is_department_admin || user?.is_child_admin
        if (isTenantScopedAdmin && ug.create_user === user?.user_id) return true
        return false
    }

    const checkSameName = (name: string) => {
        return (userGroups.find(ug =>
            ug.group_name === name && ug.id !== (userGroup as UserGroupV2)?.id))
    }
    const handleChange = async (flag: boolean) => {
        if (flag) {
            try {
                await loadData()
            } catch {
                setUserGroups([])
                tempRef.current = []
                setTotal(0)
            }
        }
        setUserGroup(null)
    }

    useEffect(() => {
        loadData().catch(() => {
            setUserGroups([])
            tempRef.current = []
            setTotal(0)
        })
    }, [])

    const groupTableCols = useMemo((): ResizableColumnDef[] => {
        const c: ResizableColumnDef[] = [
            { defaultWidth: 200, minWidth: 140 },
            { defaultWidth: 220, minWidth: 120 },
        ]
        if (appConfig.isPro) c.push({ defaultWidth: 150, minWidth: 100 })
        c.push(
            { defaultWidth: 120, minWidth: 88 },
            { defaultWidth: 160, minWidth: 130 },
            { defaultWidth: 150, minWidth: 110 },
        )
        return c
    }, [appConfig.isPro])
    const ugRc = useResizableColumns(groupTableCols)
    const ugLast = groupTableCols.length - 1

    if (userGroup !== null) return <EditUserGroup
        key={(userGroup as UserGroupV2).id ?? 'new'}
        data={userGroup}
        onBeforeChange={checkSameName}
        onChange={handleChange}
    />

    const displayCreator = (ug: UserGroupV2) => {
        const name = ug.create_user_name?.trim()
        if (name) return name
        const fromList = ug.group_admins?.map((a) => a.user_name).filter(Boolean).join(", ")
        if (fromList) return fromList
        return ug.create_user != null ? String(ug.create_user) : "—"
    }

    return <div className="relative">
        <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10">
            <div className="flex gap-6 items-center justify-end">
                <div className="w-[180px] relative">
                    <SearchInput placeholder={t('system.groupName')} onChange={handleSearch}></SearchInput>
                </div>
                <Button className="flex justify-around" disabled={loading} onClick={() => setUserGroup({})}>
                    <PlusIcon className="text-primary" />
                    <span className="text-[#fff] mx-4">{t('create')}</span>
                </Button>
            </div>
            <div className="relative min-h-[240px]">
                <Table
                    noScroll
                    className="mb-10 !w-auto min-w-full"
                    style={{ tableLayout: "fixed", width: ugRc.totalWidth }}
                >
                    <TableHeader>
                        <TableRow>
                            <TableHead {...ugRc.getThProps(0)}>
                                {t('system.groupName')}
                                <ColumnResizeHandle columnIndex={0} lastColumn={0 === ugLast} startResize={ugRc.startResize} />
                            </TableHead>
                            <TableHead {...ugRc.getThProps(1)}>
                                {t('system.groupCreator')}
                                <ColumnResizeHandle columnIndex={1} lastColumn={1 === ugLast} startResize={ugRc.startResize} />
                            </TableHead>
                            {appConfig.isPro && (
                                <TableHead {...ugRc.getThProps(2)}>
                                    {t('system.flowControl')}
                                    <ColumnResizeHandle columnIndex={2} lastColumn={2 === ugLast} startResize={ugRc.startResize} />
                                </TableHead>
                            )}
                            <TableHead {...ugRc.getThProps(appConfig.isPro ? 3 : 2)}>
                                {t('system.groupVisibility')}
                                <ColumnResizeHandle
                                    columnIndex={appConfig.isPro ? 3 : 2}
                                    lastColumn={(appConfig.isPro ? 3 : 2) === ugLast}
                                    startResize={ugRc.startResize}
                                />
                            </TableHead>
                            <TableHead {...ugRc.getThProps(appConfig.isPro ? 4 : 3)}>
                                {t('system.changeTime')}
                                <ColumnResizeHandle
                                    columnIndex={appConfig.isPro ? 4 : 3}
                                    lastColumn={(appConfig.isPro ? 4 : 3) === ugLast}
                                    startResize={ugRc.startResize}
                                />
                            </TableHead>
                            <TableHead
                                style={ugRc.getThProps(appConfig.isPro ? 5 : 4).style}
                                className={cname(ugRc.getThProps(appConfig.isPro ? 5 : 4).className, "text-right")}
                            >
                                {t('operations')}
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {userGroups.map((ug) => (
                            <TableRow key={ug.id}>
                                <TableCell {...ugRc.getTdProps(0)} className="font-medium">{ug.group_name}</TableCell>
                                <TableCell {...ugRc.getTdProps(1)} className="break-all">{displayCreator(ug)}</TableCell>
                                {appConfig.isPro && (
                                    <TableCell {...ugRc.getTdProps(2)}>
                                        {(ug as any).group_limit ? t('system.limit') : t('system.unlimited')}
                                    </TableCell>
                                )}
                                <TableCell {...ugRc.getTdProps(appConfig.isPro ? 3 : 2)}>
                                    <Badge variant={ug.visibility === 'private' ? 'secondary' : 'outline'}>
                                        {ug.visibility === 'private' ? t('system.visibilityPrivate') : t('system.visibilityPublic')}
                                    </Badge>
                                </TableCell>
                                <TableCell {...ugRc.getTdProps(appConfig.isPro ? 4 : 3)}>
                                    {(ug.update_time || "").replace("T", " ")}
                                </TableCell>
                                <TableCell
                                    {...ugRc.getTdProps(appConfig.isPro ? 5 : 4)}
                                    className="whitespace-nowrap text-right"
                                >
                                    <Button variant="link" disabled={loading} onClick={() => setUserGroup({ ...ug })}
                                        className="px-0 pl-6">{t('edit')}
                                    </Button>
                                    <Button variant="link" disabled={loading || !canDeleteGroup(ug)} onClick={() => handleDelete(ug)} className="text-red-500 px-0 pl-6">{t('delete')}</Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                    <TableFooter>
                        {!loading && !userGroups.length && <TableRow>
                            <TableCell colSpan={appConfig.isPro ? 6 : 5} className="text-center text-gray-400">{t('build.empty')}</TableCell>
                        </TableRow>}
                    </TableFooter>
                </Table>
                {loading && (
                    <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/60 dark:bg-blur-shared">
                        <div className="flex items-center gap-2 rounded-md bg-background px-4 py-2 text-sm text-muted-foreground shadow-sm">
                            <LoadingIcon className="size-5" />
                            <span>{t('loading', { ns: 'bs' })}</span>
                        </div>
                    </div>
                )}
            </div>
        </div>
        <div className="bisheng-table-footer px-6 bg-background-login">
            <div className="flex items-center gap-2">
                <p className="desc">{t('system.userGroupList')}.</p>
                <span className="text-sm text-[#86909c]">{t('pagination.totalRecords', { ns: 'bs', total })}</span>
            </div>
            <AutoPagination
                className={cname("m-0 w-auto justify-end", loading && "pointer-events-none opacity-60")}
                page={page}
                pageSize={PAGE_SIZE}
                total={total}
                onChange={(nextPage) => {
                    if (loading) return
                    loadData(nextPage).catch(() => {
                        setUserGroups([])
                        tempRef.current = []
                        setTotal(0)
                    })
                }}
            />
        </div>
    </div>
}
