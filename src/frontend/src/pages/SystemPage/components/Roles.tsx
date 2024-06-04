import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { delRoleApi, getRolesApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { ROLE } from "../../../types/api/user";
import EditRole from "./EditRole";
import { SearchInput } from "../../../components/bs-ui/input";
import { PlusIcon } from "@/components/bs-icons/plus";
export default function Roles() {
    const { t } = useTranslation()

    const [role, setRole] = useState<Partial<ROLE> | null>(null)
    const [roles, setRoles] = useState<ROLE[]>([])
    const allRolesRef = useRef([])

    const handleChange = (change: boolean) => {
        change && loadData()
        setRole(null)
    }

    const loadData = () => {
        getRolesApi().then(data => {
            setRoles(data)
            allRolesRef.current = data
        })
    }

    useEffect(() => loadData(), [])

    // 删除
    const handleDelete = (item) => {
        bsConfirm({
            desc: `${t('system.confirmText')} 【${item.role_name}】 ?`,
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(delRoleApi(item.id).then(loadData))
                next()
            }
        })
    }

    // 验证重名
    const checkSameName = (name: string) => {
        return (roles.find(_role =>
            _role.role_name === name && role.id !== _role.id))
    }

    // search
    const [searchWord, setSearchWord] = useState('')
    const handleSearch = (e) => {
        const word = e.target.value
        setSearchWord(word)
        setRoles(allRolesRef.current.filter(item => item.role_name.toUpperCase().includes(word.toUpperCase())))
    }

    if (role) return <EditRole id={role.id || -1} name={role.role_name || ''} onBeforeChange={checkSameName} onChange={handleChange}></EditRole>

    return <div className="relative">
        <div className="h-[calc(100vh-136px)] overflow-y-auto pb-10">
            <div className="flex gap-6 items-center justify-end">
                <div className="w-[180px] relative">
                    <SearchInput placeholder={t('system.roleName')} onChange={handleSearch}></SearchInput>
                </div>
                <Button className="flex justify-around" onClick={() => setRole({})}>
                    <PlusIcon className="text-primary" />
                    <span className="text-[#fff] mx-4">{t('create')}</span>
                </Button>
            </div>
            <Table className="mb-10">
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">{t('system.roleName')}</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {roles.map((el) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium">{el.role_name}</TableCell>
                            <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                            <TableCell className="text-right">
                                <Button variant="link" onClick={() => setRole(el)} className="px-0 pl-6">{t('edit')}</Button>
                                <Button variant="link" disabled={[1, 2].includes(el.id)} onClick={() => handleDelete(el)} className="text-red-500 px-0 pl-6">{t('delete')}</Button>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
        <div className="bisheng-table-footer">
            <p className="desc">{t('system.roleList')}.</p>
        </div>
    </div>
};
