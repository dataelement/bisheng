import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FilterIcon } from "@/components/bs-icons/filter";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import FilterUserGroup from "@/components/bs-ui/select/filter";
import { getSearchRes } from "@/controllers/API/user";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { userContext } from "../../../contexts/userContext";
import { disableUserApi, getRoleTypes, getUserGroupTypes, getUsersApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import UserRoleModal from "./UserRoleModal";


function UsersFilter({arr, placeholder, onButtonClick, onIsOpen}) {
    const setDefault = (array) => {
        return array.map((a, index) => (a.name == '默认用户组' ||  a.name == '普通用户') ? {...a, checked:true} : a)
    }

    const [items, setItems] = useState(setDefault(arr))
    const handlerChecked = (id) => {
      const newItems = items.map((item:any) => item.id === id ? {...item, checked:!item.checked} : item)
      setItems(newItems)
    }

    const filterData = () => {
        const res = getSearchRes('zgj')
        onButtonClick(res)
        onIsOpen(false)
    }
    const getSearchKey = (e) => {
        const key = e.target.value
        let newItems = []
        if(!key.toUpperCase()) {
            newItems = setDefault(arr)
        } else {
            newItems = setDefault(arr.filter(a => a.name.toUpperCase().includes(key.toUpperCase())))
        }
        setItems(newItems)
    }

  return <FilterUserGroup 
    options={items} 
    placeholder={placeholder} 
    onChecked={handlerChecked} 
    search={getSearchKey} 
    onClearChecked={() => setItems(setDefault(arr))} 
    onOk={filterData} 
  />
}

export default function Users(params) {
    const { user } = useContext(userContext);
    const { t } = useTranslation()

    const { page, pageSize, data: users, total, loading, setPage, search, reload, filterData } = useTable({ pageSize: 13 }, (param) =>
        getUsersApi(param.keyword, param.page, param.pageSize)
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
    const [roleOpenId, setRoleOpenId] = useState(null)
    const handleRoleChange = () => {
        setRoleOpenId(null)
        reload()
    }

    // 搜索返回的数据
    const [data, setData] = useState('')
    const getFilterData = (data) => {
        setData(data)
    }

    const [flagUserGroup, setFlagUserGroup] = useState(false)
    const [flagRole, setFlagRole] = useState(false)

    // 获取用户组类型数据
    const [userGroups, setUserGroups] = useState([])
    const getUserGoups = () => {
        const res = getUserGroupTypes()
        setUserGroups(res)
    }
    // 获取角色类型数据
    const [roles, setRoles] = useState([])
    const getRoles = () => {
        const res = getRoleTypes()
        setRoles(res)
    }

    useEffect(() => {
        getUserGoups()
        getRoles()
        return () => {setUserGroups([]); setRoles([])}
    },[])

    return <div className="relative">
        <div className="h-[calc(100vh-136px)] overflow-y-auto pb-10">
            <div className="flex justify-end">
                <div className="w-[180px] relative">
                    <SearchInput placeholder={t('system.username')} onChange={(e) => search(e.target.value)}></SearchInput>
                </div>
            </div>
            <Table className="mb-[50px]">
                {/* <TableCaption>用户列表.</TableCaption> */}
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('system.username')}</TableHead>
                        <TableHead>
                            <div className="flex items-center">
                                {t('system.userGroup')}
                                <Popover open={flagUserGroup} onOpenChange={() => setFlagUserGroup(!flagUserGroup)}> {/* onOpenChange点击空白区域触发 */}
                                    <PopoverTrigger>
                                        <FilterIcon onClick={() => setFlagUserGroup(!flagUserGroup)} className="text-gray-400 ml-3"/>
                                    </PopoverTrigger>
                                    <PopoverContent>
                                        <UsersFilter arr={userGroups} placeholder={t('system.searchUserGroups')} 
                                        onButtonClick={getFilterData} onIsOpen={(is) => setFlagUserGroup(is)}></UsersFilter>
                                    </PopoverContent>
                                </Popover>
                            </div>
                        </TableHead> 
                        <TableHead>
                            <div className="flex items-center">
                                {t('system.role')}
                                <Popover open={flagRole} onOpenChange={() => setFlagRole(!flagRole)}>
                                    <PopoverTrigger>
                                        <FilterIcon onClick={() => setFlagRole(!flagRole)} className="text-blue-500 ml-3"/>
                                    </PopoverTrigger>
                                    <PopoverContent>
                                        <UsersFilter arr={roles} placeholder={t('system.searchRoles')} 
                                        onButtonClick={getFilterData} onIsOpen={(is) => setFlagRole(is)}></UsersFilter>
                                    </PopoverContent>
                                </Popover>
                            </div>
                        </TableHead> 
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {users.map((el) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium max-w-md truncate">{el.user_name}</TableCell>
                            {/* <TableCell>{el.role}</TableCell> */}
                            <TableCell>用户组A</TableCell>
                            <TableCell>角色B</TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell className="text-right">
                                {user.user_id === el.user_id ? <Button variant="link" className="text-gray-400 px-0 pl-6">{t('edit')}</Button> :
                                    <Button variant="link" onClick={() => setRoleOpenId(el.user_id)} className="px-0 pl-6">{t('edit')}</Button>}
                                {
                                    el.delete === 1 ? <Button variant="link" onClick={() => handleEnableUser(el)} className="text-green-500 px-0 pl-6">{t('enable')}</Button> :
                                        user.user_id === el.user_id ? <Button variant="link" className="text-gray-400 px-0 pl-6">{t('disable')}</Button> :
                                            <Button variant="link" onClick={() => handleDelete(el)} className="text-red-500 px-0 pl-6">{t('disable')}</Button>
                                }
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
        {/* 分页 */}
        {/* <Pagination count={10}></Pagination> */}
        <div className="bisheng-table-footer">
            <p className="desc">{t('system.userList')}</p>
            <AutoPagination
                className="float-right justify-end w-full mr-6"
                page={page}
                pageSize={pageSize}
                total={total}
                onChange={(newPage) => setPage(newPage)}
            />
        </div>

        <UserRoleModal id={roleOpenId} onClose={() => setRoleOpenId(null)} onChange={handleRoleChange}></UserRoleModal>
    </div>
};
