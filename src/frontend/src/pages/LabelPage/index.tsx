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
import { getUsersApi } from "@/controllers/API/user";
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
        captureAndAlertRequestErrorHoc(createMarkApi({
            app_list: apps.map(el => el.value),
            user_list: users.map(el => el.value)
        }).then(res => {
            if (!res) return
            message({
                variant: "success",
                description: "创建成功"
            })
            setOpen(false)
            onSuccess()
        }))
    }

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>创建标注任务</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                <div className="">
                    <label htmlFor="name" className="bisheng-label">选择要标注的应用</label>
                    <MultiSelect
                        contentClassName=" max-w-[630px]"
                        multiple
                        value={apps}
                        options={options}
                        placeholder="请选择"
                        searchPlaceholder="搜索应用名称"
                        onChange={setApps}
                        onLoad={reload}
                        onSearch={search}
                        onScrollLoad={loadMore}
                    ></MultiSelect>
                </div>
                {count ? <p className="text-sm text-gray-500">当前未标注会话数：{count}</p> : null}
                <div className="">
                    <label htmlFor="name" className="bisheng-label">标注人</label>
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
                    >{t('cancel')}</Button>
                </DialogClose>
                <Button
                    type="submit"
                    className="px-11"
                    disabled={apps.length === 0 || users.length === 0}
                    onClick={handleCreate}
                >{t('create')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

export default function Tasks() {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);

    // 获取任务数据
    const { page, pageSize, data: tasks, total, setPage, search, reload, filterData } = useTable({ pageSize: 20 }, (param) =>
        getMarksApi({
            ...param
        })
    )

    // 删除任务
    const handleDelete = (taskId) => {
        bsConfirm({
            title: "确认删除",
            desc: "您确定要删除此任务吗？",
            okTxt: "删除",
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
                    {['admin', 'group_admin'].includes(user.role) && <Button onClick={() => setOpen(true)}>
                        创建标注任务
                    </Button>}
                </div>
                <Table className="mb-[50px]">
                    <TableHeader>
                        <TableRow>
                            <TableHead>任务 ID</TableHead>
                            <TableHead>
                                <div className="flex items-center w-[144px]">
                                    任务状态
                                    <TableHeadEnumFilter options={[
                                        { label: '全部', value: '0' },
                                        { label: '未开始', value: '1' },
                                        { label: '已完成', value: '2' },
                                        { label: '进行中', value: '3' },
                                    ]}
                                        onChange={(v) => filterData({ status: Number(v) })} />
                                </div>
                            </TableHead>
                            <TableHead>创建时间</TableHead>
                            <TableHead>创建人</TableHead>
                            <TableHead className="w-[144px]">标注进度</TableHead>
                            <TableHead className="text-right w-[164px]">操作</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {tasks.map((task) => (
                            <TableRow key={task.id}>
                                <TableCell>{task.id}</TableCell>
                                <TableCell>{['', '未开始', '已完成', '进行中'][task.status]}</TableCell>
                                <TableCell>{task.create_time.replace('T', ' ')}</TableCell>
                                <TableCell>{task.create_user}</TableCell>
                                <TableCell className="break-all">{
                                    (task.mark_process || []).map(name => <p>{name}</p>)
                                }</TableCell>
                                <TableCell className="text-right">
                                    <Link to={`/label/${task.id}`}><Button variant="link" className="px-0 pl-4" >查看</Button></Link>
                                    {/* <Button variant="link" onClick={() => handleDelete(task.id)} className="text-red-500 px-0 pl-4">删除</Button> */}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                    <TableFooter>
                        {!tasks.length && (
                            <TableRow>
                                <TableCell colSpan={6} className="text-center text-gray-400">暂无数据</TableCell>
                            </TableRow>
                        )}
                    </TableFooter>
                </Table>
            </div>
            <div className="bisheng-table-footer bg-background-login px-2">
                {/* <p className="desc">xxxx</p> */}
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
