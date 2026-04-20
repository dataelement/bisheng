import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { FlowControl } from "@/components/Pro/FlowControl";
import { FlowRadio } from "@/components/Pro/FlowRadio";
import { getDepartmentLimitDetailApi, saveDepartmentLimitApi } from "@/controllers/API/pro";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { DepartmentTreeNode } from "@/types/api/department";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

type Props = {
    dept: DepartmentTreeNode
}

export function DepartmentTrafficControl({ dept }: Props) {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [deptLimit, setDeptLimit] = useState(0)
    const assistantRef = useRef<any[]>([])
    const skillRef = useRef<any[]>([])
    const workFlowsRef = useRef<any[]>([])

    useEffect(() => {
        // Load existing limit config
        captureAndAlertRequestErrorHoc(getDepartmentLimitDetailApi(dept.id)).then((res) => {
            if (res) {
                setDeptLimit(res.dept_limit ?? 0)
            }
        })
        // Reset resource refs on dept change
        assistantRef.current = []
        skillRef.current = []
        workFlowsRef.current = []
    }, [dept.id])

    const handleSave = async () => {
        try {
            await saveDepartmentLimitApi({
                departmentId: dept.id,
                deptLimit,
                assistant: assistantRef.current,
                skill: skillRef.current,
                workFlows: workFlowsRef.current
            })
            toast({ title: t('prompt'), description: t('save') + t('success'), variant: 'success' })
        } catch {
            toast({ title: t('prompt'), description: t('save') + t('failed'), variant: 'error' })
        }
    }

    return (
        <div className="space-y-8 pb-20">
            <div>
                <p className="text-xl font-bold mb-4">{t('bs:department.deptFlowControl')}</p>
                <FlowRadio limit={deptLimit} onChange={setDeptLimit} />
            </div>

            <FlowControl
                entityId={dept.id}
                entityType="department"
                type={3}
                onChange={(vals) => { assistantRef.current = vals }}
            />

            <FlowControl
                entityId={dept.id}
                entityType="department"
                type={2}
                onChange={(vals) => { skillRef.current = vals }}
            />

            <FlowControl
                entityId={dept.id}
                entityType="department"
                type={5}
                onChange={(vals) => { workFlowsRef.current = vals }}
            />

            <div className="flex justify-center gap-4 pt-4">
                <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
            </div>
        </div>
    )
}
