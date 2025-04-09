import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import { PlusIcon } from "@/components/bs-icons/plus";
import { getUserGroupsApi, delUserGroupApi, getAdminsApi } from "@/controllers/API/user"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useContext, useEffect, useRef, useState } from "react";
import {
    Table,
    TableBody,
    TableCell,
    TableFooter,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import EditUserGroup from "./EditUserGroup";
import { UserGroup } from "@/types/api/user";
import { locationContext } from "@/contexts/locationContext";
import { getUserGroupsProApi } from "@/controllers/API/pro";

export default function UserGroups() {
    const { t } = useTranslation()
    const [userGroups, setUserGroups] = useState<UserGroup[]>([])
    const [userGroup, setUserGroup] = useState(null)
    const tempRef = useRef<UserGroup[]>([]) // 搜索功能的数据暂存
    const { appConfig } = useContext(locationContext)
    const defaultAdminsRef = useRef([])

    const loadData = async () => {
        const res: any = await (appConfig.isPro ? getUserGroupsProApi : getUserGroupsApi)()
        defaultAdminsRef.current = await getAdminsApi()
        res.records.map(g => g.group_admins = [...defaultAdminsRef.current, ...g.group_admins])
        setUserGroups(res.records)
        tempRef.current = res.records
    }

    const handleSearch = (e) => {
        const word = e.target.value
        const newUgs = tempRef.current.filter(ug => ug.group_name.toUpperCase().includes(word.toUpperCase()))
        setUserGroups(newUgs)
    }
    const handleDelete = (userGroup) => {
        bsConfirm({
            desc: t('system.deleteGroup', { name: userGroup.group_name }),
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(delUserGroupApi(userGroup.id).then(loadData))
                next()
            }
        })
    }

    const checkSameName = (name: string) => {
        return (userGroups.find(ug =>
            ug.group_name === name && ug.id !== userGroup.id))
    }
    const handleChange = (flag: boolean) => {
        flag && loadData()
        setUserGroup(null)
    }

    useEffect(() => { loadData() }, [])

    if (userGroup) return <EditUserGroup
        data={userGroup}
        onBeforeChange={checkSameName}
        onChange={handleChange}
    />

    return <div className="relative">
        <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10">
            <div className="flex gap-6 items-center justify-end">
                <div className="w-[180px] relative">
                    <SearchInput placeholder={t('system.groupName')} onChange={handleSearch}></SearchInput>
                </div>
                <Button className="flex justify-around" onClick={() => setUserGroup({})}>
                    <PlusIcon className="text-primary" />
                    <span className="text-[#fff] mx-4">{t('create')}</span>
                </Button>
            </div>
            <Table className="mb-10">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('system.groupName')}</TableHead>
                        <TableHead>{t('system.admins')}</TableHead>
                        {appConfig.isPro && <TableHead className="w-[150px]">{t('system.flowControl')}</TableHead>}
                        <TableHead className="w-[160px]">{t('system.changeTime')}</TableHead>
                        <TableHead className="text-right w-[130px]">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {userGroups.map((ug: any) => (
                        <TableRow key={ug.id}>
                            <TableCell className="font-medium">{ug.group_name}</TableCell>
                            <TableCell className="break-all">{(ug.admin_user || ug.group_admins).map(el => el.user_name).join(',')}</TableCell>
                            {appConfig.isPro && <TableCell>{ug.group_limit ? t('system.limit') : t('system.unlimited')}</TableCell>}
                            <TableCell>{ug.update_time.replace('T', ' ')}</TableCell>
                            <TableCell className="text-right">
                                <Button variant="link" onClick={() => setUserGroup({
                                    ...ug,
                                    group_admins: ug.group_admins.slice(defaultAdminsRef.current.length)
                                })}
                                    className="px-0 pl-6">{t('edit')}
                                </Button>
                                <Button variant="link" disabled={ug.id === 2} onClick={() => handleDelete(ug)} className="text-red-500 px-0 pl-6">{t('delete')}</Button>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
                <TableFooter>
                    {!userGroups.length && <TableRow>
                        <TableCell colSpan={5} className="text-center text-gray-400">{t('build.empty')}</TableCell>
                    </TableRow>}
                </TableFooter>
            </Table>
        </div>
        <div className="bisheng-table-footer bg-background-login">
            <p className="desc">{t('system.userGroupList')}.</p>
        </div>
    </div>
}