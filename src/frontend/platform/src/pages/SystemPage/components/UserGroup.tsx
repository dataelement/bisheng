import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import { PlusIcon } from "@/components/bs-icons/plus";
import { getUserGroupsApi, delUserGroupApi, getAdminsApi, getUserGroupsProApiV2 } from "@/controllers/API/user"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
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
import EditUserGroup from "./EditUserGroup";
import { UserGroup } from "@/types/api/user";
import { locationContext } from "@/contexts/locationContext";
import { getUserGroupsProApi } from "@/controllers/API/pro";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { useTable } from "@/util/hook";

export default function UserGroups() {
    const { t } = useTranslation()
    const [userGroups, setUserGroups] = useState<UserGroup[]>([])
    const [userGroup, setUserGroup] = useState(null)
    const tempRef = useRef<UserGroup[]>([]) // 搜索功能的数据暂存
    const { appConfig } = useContext(locationContext)
    const defaultAdminsRef = useRef([])

    
    const { page, pageSize, data: groupsData, total, setPage, search, reload, filterData } = useTable({ pageSize: 20 }, (param) =>
        (appConfig.isPro ? getUserGroupsProApi : getUserGroupsProApiV2)({
            ...param,
            name: param.keyword
        })
    )
    
    useEffect(() => {
        getAdmins();
     }, [])

    const getAdmins = async () => {
        defaultAdminsRef.current = await getAdminsApi();
    } 

    useEffect(() => {
        const groups = groupsData.map((g: any)=> {
            const group_admins = [...defaultAdminsRef.current, ...g.group_admins];
            const group_audits = [...defaultAdminsRef.current, ...g.group_audits];
            const group_operations = [...defaultAdminsRef.current, ...g.group_operations];
            return {
                ...g,
                group_admins,
                group_audits,
                group_operations
            }
        });
        setUserGroups(groups);
        tempRef.current = groups;
     }, [groupsData, defaultAdminsRef])

    const handleDelete = (userGroup) => {
        bsConfirm({
            desc: t('system.deleteGroup', { name: userGroup.group_name }),
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(delUserGroupApi(userGroup.id).then(reload))
                next()
            }
        })
    }

    const checkSameName = (name: string) => {
        return (userGroups.find(ug =>
            ug.group_name === name && ug.id !== userGroup.id))
    }
    const handleChange = () => {
        setUserGroup(null)
        reload()
    }


    if (userGroup) return <EditUserGroup
        data={userGroup}
        onBeforeChange={checkSameName}
        onChange={handleChange}
    />

    return <div className="relative">
        <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10">
            <div className="flex gap-6 items-center justify-end">
                <div className="w-[180px] relative">
                    <SearchInput placeholder={t('system.groupName')} onChange={(e) => search(e.target.value)}></SearchInput>
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
                        <TableHead>{t('system.permissionsAdmins')}</TableHead>
                        <TableHead>{t('system.auditor')}</TableHead>
                        <TableHead>{t('system.operator')}</TableHead>
                        {appConfig.isPro && <TableHead className="w-[150px]">{t('system.flowControl')}</TableHead>}
                        <TableHead className="w-[160px]">上级用户组</TableHead>
                        <TableHead className="w-[160px]">{t('system.changeTime')}</TableHead>
                        <TableHead className="text-right w-[130px]">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {userGroups.map((ug: any) => (
                        <TableRow key={ug.id}>
                            <TableCell className="font-medium">{ug.group_name}</TableCell>
                            {/* TODO: admin_user是啥？ zzy */}
                            <TableCell className="break-all">{(ug.admin_user || ug.group_admins).map(el => el.user_name).join(',')}</TableCell>
                            <TableCell className="break-all">{(ug.admin_user || ug.group_audits).map(el => el.user_name).join(',')}</TableCell>
                            <TableCell className="break-all">{(ug.admin_user || ug.group_operations).map(el => el.user_name).join(',')}</TableCell>
                            {appConfig.isPro && <TableCell>{ug.group_limit ? t('system.limit') : t('system.unlimited')}</TableCell>}
                            <TableCell>{ug.parent_group_path || '无'}</TableCell>
                            <TableCell>{ug.update_time.replace('T', ' ')}</TableCell>
                            <TableCell className="text-right">
                                <Button variant="link" onClick={() => setUserGroup({
                                    ...ug,
                                    group_admins: ug.group_admins.slice(defaultAdminsRef.current.length),
                                    group_audits: ug.group_audits.slice(defaultAdminsRef.current.length),
                                    group_operations: ug.group_operations.slice(defaultAdminsRef.current.length),
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
        {/* 分页 */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="bisheng-table-footer bg-background-login">
        <p className="desc">{t('system.userGroupList')}</p>
            <AutoPagination
                className="float-right justify-end w-full mr-6"
                page={page}
                pageSize={pageSize}
                total={total}
                onChange={(newPage) => setPage(newPage)}
            />
        </div>
    </div>
}