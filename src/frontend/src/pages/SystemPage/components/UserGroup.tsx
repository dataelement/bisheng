import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import { PlusIcon } from "@/components/bs-icons/plus";
import { getUserGroupsApi, delUserGroupApi } from "@/controllers/API/user"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useEffect, useRef, useState } from "react";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import EditUserGroup from "./EditUserGroup";
import { UserGroup } from "@/types/api/user";

export default function UserGroups() {
    const { t } = useTranslation()
    const [userGroups, setUserGroups] = useState<UserGroup[]>([])
    const [userGroup, setUserGroup] = useState(null)
    const tempRef = useRef<UserGroup[]>([]) // 搜索功能的数据暂存

    const loadData = async () => {
        const res = await getUserGroupsApi()  
        setUserGroups(res.data.records)  
        tempRef.current = res.data.records
    }

    const handleSearch = (e) => {
        const word = e.target.value
        const newUgs = tempRef.current.filter(ug => ug.groupName.toUpperCase().includes(word.toUpperCase()))
        setUserGroups(newUgs)
    }
    const handleDelete = (userGroup) => {
        bsConfirm({
            desc: `${t('system.confirmText')} 【${userGroup.groupName}】 ?`,
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(delUserGroupApi(userGroup.id).then(loadData))
                next()
            }
        })
    }

    const checkSameName = (name: string) => {
        return (userGroups.find(ug =>
            ug.groupName === name && ug.id !== userGroup.id))
    }
    const handleChange = (flag:boolean) => {
        flag && loadData()
        setUserGroup(null)
    }

    useEffect(() => { loadData() }, [])

    if(userGroup) return <EditUserGroup id={userGroup.id || ''} name={userGroup.groupName || ''} onBeforeChange={checkSameName} onChange={handleChange}/>

    return <div className="relative">
        <div className="h-[calc(100vh-136px)] overflow-y-auto pb-10">
            <div className="flex gap-6 items-center justify-end">
                <div className="w-[180px] relative">
                    <SearchInput placeholder={t('system.userGroupName')} onChange={handleSearch}></SearchInput>
                </div>
                <Button className="flex justify-around" onClick={() => setUserGroup({})}>
                    <PlusIcon className="text-primary" />
                    <span className="text-[#fff] mx-4">{t('create')}</span>
                </Button>
            </div>
            <Table className="mb-10">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('system.userGroupName')}</TableHead>
                        <TableHead>{t('system.admins')}</TableHead>
                        <TableHead>{t('system.flowControl')}</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {userGroups.map((ug) => (
                        <TableRow key={ug.id}>
                            <TableCell className="font-medium">{ug.groupName}</TableCell>
                            <TableCell>{ug.adminUser.replaceAll(',', '，')}</TableCell>
                            <TableCell>{ug.groupLimit ? t('system.limit') : t('system.unlimited')}</TableCell>
                            <TableCell>{ug.updateTime.replace('T', ' ')}</TableCell>
                            <TableCell className="text-right">
                                <Button variant="link" onClick={() => setUserGroup(ug)} className="px-0 pl-6">{t('edit')}</Button>
                                <Button variant="link" disabled={[1].includes(ug.id)} onClick={() => handleDelete(ug)} className="text-red-500 px-0 pl-6">{t('delete')}</Button>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
        <div className="bisheng-table-footer">
            <p className="desc">{t('system.userGroupList')}.</p>
        </div>
    </div>
}