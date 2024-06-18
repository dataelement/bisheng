import { Button } from "@/components/bs-ui/button";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getActionsApi, getActionsByModuleApi, getLogsApi, getModulesApi } from "@/controllers/API/log";
import { getUserGroupsApi, getUsersApi } from "@/controllers/API/user";
import { useTable } from "@/util/hook";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";

const useGroups = () => {
    const [groups, setGroups] = useState([])
    const loadData = () => {
        getUserGroupsApi().then(res => setGroups(res.records))
    }
    return { groups, loadData }
}
const useModules = () => {
    const [modules, setModules] = useState([])
    const loadModules = () => {
        getModulesApi().then(res => setModules(res.data))
    }
    return { modules, loadModules }
}

export default function index() {
    const { t } = useTranslation()
    const { users, reload, loadMore, searchUser } = useUsers()
    const { groups, loadData } = useGroups()
    const { modules, loadModules } = useModules()
    const { page, pageSize, data: logs, total, setPage, filterData } = useTable({ pageSize: 20 }, (param) =>
        getLogsApi({...param})
    )

    const [actions, setActions] = useState([])
    const [keys, setKeys] = useState({
        userIds: [],
        groupId: undefined,
        start: undefined,
        end: undefined,
        moduleId: undefined,
        actionId: undefined
    })

    const handleActionOpen = () => {
        keys.moduleId ? getActionsByModuleApi(keys.moduleId).then(res => setActions(res.data))
        : getActionsApi().then(res => setActions(res.data))
    }
    const handleSearch = () => {
        console.log(keys)
        filterData(keys)
    }
    const handleReset = () => {
        setKeys({
            userIds: [],
            groupId: undefined,
            start: undefined,
            end: undefined,
            moduleId: undefined,
            actionId: undefined
        })
    }

    return <div className="relative">
        <div className="h-[calc(100vh-98px)] overflow-y-auto px-2 py-4 pb-10">
            <div className="flex flex-wrap gap-4">
                <div className="w-[180px] relative">
                    <MultiSelect className=" w-full" multiple
                        options={users}
                        value={keys.userIds}
                        placeholder="选择用户"
                        onLoad={reload}
                        onSearch={searchUser}
                        onScrollLoad={loadMore}
                        onChange={(values) => setKeys({...keys,userIds:values})}
                    ></MultiSelect>
                </div>
                <div className="w-[180px] relative">
                    <Select onOpenChange={loadData} value={keys.groupId} onValueChange={(value) => setKeys({...keys,groupId:value})}>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="选择用户组" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {groups.map(g => <SelectItem value={g.id} key={g.id}>{g.group_name}</SelectItem>)}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <div className="w-[180px] relative">
                    <DatePicker value={keys.start} placeholder='开始日期' onChange={(t) => setKeys({...keys,start:t})} />
                </div>
                <div className="w-[180px] relative">
                    <DatePicker value={keys.end} placeholder='结束日期' onChange={(t) => setKeys({...keys,end:t})} />
                </div>
                <div className="w-[180px] relative">
                    <Select value={keys.moduleId} onOpenChange={loadModules} onValueChange={(value) => setKeys({...keys,moduleId:value})}>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="系统模块" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="apple">Apple</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <div className="w-[180px] relative">
                    <Select value={keys.actionId} onOpenChange={handleActionOpen} onValueChange={(value) => setKeys({...keys,actionId:value})}>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="操作行为" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="apple">Apple</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <div>
                    <Button className=" mr-3 px-6" onClick={handleSearch}>查询</Button>
                    <Button variant="outline" className="px-6" onClick={handleReset}>重置</Button>
                </div>
            </div>
            <Table className="mb-[50px]">
                {/* <TableCaption>用户列表.</TableCaption> */}
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">审计ID</TableHead>
                        <TableHead className="w-[200px]">用户名</TableHead>
                        <TableHead className="w-[200px]">操作时间</TableHead>
                        <TableHead className="w-[200px]">系统模块</TableHead>
                        <TableHead className="w-[200px]">操作行为</TableHead>
                        <TableHead className="w-[200px]">操作对象类型</TableHead>
                        <TableHead className="w-[200px]">操作对象</TableHead>
                        <TableHead className="w-[200px]">IP地址</TableHead>
                        <TableHead className="w-[200px]">备注</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className="font-medium max-w-md truncate">34</TableCell>
                        <TableHead>赵光晶</TableHead>
                        <TableHead>2024-06-18-15:59</TableHead>
                        <TableHead>构建</TableHead>
                        <TableHead>创建应用</TableHead>
                        <TableHead>助手</TableHead>
                        <TableHead>代码助手</TableHead>
                        <TableHead>122.9.35.239</TableHead>
                        <TableHead>创建了一个很牛的代码助手</TableHead>
                    </TableRow>
                </TableBody>
            </Table>
        </div>
        {/* 分页 */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="bisheng-table-footer">
            <p className="desc pl-4">审计管理</p>
            <AutoPagination
                className="float-right justify-end w-full mr-6"
                page={page}
                pageSize={pageSize}
                total={total}
                onChange={(newPage) => setPage(newPage)}
            />
        </div>
    </div>
};


const useUsers = () => {
    const pageRef = useRef(1)
    const [users, setUsers] = useState<any[]>([]);

    const reload = (page, name) => {
        getUsersApi({ name, page, pageSize: 60 }).then(res => {
            pageRef.current = page
            const opts = res.data.map(el => ({ label: el.user_name, value: el.user_id }))
            setUsers(_ops => page > 1 ? [..._ops, ...opts] : opts)
        })
    }

    // 加载更多
    const loadMore = (name) => {
        reload(pageRef.current + 1, name)
    }

    return {
        users,
        loadMore,
        reload() {
            reload(1, '')
        },
        searchUser(name) {
            reload(1, name)
        }
    }
}