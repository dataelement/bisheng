import FlowRadio from "@/components/bs-ui/radio/flowRadio";
import { Table, TableHead, TableHeader, TableRow, TableCell, TableBody } from "@/components/bs-ui/table";
import { useTranslation } from "react-i18next";

export default function FlowControl({name}) {
    const { t } = useTranslation()
    const flag = true
    return <>
        <div className="!bg-[whitesmoke] rounded-[5px]">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>{name}</TableHead>
                        <TableHead>{t('system.createdBy')}</TableHead>
                        <TableHead className="flex justify-evenly items-center">{t('system.flowCtrlStrategy')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell>助手一发的啥可</TableCell>
                        <TableCell>用户X发货时间看</TableCell>
                        <TableCell className="flex justify-evenly items-center pt-[15px]">
                            <FlowRadio limit={flag} onChange={() => console.log('djsal')}></FlowRadio>
                        </TableCell>
                    </TableRow>
                    <TableRow>
                        <TableCell>助手一发的啥可</TableCell>
                        <TableCell>用户X发货时间看</TableCell>
                        <TableCell className="flex justify-evenly items-center pt-[15px]">
                            <FlowRadio limit={flag} onChange={() => console.log('djsal')}></FlowRadio>
                        </TableCell>
                    </TableRow>
                    <TableRow>
                        <TableCell>助手一发的啥可</TableCell>
                        <TableCell>用户X发货时间看</TableCell>
                        <TableCell className="flex justify-evenly items-center pt-[15px]">
                            <FlowRadio limit={flag} onChange={() => console.log('djsal')}></FlowRadio>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
        </div>
    </>
}