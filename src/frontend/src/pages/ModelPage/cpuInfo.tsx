import { useEffect, useState } from "react";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/ui/table";
import { GPUlistApi } from "../../controllers/API";

export const CpuDetail = () => {

    const [datalist, setDatalist] = useState([])

    const loadData = () => {
        GPUlistApi().then(res => {
            setDatalist(res.data.list[0])
        })
    }

    useEffect(loadData, [])

    // 2s刷新一次
    useEffect(() => {
        const timer = setTimeout(loadData, 1000 * 2);

        return () => clearTimeout(timer)
    }, [open, datalist])

    return <Table className="w-full">
        <TableHeader>
            <TableRow>
                <TableHead className="w-[200px]">机器</TableHead>
                <TableHead>GPU序号</TableHead>
                <TableHead>GPU-ID</TableHead>
                <TableHead>总显存</TableHead>
                <TableHead>空余显存</TableHead>
                <TableHead>GPU利用率</TableHead>
            </TableRow>
        </TableHeader>
        <TableBody>
            {datalist.map((el) => (
                <TableRow key={el.gpu_id}>
                    <TableCell>{el.server}</TableCell>
                    <TableCell>{el.gpu_uuid}</TableCell>
                    <TableCell>{el.gpu_id}</TableCell>
                    <TableCell>{el.gpu_total_mem}</TableCell>
                    <TableCell>{el.gpu_used_mem}</TableCell>
                    <TableCell>{el.gpu_utility * 100}%</TableCell>
                </TableRow>
            ))}
        </TableBody>
    </Table>
};
