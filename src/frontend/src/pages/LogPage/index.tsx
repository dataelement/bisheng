import { Button } from "@/components/bs-ui/button";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getActionsApi, getActionsByModuleApi, getLogsApi, getModulesApi, getOperatorsApi } from "@/controllers/API/log";
import { getUserGroupsApi, getUsersApi } from "@/controllers/API/user";
import { useTable } from "@/util/hook";
import { formatDate } from "@/util/utils";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import {
    Table,
    TableBody,
    TableCell,
    TableFooter,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import { transformEvent, transformModule, transformObjectType } from "./utils";

const useGroups = () => {
    const [groups, setGroups] = useState([])
    const loadData = () => {
        getUserGroupsApi().then((res:any) => setGroups(res.records))
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
    const { users, selectedRef, loadUsers, searchUser } = useUsers()
    const { groups, loadData } = useGroups()
    const { modules, loadModules } = useModules()
    const { page, pageSize, data: logs, total, setPage, filterData } = useTable({ pageSize: 20 }, (param) =>
        getLogsApi({...param})
    )
    const init = {
        userIds: [],
        groupId: '',
        start: undefined,
        end: undefined,
        moduleId: '',
        action: ''
    }

    const [actions, setActions] = useState<any[]>([])
    const [keys, setKeys] = useState({...init})

    const handleActionOpen = async () => {
        setActions((keys.moduleId ? await getActionsByModuleApi(keys.moduleId) : await getActionsApi()))
    }
    const handleSearch = () => {
        const startTime = keys.start && formatDate(keys.start, 'yyyy-MM-dd HH:mm:ss')
        const endTime = keys.end && formatDate(keys.end, 'yyyy-MM-dd HH:mm:ss')
        filterData({...keys, start:startTime, end:endTime})
    }
    const handleReset = () => {
        setKeys({...init})
        filterData(init)
    }
    useEffect(() => {
        loadUsers()
    },[])

    return <div className="relative">
        <div className="h-[calc(100vh-98px)] overflow-y-auto px-2 py-4 pb-10">
            <div className="flex flex-wrap gap-4">
            <div className="w-[200px] relative">
                <MultiSelect className="overflow-y-auto max-w-[200px]" multiple
                    options={users}
                    value={keys.userIds}
                    placeholder={t('log.selectUser')}
                    onLoad={loadUsers}
                    onSearch={(key) => { searchUser(key); selectedRef.current = keys.userIds}}
                    onChange={(values) => {setKeys({...keys,userIds:values}); console.log(values)}}
                ></MultiSelect>
            </div>
            <div className="w-[200px] relative">
                <Select onOpenChange={loadData} value={keys.groupId} onValueChange={(value) => setKeys({...keys,groupId:value})}>
                    <SelectTrigger className="w-[200px]">
                        <SelectValue placeholder={t('log.selectUserGroup')} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {groups.map(g => <SelectItem value={g.id} key={g.id}>{g.group_name}</SelectItem>)}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
            <div className="w-[180px] relative">
                <DatePicker value={keys.start} placeholder={t('log.startDate')} onChange={(t) => setKeys({...keys,start:t})} />
            </div>
            <div className="w-[180px] relative">
                <DatePicker value={keys.end} placeholder={t('log.endDate')} onChange={(t) => setKeys({...keys,end:t})} />
            </div>
            <div className="w-[180px] relative">
                <Select value={keys.moduleId} onOpenChange={loadModules} onValueChange={(value) => setKeys({...keys,moduleId:value})}>
                    <SelectTrigger className="w-[180px]">
                        <SelectValue placeholder={t('log.systemModule')} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {modules.map(m => <SelectItem value={m.value} key={m.value}>{m.name}</SelectItem>)}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
            <div className="w-[180px] relative">
                <Select value={keys.action} onOpenChange={handleActionOpen} onValueChange={(value) => setKeys({...keys,action:value})}>
                    <SelectTrigger className="w-[180px]">
                        <SelectValue placeholder={t('log.actionBehavior')} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {actions.map(a => <SelectItem value={a.value} key={a.value}>{a.name}</SelectItem>)}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
                <div>
                    <Button className="mr-3 px-6" onClick={handleSearch}>
                        {t('log.searchButton')}
                    </Button>
                    <Button variant="outline" className="px-6" onClick={handleReset}>
                        {t('log.resetButton')}
                    </Button>
                </div>
            </div>
            <Table className="mb-[50px]">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('log.auditId')}</TableHead>
                        <TableHead className="w-[200px]">{t('log.username')}</TableHead>
                        <TableHead className="w-[200px]">{t('log.operationTime')}</TableHead>
                        <TableHead className="w-[100px]">{t('log.systemModule')}</TableHead>
                        <TableHead className="w-[150px]">{t('log.operationAction')}</TableHead>
                        <TableHead className="w-[150px]">{t('log.objectType')}</TableHead>
                        <TableHead className="w-[200px]">{t('log.operationObject')}</TableHead>
                        <TableHead className="w-[150px]">{t('log.ipAddress')}</TableHead>
                        <TableHead className="w-[200px]">{t('log.remark')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {logs.map((log:any) => (
                    <TableRow key={log.id}>
                        <TableCell>{log.id}</TableCell>
                        <TableCell><div className="truncate-multiline">{log.operator_name}</div></TableCell>
                        <TableCell>{log.create_time.replace('T', ' ')}</TableCell>
                        <TableCell>{transformModule(log.system_id)}</TableCell>
                        <TableCell>{transformEvent(log.event_type)}</TableCell>
                        <TableCell>{transformObjectType(log.object_type)}</TableCell>
                        <TableCell><div className="truncate-multiline">{log.object_name}</div></TableCell> {/* div是必要的 */}
                        <TableCell>{log.ip_address}</TableCell>
                        {/* whitespace-pre类保持原有的空格和换行符 */}
                        <TableCell><div className="whitespace-pre truncate-doubleline">{log.note?.replace('编辑后', `\n编辑后`)}</div></TableCell>
                    </TableRow>
                    ))}
                </TableBody>
                <TableFooter>
                    {!logs.length && <TableRow>
                        <TableCell colSpan={9} className="text-center text-gray-400">{t('build.empty')}</TableCell>
                    </TableRow>}
                </TableFooter>
            </Table>
        </div>
        {/* 分页 */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="bisheng-table-footer">
            <p className="desc pl-4">{t('log.auditManagement')}</p>
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
    const [users, setUsers] = useState<any[]>([]);
    const userRef = useRef([])
    const selectedRef = useRef([])

    const loadUsers = () => {
        getOperatorsApi().then(res => {
            const options = res.map((u:any) => ({label:u.user_name, value:u.user_id}))
            userRef.current = options
            setUsers(options)
        })
    }
    const search = (name) => {
        const newUsers = userRef.current.filter(u => u.label.toLowerCase().includes(name.toLowerCase())
                                                || selectedRef.current.includes(u.value))
        setUsers(newUsers)
    }

    return {
        users,
        selectedRef,
        loadUsers,
        searchUser(name) {
            search(name)
        }
    }
}