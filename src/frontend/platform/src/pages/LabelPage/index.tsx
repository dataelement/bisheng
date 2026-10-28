// @ts-strict-ignore
import { Outlined } from "bisheng-icons";
import { Pagination, Button, Select, toast } from '@bisheng/ui';
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import UsersSelect from "@/components/bs-comp/selectComponent/Users";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";

import { userContext } from "@/contexts/userContext";
import { getChatOnlineApi } from "@/controllers/API/assistant";
import { createMarkApi, deleteMarkApi, getMarksApi } from "@/controllers/API/log";
import { showApiError } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

// apps
const useAppsOptions = () => {
    const [options, setOptions] = useState([])
    const optionsRef = useRef([])
    const cursorRef = useRef<string | null>(null)
    const keywordRef = useRef("")
    // 未标注数map
    const unmarkedMap = useRef({})
    const loadApps = (append = false) => {
        getChatOnlineApi(append ? cursorRef.current : null, keywordRef.current, -1).then((res: any) => {
            const list = res.list || []
            const newOptions = list.map(el => {
                unmarkedMap.current[el.id] = el.count
                return {
                    label: el.name,
                    value: el.id,
                    count: el.count
                }
            })
            optionsRef.current = append ? [...optionsRef.current, ...newOptions] : newOptions
            setOptions(optionsRef.current)
            cursorRef.current = res.nextCursor
        })
    }
    useEffect(() => {
        loadApps()
    }, [])

    return {
        options,
        unmarkedMap: unmarkedMap.current,
        reload: () => {
            keywordRef.current = ''
            cursorRef.current = null
            loadApps()
        },
        loadMore: () => {
            loadApps(true)
        },
        search: (keyword) => {
            cursorRef.current = null
            keywordRef.current = keyword
            loadApps()
        }
    }
}

function CreateModal({ open, setOpen, onSuccess }) {
    const { t } = useTranslation()

    const selectLabels = useSelectLabels()
    const { options, unmarkedMap, reload, loadMore, search } = useAppsOptions()
    const [apps, setApps] = useState([])
    const [users, setUsers] = useState([])

    // Keep the selected apps' labels known even when the current page/search result lacks them
    const appOptions = useMemo(() => {
        const merged = [...options]
        apps.forEach(app => {
            if (!merged.some(o => o.value === app.value)) merged.push(app)
        })
        return merged
            .filter(o => o.value != null && o.value !== '')
            .map(o => ({ value: o.value, label: o.label }))
    }, [options, apps])

    const count = useMemo(() => {
        return apps.reduce((pre, cur) => pre + unmarkedMap[cur.value], 0)
    }, [apps, unmarkedMap])


    const handleCreate = () => {
        if (apps.length > 30) {
            return toast.show({ type: "error", message: String(t('label.maxAppsError') ?? '') })
        }
        createMarkApi({
            app_list: apps.map(el => el.value),
            user_list: users.map(el => el.value)
        }).then(res => {
            if (!res) return
            toast.show({ type: "success", message: String(t('label.createSuccess') ?? '') })
            setOpen(false)
            onSuccess()
        }).catch(showApiError)
    }

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('label.createTask')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('label.selectAppsToLabel')}</label>
                    <Select
                        {...selectLabels}
                        multiple
                        showSearch
                        aria-label={t('label.selectAppsToLabel')}
                        value={apps.map(app => app.value)}
                        options={appOptions}
                        placeholder={t('label.selectPlaceholder')}
                        onChange={(_values, selectedOptions) => setApps(selectedOptions.map(o => ({ label: o.label, value: o.value })))}
                        onOpenChange={(isOpen) => { if (isOpen) reload() }}
                        onSearch={search}
                        onLoadMore={loadMore}
                    />
                </div>
                {count ? <p className="text-sm text-gray-500">{t('label.unmarkedConversationCount')}: {count}</p> : null}
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('label.selectLabelers')}</label>
                    <UsersSelect
                        multiple
                        value={users}
                        onChange={setUsers}
                    />
                </div>
            </div>
            <DialogFooter>
                <DialogClose asChild>
                    <Button variant="outlined" type="button" onClick={() => setOpen(false)} color="default">{t('label.cancel')}</Button>
                </DialogClose>
                <Button type="submit" disabled={apps.length === 0 || users.length === 0} onClick={handleCreate}>{t('label.create')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

const TASK_STATUS_OPTIONS = [
    { labelKey: 'label.all', value: '0' },
    { labelKey: 'label.notStarted', value: '1' },
    { labelKey: 'label.completed', value: '2' },
    { labelKey: 'label.inProgress', value: '3' },
]

export default function Tasks() {
    const { t } = useTranslation()
    const paginationLocale = usePaginationLocale();
    const selectLabels = useSelectLabels()
    const [statusFilter, setStatusFilter] = useState<string | null>(null)
    const statusOptions = TASK_STATUS_OPTIONS.map(o => ({ value: o.value, label: t(o.labelKey) }))
    const statusFilterLabel = statusOptions.find(o => o.value === statusFilter)?.label ?? t('label.all')
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);

    const { page, pageSize, data: tasks, total, setPage, search, reload, filterData } = useTable({ pageSize: 20 }, (param) =>
        getMarksApi({
            ...param
        })
    )

    const handleDelete = (taskId) => {
        bsConfirm({
            title: t('label.confirmDelete'),
            desc: t('label.deleteConfirmation'),
            okTxt: t('label.delete'),
            onOk: async (next) => {
                await deleteMarkApi(taskId);
                reload();
                next();
            }
        });
    };

    return (
        <div className="relative px-2 pt-4 h-full">
            <div className="h-full overflow-y-auto pb-20">
                <div className="flex justify-end gap-6">
                    {user.role === 'admin' && <Button onClick={() => setOpen(true)}>
                        {t('label.createTask')}
                    </Button>}
                </div>
                <Table className="mb-[50px]">
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('label.taskId')}</TableHead>
                            <TableHead>
                                <div className="flex items-center w-[144px]">
                                    {t('label.taskStatus')}
                                    <Select
                                        {...selectLabels}
                                        options={statusOptions}
                                        value={statusFilter}
                                        onChange={(v) => {
                                            if (v == null) return
                                            setStatusFilter(String(v))
                                            filterData({ status: Number(v) })
                                        }}
                                        trigger={
                                            <button type="button" className="outline-none" aria-label={`${t('label.taskStatus')}: ${statusFilterLabel}`}>
                                                <Outlined.Filter size={16} aria-hidden className={statusFilter ? 'text-primary ml-3' : 'text-gray-400 ml-3'} />
                                            </button>
                                        }
                                    />
                                </div>
                            </TableHead>
                            <TableHead>{t('label.creationTime')}</TableHead>
                            <TableHead>{t('label.createdBy')}</TableHead>
                            <TableHead className="w-[144px]">{t('label.labelingProgress')}</TableHead>
                            <TableHead className="text-right w-[164px]">{t('label.actions')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {tasks.map((task) => (
                            <TableRow key={task.id}>
                                <TableCell>{task.id}</TableCell>
                                <TableCell>{['', t('label.notStarted'), t('label.completed'), t('label.inProgress')][task.status]}</TableCell>
                                <TableCell>{task.create_time.replace('T', ' ')}</TableCell>
                                <TableCell>{task.create_user}</TableCell>
                                <TableCell className="break-all">{
                                    (task.mark_process || []).map((name, index) => <p key={index}>{name}</p>)
                                }</TableCell>
                                <TableCell className="text-right">
                                    <Button asChild size="small" variant="link"><Link to={`/label/${task.id}`}>{t('label.view')}</Link></Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                    <TableFooter>
                        {!tasks.length && (
                            <TableRow>
                                <TableCell colSpan={6} className="text-center text-gray-400">{t('label.noData')}</TableCell>
                            </TableRow>
                        )}
                    </TableFooter>
                </Table>
            </div>
            <div className="bisheng-table-footer bg-background-login px-2">
                <Pagination locale={paginationLocale}
                    className="float-right justify-end w-full mr-6"
                    current={page}
                    pageSize={pageSize}
                    total={total}
                    showTotal={true}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
            {open && <CreateModal open={open} setOpen={setOpen} onSuccess={reload}></CreateModal>}
        </div>
    );
}
