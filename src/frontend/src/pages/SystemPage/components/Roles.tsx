import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsconfirm } from "../../../alerts/confirm";
import { Button } from "../../../components/ui/button";
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/ui/table";
import { delRoleApi, getRolesApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { ROLE } from "../../../types/api/user";
import EditRole from "./EditRole";

export default function Roles() {
    const { t } = useTranslation()

    const [role, setRole] = useState<Partial<ROLE> | null>(null)
    const [roles, setRoles] = useState<ROLE[]>([])

    const handleChange = (change: boolean) => {
        change && loadData()
        setRole(null)
    }

    const loadData = () => {
        getRolesApi().then(data =>
            setRoles(data)
        )
    }

    useEffect(() => loadData(), [])

    // 删除
    const handleDelete = (item) => {
        bsconfirm({
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

    if (role) return <EditRole id={role.id || -1} name={role.role_name || ''} onBeforeChange={checkSameName} onChange={handleChange}></EditRole>

    return <div className=" relative">
        <Button className="h-8 rounded-full absolute right-0 top-[-40px]" onClick={() => setRole({})}>{t('create')}</Button>
        <Table>
            <TableCaption>{t('system.roleList')}.</TableCaption>
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
                            <Button variant="link" disabled={[1, 2].includes(el.id)} onClick={() => setRole(el)}>{t('edit')}</Button>
                            <Button variant="link" disabled={[1, 2].includes(el.id)} onClick={() => handleDelete(el)} className="text-red-500">{t('delete')}</Button>
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    </div>
};
