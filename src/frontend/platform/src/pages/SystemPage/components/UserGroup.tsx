import { useTranslation } from "react-i18next"
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "../../../components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import { PlusIcon } from "@/components/bs-icons/plus";
import { deleteUserGroupV2, listUserGroupsV2, UserGroupV2 } from "@/controllers/API/userGroups";
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
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";

export default function UserGroups() {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const [userGroups, setUserGroups] = useState<UserGroupV2[]>([])
    const [userGroup, setUserGroup] = useState<UserGroupV2 | Record<string, never> | null>(null)
    const tempRef = useRef<UserGroupV2[]>([])
    const { appConfig } = useContext(locationContext)

    const HIDDEN_GROUP_NAMES = new Set(['Default user group', '默认用户组'])

    const loadData = async () => {
        const res = await listUserGroupsV2()
        const records = (res?.data ?? []).filter((ug) => !HIDDEN_GROUP_NAMES.has(ug.group_name))
        setUserGroups(records)
        tempRef.current = records
    }

    const handleSearch = (e) => {
        const word = e.target.value
        const newUgs = tempRef.current.filter(ug =>
            ug.group_name.toUpperCase().includes(word.toUpperCase()))
        setUserGroups(newUgs)
    }
    const handleDelete = (ug: UserGroupV2) => {
        bsConfirm({
            desc: t('system.deleteGroup', { name: ug.group_name }),
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteUserGroupV2(ug.id).then(loadData))
                next()
            }
        })
    }

    const canDeleteGroup = (ug: UserGroupV2) => {
        if (user?.role === "admin") return true
        if (user?.is_department_admin && ug.create_user === user?.user_id) return true
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
            }
        }
        setUserGroup(null)
    }

    useEffect(() => {
        loadData().catch(() => {
            setUserGroups([])
            tempRef.current = []
        })
    }, [])

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
                <Button className="flex justify-around" onClick={() => setUserGroup({})}>
                    <PlusIcon className="text-primary" />
                    <span className="text-[#fff] mx-4">{t('create')}</span>
                </Button>
            </div>
            <Table className="mb-10">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('system.groupName')}</TableHead>
                        <TableHead>{t('system.groupCreator')}</TableHead>
                        {appConfig.isPro && <TableHead className="w-[150px]">{t('system.flowControl')}</TableHead>}
                        <TableHead className="w-[100px]">{t('system.groupVisibility')}</TableHead>
                        <TableHead className="w-[160px]">{t('system.changeTime')}</TableHead>
                        <TableHead className="text-right w-[130px]" >{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {userGroups.map((ug) => (
                        <TableRow key={ug.id}>
                            <TableCell className="font-medium">{ug.group_name}</TableCell>
                            <TableCell className="break-all">{displayCreator(ug)}</TableCell>
                            {appConfig.isPro && <TableCell>{(ug as any).group_limit ? t('system.limit') : t('system.unlimited')}</TableCell>}
                            <TableCell>
                                <Badge variant={ug.visibility === 'private' ? 'secondary' : 'outline'}>
                                    {ug.visibility === 'private' ? t('system.visibilityPrivate') : t('system.visibilityPublic')}
                                </Badge>
                            </TableCell>
                            <TableCell>{(ug.update_time || "").replace("T", " ")}</TableCell>
                            <TableCell className="text-right" style={{
                                whiteSpace: 'nowrap',
                            }}>
                                <Button variant="link" onClick={() => setUserGroup({ ...ug })}
                                    className="px-0 pl-6">{t('edit')}
                                </Button>
                                <Button variant="link" disabled={!canDeleteGroup(ug)} onClick={() => handleDelete(ug)} className="text-red-500 px-0 pl-6">{t('delete')}</Button>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
                <TableFooter>
                    {!userGroups.length && <TableRow>
                        <TableCell colSpan={appConfig.isPro ? 6 : 5} className="text-center text-gray-400">{t('build.empty')}</TableCell>
                    </TableRow>}
                </TableFooter>
            </Table>
        </div>
        <div className="bisheng-table-footer bg-background-login">
            <p className="desc">{t('system.userGroupList')}.</p>
        </div>
    </div>
}
