import { useEffect, useState } from "react"
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/ui/table";
import { Button } from "../../components/ui/button";
import { useNavigate } from "react-router-dom";
import EditRole from "./components/EditRole";
import { getRolesApi } from "../../controllers/API";

type ROLE = {
    create_time: string
    id: number
    remark: string
    role_name: string
    update_time: string
}

export default function Roles(params) {


    const [id, setId] = useState<number | null>(null)
    const [roles, setRoles] = useState<ROLE[]>([])
    console.log('roles :>> ', roles);

    const handleChange = (change: boolean) => {
        change && loadData()
        setId(null)
    }

    const loadData = () => {
        getRolesApi().then(res => {
            setRoles(res.data.data);
        })
    }

    useEffect(() => loadData(), [])

    if (id) return <EditRole id={id} onChange={handleChange}></EditRole>

    return <div className=" relative">
        <Button className="h-8 rounded-full absolute right-0 top-[-40px]" onClick={() => setId(-1)}>创建</Button>
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
                            <Button variant="link" disabled={false} onClick={() => setId(el.id)}>编辑</Button>
                            <Button variant="link" disabled={false} className="text-red-500">删除</Button>
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    </div>
};
