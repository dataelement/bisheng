import { FilterIcon } from "@/components/bs-icons/filter";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import FilterUserGroup from "@/components/bs-ui/select/filter";
import { getRolesApi, getUserGroupsApi } from "@/controllers/API/user";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import {
    Table,
    TableBody,
    TableCell,
    TableFooter,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { userContext } from "../../../contexts/userContext";
import { disableUserApi, getUsersApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import UserRoleModal from "./UserRoleModal";
import UserPwdModal from "@/pages/LoginPage/UserPwdModal";
import { PlusIcon } from "@/components/bs-icons";
import CreateUser from "./CreateUser";

function UsersFilter({ options, onChecked, nameKey, placeholder, onFilter }) {
    const [open, setOpen] = useState(false)
    const [_value, setValue] = useState([])
    const [searchKey, setSearchKey] = useState('')
    // 点击 checkbox
    const handlerChecked = (id) => {
        setValue(val => {
            const index = val.indexOf(id)
            index === -1 ? val.push(id) : val.splice(index, 1)
            return [...val]
        })
        // 已选项上浮
        const checked = options.filter(o => _value.includes(o.id))
        const uncheck = options.filter(o => !_value.includes(o.id))
        onChecked([...checked, ...uncheck])
    }

    const filterData = () => {
        onFilter(_value)
        setOpen(false)
    }
    // 搜索
    const _options = useMemo(() => {
        if (!searchKey) return options
        return options.filter(a => a[nameKey].toUpperCase().includes(searchKey.toUpperCase()))
    }, [searchKey, options])
    // 重置
    const reset = () => {
        setValue([])
        setSearchKey('')
    }

    return <Popover open={open} onOpenChange={(bln) => { setOpen(bln); setSearchKey('') }}>
        <PopoverTrigger>
            {/* @ts-ignore */}
            <FilterIcon onClick={() => setOpen(!open)} className={_value.length ? 'text-primary ml-3' : 'text-gray-400 ml-3'} />
        </PopoverTrigger>
        <PopoverContent>
            <FilterUserGroup
                value={_value}
                options={_options}
                nameKey={nameKey}
                placeholder={placeholder}
                onChecked={handlerChecked}
                search={(e) => setSearchKey(e.target.value)}
                onClearChecked={reset}
                onOk={filterData}
            />
        </PopoverContent>
    </Popover>

}


export default function Users(params) {
    const { user } = useContext(userContext);
    const { t } = useTranslation()

    const { page, pageSize, data: users, total, setPage, search, reload, filterData } = useTable({ pageSize: 20 }, (param) =>
        getUsersApi({
            ...param,
            name: param.keyword
        })
    )

    // 禁用确认
    const handleDelete = (user) => {
        bsConfirm({
            title: `${t('prompt')}!`,
            desc: t('system.confirmDisable'),
            okTxt: t('disable'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(disableUserApi(user.user_id, 1).then(res => {
                    reload()
                }))
                next()
            }
        })
    }
    const handleEnableUser = (user) => {
        captureAndAlertRequestErrorHoc(disableUserApi(user.user_id, 0).then(res => {
            reload()
        }))
    }

    // 编辑
    const [currentUser, setCurrentUser] = useState(null)
    const userPwdModalRef = useRef(null)
    const handleRoleChange = () => {
        setCurrentUser(null)
        reload()
    }

    // 获取用户组类型数据
    const [userGroups, setUserGroups] = useState([])
    const getUserGoups = async () => {
        const res: any = await getUserGroupsApi()
        setUserGroups(res.records)
    }
    // 获取角色类型数据
    const [roles, setRoles] = useState([])
    const getRoles = async () => {
        const res: any = await getRolesApi()
        setRoles(res)
    }
    // 已选项上浮
    const handleGroupChecked = (values) => {
        setUserGroups(values)
    }
    const handleRoleChecked = (values) => {
        setRoles(values)
    }

    const [openCreate, setOpenCreate] = useState(false)

    useEffect(() => {
        getUserGoups()
        getRoles()
        return () => { setUserGroups([]); setRoles([]) }
    }, [])

    const operations = (el) => {
        const isSuperAdmin = el.roles.some(role => role.id === 1)
        // 禁止编辑admin用户
        if (isSuperAdmin) return <div>
            <Button variant="link" disabled className="px-0">{t('edit')}</Button>
            {/* <Button variant="link" disabled className="px-0 pl-4">{t('system.resetPwd')}</Button> */}
            <Button variant="link" className="px-0 pl-4" onClick={() => userPwdModalRef.current.open(el.user_id)}>{t('system.resetPwd')}</Button>
            <Button variant="link" disabled className="text-red-500 px-0 pl-4">{t('disable')}</Button>
        </div>

        return <div>
            {/* 编辑 */}
            <Button variant="link" disabled={user.user_id === el.user_id} onClick={() => setCurrentUser(el)} className="px-0">{t('edit')}</Button>
            {/* 重置密码 */}
            {(user.role === 'admin' || user.role === 'group_admin') &&
                <Button variant="link" className="px-0 pl-4" onClick={() => userPwdModalRef.current.open(el.user_id)}>{t('system.resetPwd')}</Button>}
            {/* 禁用 */}
            {
                el.delete === 1 ? <Button variant="link" onClick={() => handleEnableUser(el)} className="text-green-500 px-0 pl-4">{t('enable')}</Button> :
                    <Button variant="link" disabled={user.user_id === el.user_id} onClick={() => handleDelete(el)} className="text-red-500 px-0 pl-4">{t('disable')}</Button>
            }
        </div>
    }

    return <div className="relative">
        <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10">
            <div className="flex justify-end gap-6">
                <div className="w-[180px] relative">
                    <SearchInput placeholder={t('system.username')} onChange={(e) => search(e.target.value)}></SearchInput>
                </div>
                {user.role === 'admin' && <Button className="flex justify-around" onClick={() => setOpenCreate(true)}>
                    <PlusIcon className="text-primary" />
                    <span className="text-[#fff] mx-4">{t('create')}</span>
                </Button>}
            </div>
            <Table className="mb-[50px]">
                {/* <TableCaption>用户列表.</TableCaption> */}
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('system.username')}</TableHead>
                        <TableHead>
                            <div className="flex items-center">
                                {t('system.userGroup')}
                                <UsersFilter
                                    options={userGroups}
                                    nameKey='group_name'
                                    onChecked={handleGroupChecked}
                                    placeholder={t('system.searchUserGroups')}
                                    onFilter={(ids) => filterData({ groupId: ids })}
                                ></UsersFilter>
                            </div>
                        </TableHead>
                        <TableHead>
                            <div className="flex items-center">
                                {t('system.role')}
                                <UsersFilter
                                    options={roles}
                                    nameKey='role_name'
                                    onChecked={handleRoleChecked}
                                    placeholder={t('system.searchRoles')}
                                    onFilter={(ids) => filterData({ roleId: ids })}
                                ></UsersFilter>
                            </div>
                        </TableHead>
                        <TableHead>{t('system.changeTime')}</TableHead>
                        <TableHead className="text-right w-[164px]">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {users.map((el: any) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium max-w-md truncate">{el.user_name}</TableCell>
                            {/* <TableCell>{el.role}</TableCell> */}
                            <TableCell className="break-all">{(el.groups || []).map(el => el.name).join(',')}</TableCell>
                            <TableCell className="break-all">{(el.roles || []).map(el => el.name).join(',')}</TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell className="text-right">{operations(el)}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
                <TableFooter>
                    {!users.length && <TableRow>
                        <TableCell colSpan={5} className="text-center text-gray-400">{t('build.empty')}</TableCell>
                    </TableRow>}
                </TableFooter>
            </Table>
        </div>
        {/* 分页 */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="bisheng-table-footer bg-background-login">
            <p className="desc">{t('system.userList')}</p>
            <AutoPagination
                className="float-right justify-end w-full mr-6"
                page={page}
                pageSize={pageSize}
                total={total}
                onChange={(newPage) => setPage(newPage)}
            />
        </div>

        <CreateUser open={openCreate} onClose={(bool) => { setOpenCreate(bool); reload() }} onSave={reload} />
        <UserRoleModal user={currentUser} onClose={() => setCurrentUser(null)} onChange={handleRoleChange}></UserRoleModal>
        <UserPwdModal ref={userPwdModalRef} />
    </div>
};
