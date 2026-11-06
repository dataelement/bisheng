import { Pagination, Tooltip as SharedTooltip, TooltipProvider as SharedTooltipProvider } from '@bisheng/ui';
import { SearchInput } from '@bisheng/ui';
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";

import { getGroupFlowsApi, getDepartmentFlowsApi } from "@/controllers/API/pro";
import { useTable } from "@/util/hook";
import { CircleHelp } from "lucide-react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { FlowRadio } from "./FlowRadio";

type FlowControlProps = {
    entityId: number
    entityType: 'group' | 'department'
    type: number
    onChange: (vals: any[]) => void
}

export function FlowControl({ entityId, entityType, type, onChange }: FlowControlProps) {
    const { t } = useTranslation()
    const paginationLocale = usePaginationLocale();
    const map: Record<number, { name: string; label: string; placeholder: string }> = {
        3: { name: t('build.assistantName'), label: t('system.AssistantFlowCtrl'), placeholder: t('system.assistantName') },
        2: { name: t('skills.skillName'), label: t('system.SkillFlowCtrl'), placeholder: t('skills.skillName') },
        5: { name: t('build.workFlowName'), label: t('system.flowCtrl'), placeholder: t('build.workFlowName') },
    }
    const { name, label, placeholder } = map[type]

    const fetchFn = entityType === 'department' ? getDepartmentFlowsApi : getGroupFlowsApi

    const { page, pageSize, data, total, setPage, search, refreshData } = useTable({ pageSize: 10 }, (params) =>
        fetchFn(params.page, params.pageSize, String(type), entityId, params.keyword)
    )

    const itemsRef = useRef<any[]>([])
    const handleChange = (value: number, id: string) => {
        const item = itemsRef.current.find(item => item.resource_id === id)
        if (item) {
            item.resource_limit = value
        } else {
            itemsRef.current.push({
                resource_id: id,
                [entityType === 'department' ? 'department_id' : 'group_id']: entityId,
                resource_limit: value
            })
        }
        refreshData((item: any) => item.id === id, { limit: value })
        onChange(itemsRef.current)
    }

    const searchEndRef = useRef(false)
    const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
        searchEndRef.current = true
        search(e.target.value)
    }

    if (!searchEndRef.current && !data.length) return null

    return <>
        <div className="flex items-center mb-4 justify-between">
            <div className="flex items-center space-x-2">
                <p className="text-xl font-bold">{label}</p>
                <SharedTooltipProvider ><SharedTooltip  content={<><p>{t('system.iconHover')}</p></>} ><button type="button" ><CircleHelp className="w-4 h-4" /></button></SharedTooltip></SharedTooltipProvider>
            </div>
            <SearchInput placeholder={placeholder} onChange={handleSearch} />
        </div>
        <div className="rounded-[5px]">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[150px]">{name}</TableHead>
                        <TableHead className="w-[100px]">{t('system.createdBy')}</TableHead>
                        <TableHead className="w-[380px]">{t('system.flowCtrlStrategy')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {data.map((i: any) => (<TableRow key={i.id}>
                        <TableCell className="break-all">{i.name}</TableCell>
                        <TableCell className="break-all">{i.user_name}</TableCell>
                        <TableCell className="pt-4">
                            <FlowRadio limit={i.limit} onChange={(val) => handleChange(val, i.id)} />
                        </TableCell>
                    </TableRow>))}
                </TableBody>
            </Table>
            <Pagination locale={paginationLocale} className="m-0 mt-4 w-auto justify-end"
                current={page} pageSize={pageSize} total={total}
                onChange={setPage}
            />
        </div>
    </>
}
