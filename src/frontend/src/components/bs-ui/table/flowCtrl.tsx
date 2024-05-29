import FlowRadio from "@/components/bs-ui/radio/flowRadio";
import { Table, TableHead, TableRow, TableCell, TableBody } from "@/components/ui/table";
import { useTranslation } from "react-i18next";

export default function FlowControl({name}) {
    const { t } = useTranslation()
    const flag = false
    return <>
        <div className="!bg-[whitesmoke]">
            <Table className="font-black">
                <TableRow className="border-b-0">
                    <TableHead className="text-black">{name}</TableHead>
                    <TableHead className="text-black">{t('system.createdBy')}</TableHead>
                    <TableHead className="text-black flex justify-evenly items-center">{t('system.flowCtrlStrategy')}</TableHead>
                </TableRow>
                <TableBody>
                    <TableRow className="border-b-0">
                        <TableCell></TableCell>
                        <TableCell></TableCell>
                        <TableCell className="flex justify-evenly">
                            <FlowRadio limit={flag} onChange={() => console.log('djsal')}></FlowRadio>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
        </div>
    </>
}