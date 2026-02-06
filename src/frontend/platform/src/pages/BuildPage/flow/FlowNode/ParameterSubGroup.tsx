import { WorkflowNode } from "@/types/flow";
import GroupInputFile from "./component/GroupInputFile";
import Parameter from "./Parameter";
import { useTranslation } from "react-i18next";
import { Switch } from "@/components/bs-ui/switch";
import { useEffect, useMemo, useRef, useState } from "react";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";

type category = WorkflowNode['group_params'][number]
interface Props {
    nodeId: string,
    node: WorkflowNode,
    cate: category,
    tab?: string,
    onOutPutChange: (key: string, value: any) => void
    onStatusChange: (key: string, obj: any) => void
    onVarEvent: (key: string, obj: any) => void
    onAddSysPrompt: (type: string) => void
    onFouceUpdate: () => void
}

export default function ParameterSubGroup({ tab, cate, ...props }: Props) {
    const groupTab = cate.params[0].tab
    if (groupTab && groupTab !== tab) return null

    if (cate.groupKey === 'inputfile') return <GroupInputFile cate={cate} {...props} />

    return <CustomGroup cate={cate} {...props} />
};



const CustomGroup = ({ nodeId, node, cate, tab,
    onOutPutChange, onAddSysPrompt, onStatusChange, onVarEvent, onFouceUpdate
}: Props) => {
    const { t } = useTranslation('flow')

    const titleItem = useMemo(() => cate.params.find(item => item.groupTitle), [cate.params])
    const [open, setOpen] = useState(titleItem.value)
    const validatesCallbackRef = useRef({})
    // Intercept Node Verification
    useEffect(() => {
        if (!validatesCallbackRef.current) return
        Object.keys(validatesCallbackRef.current).forEach(key => {
            if (validatesCallbackRef.current[key]) {
                const cacheCallback = validatesCallbackRef.current[key]
                onStatusChange(key, { param: cacheCallback.param, validate: open ? cacheCallback.validate : () => false })
            }
        })
    }, [open])
    return <div className="px-4 py-2 border-t">
        <div className="mt-2 mb-3 flex justify-between items-center">
            <div className="flex gap-1 items-center">
                <p className='text-sm font-bold'>{t(`node.${node.type}.${titleItem.key}.label`)}</p>
                {titleItem.help && <QuestionTooltip content={t(`node.${node.type}.${titleItem.key}.help`)} ></QuestionTooltip>}
            </div>
            <Switch
                className=""
                checked={open}
                onCheckedChange={(checked) => {
                    titleItem.value = checked
                    setOpen(checked)
                }}
            />
        </div>
        <div className={!open && 'hidden'}>
            {
                cate.params.map(item => <Parameter
                    nodeId={nodeId}
                    node={node}
                    key={item.key}
                    item={item}
                    onOutPutChange={onOutPutChange}
                    onStatusChange={(key, obj) => {
                        validatesCallbackRef.current[key] = obj
                    }}
                    onVarEvent={onVarEvent}
                    onFouceUpdate={onFouceUpdate}
                    onAddSysPrompt={onAddSysPrompt}
                />)
            }
        </div>
    </div>
}