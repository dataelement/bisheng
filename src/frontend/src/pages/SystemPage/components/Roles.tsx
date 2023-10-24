import { useEffect, useState } from "react"
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/ui/table";
import { Button } from "../../../components/ui/button";
import { useNavigate } from "react-router-dom";
import EditRole from "./EditRole";
import { delRoleApi, getRolesApi } from "../../../controllers/API/user";
import { bsconfirm } from "../../../alerts/confirm";

export type ROLE = {
    create_time: string
    id: number
    remark: string
    role_name: string
    update_time: string
}

export default function Roles(params) {


    const [role, setRole] = useState<ROLE | null | {}>(null)
    const [roles, setRoles] = useState<ROLE[]>([])
    console.log('roles :>> ', roles);

    const handleChange = (change: boolean) => {
        change && loadData()
        setRole(null)
    }

    const loadData = () => {
        getRolesApi().then(res => {
            setRoles(res.data.data);
        })
    }

    useEffect(() => loadData(), [])

    // 删除
    const handleDelete = (item) => {
        bsconfirm({
            desc: `是否删除 【${item.role_name}】 ?`,
            okTxt: '删除',
            onOk(next) {
                delRoleApi(item.id).then(loadData)
                next()
            }
        })
    }

    if (role) return <EditRole id={role?.id || -1} name={role?.role_name || ''} onChange={handleChange}></EditRole>

    return <div className=" relative">
        <Button className="h-8 rounded-full absolute right-0 top-[-40px]" onClick={() => setRole({})}>创建</Button>
        <Table>
            <TableCaption>角色列表.</TableCaption>
            <TableHeader>
                <TableRow>
                    <TableHead className="w-[200px]">角色名</TableHead>
                    <TableHead>创建时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {roles.map((el) => (
                    <TableRow key={el.id}>
                        <TableCell className="font-medium">{el.role_name}</TableCell>
                        <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                        <TableCell className="text-right">
                            <Button variant="link" disabled={[1, 2].includes(el.id)} onClick={() => setRole(el)}>编辑</Button>
                            <Button variant="link" disabled={[1, 2].includes(el.id)} onClick={() => handleDelete(el)} className="text-red-500">删除</Button>
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    </div>
};
