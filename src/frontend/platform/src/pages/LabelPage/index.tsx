import UsersSelect from "@/components/bs-comp/selectComponent/Users";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { TableHeadEnumFilter } from "@/components/bs-ui/select/filter";
import MultiSelect from "@/components/bs-ui/select/multi";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { getChatOnlineApi } from "@/controllers/API/assistant";
import { createMarkApi, deleteMarkApi, getMarksApi } from "@/controllers/API/log";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

// apps
const useAppsOptions = () => {
    const [options, setOptions] = useState([])
    const optionsRef = useRef([])
    const pageRef = useRef(1)
    const keywordRef = useRef("")
    // 未标注数map
    const unmarkedMap = useRef({})
    const loadApps = () => {
        const page = pageRef.current
        getChatOnlineApi(page, keywordRef.current, -1).then((res: any) => {
            const newOptions = res.map(el => {
                unmarkedMap.current[el.id] = el.count
                return {
                    label: el.name,
                    value: el.id,
                    count: el.count
                }
            })
            optionsRef.current = page === 1 ? newOptions : [...optionsRef.current, ...newOptions]
            setOptions(optionsRef.current)
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
            pageRef.current = 1
            loadApps()
        },
        loadMore: () => {
            pageRef.current++
            loadApps()
        },
        search: (keyword) => {
            pageRef.current = 1
            keywordRef.current = keyword
            loadApps()
        }
    }
}

function CreateModal({ open, setOpen, onSuccess }) {
    const { t } = useTranslation()

    const { options, unmarkedMap, reload, loadMore, search } = useAppsOptions()
    const [apps, setApps] = useState([])
    const [users, setUsers] = useState([])

    const count = useMemo(() => {
        return apps.reduce((pre, cur) => pre + unmarkedMap[cur.value], 0)
    }, [apps, unmarkedMap])

    const { message } = useToast()
    const handleCreate = () => {
        if (apps.length > 30) {
            return message({
                variant: "error",
                description: t('label.maxAppsError')
            })
        }
        captureAndAlertRequestErrorHoc(createMarkApi({
            app_list: apps.map(el => el.value),
            user_list: users.map(el => el.value)
        }).then(res => {
            if (!res) return
            message({
                variant: "success",
                description: t('label.createSuccess')
            })
            setOpen(false)
            onSuccess()
        }))
    }

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('label.createTask')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('label.selectAppsToLabel')}</label>
                    <MultiSelect
                        contentClassName=" max-w-[630px]"
                        multiple
                        value={apps}
                        options={options}
                        placeholder={t('label.selectPlaceholder')}
                        searchPlaceholder={t('label.searchAppsPlaceholder')}
                        onChange={setApps}
                        onLoad={reload}
                        onSearch={search}
                        onScrollLoad={loadMore}
                    ></MultiSelect>
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
                <DialogClose>
                    <Button
                        variant="outline"
                        className="px-11"
                        type="button"
                        onClick={() => setOpen(false)}
                    >{t('label.cancel')}</Button>
                </DialogClose>
                <Button
                    type="submit"
                    className="px-11"
                    disabled={apps.length === 0 || users.length === 0}
                    onClick={handleCreate}
                >{t('label.create')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

export default function Tasks() {
    const { t } = useTranslation()
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

    // 系统管理员(超管、组超管)
    const isAdmin = useMemo(() => {
        console.log('user', user);
        
        return user.role?.includes('admin')
    }, [user])
    
    // 拥有权限管理权限
    const hasGroupAdminRole = useMemo(() => {
        return user.role?.includes('group_admin')
    }, [user])

    return (
        <div className="relative px-2 pt-4 h-full">
            <div className="h-full overflow-y-auto pb-20">
                <div className="flex justify-end gap-6">
                    {(isAdmin || hasGroupAdminRole) && <Button onClick={() => setOpen(true)}>
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
                                    <TableHeadEnumFilter options={[
                                        { label: t('label.all'), value: '0' },
                                        { label: t('label.notStarted'), value: '1' },
                                        { label: t('label.completed'), value: '2' },
                                        { label: t('label.inProgress'), value: '3' },
                                    ]}
                                        onChange={(v) => filterData({ status: Number(v) })} />
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
                                    (task.mark_process || []).map(name => <p>{name}</p>)
                                }</TableCell>
                                <TableCell className="text-right">
                                    <Link to={`/label/${task.id}`}><Button variant="link" className="px-0 pl-4" >{t('label.view')}</Button></Link>
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
                <AutoPagination
                    className="float-right justify-end w-full mr-6"
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
            {open && <CreateModal open={open} setOpen={setOpen} onSuccess={reload}></CreateModal>}
        </div>
    );
}