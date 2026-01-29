import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { WorkflowNode } from "@/types/flow"
import { useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import FileTypeSelect from "./FileTypeSelect"
import InputItem from "./InputItem"

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

export default function GroupInputFile({ nodeId, node, cate, tab,
    onOutPutChange, onAddSysPrompt, onStatusChange, onVarEvent, onFouceUpdate
}: Props) {
    const { t } = useTranslation('flow')

    const titleItem = useMemo(() => cate.params.find(item => item.groupTitle), [cate.params])
    const fileTypeItem = useMemo(() => cate.params.find(item => item.key === 'dialog_file_accept'), [cate.params])
    const sizeItem = useMemo(() => cate.params.find(item => item.key === 'dialog_files_content_size'), [cate.params])
    const [open, setOpen] = useState(titleItem.value ?? false)

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
            <FileTypeSelect
                data={fileTypeItem}
                onChange={(val) => {
                    const imageFileItem = node.group_params[0].params.find(param => {
                        if (param.key === 'dialog_image_files') return true
                    })
                    imageFileItem.hidden = val === 'file'
                }}
                i18nPrefix={`node.${node.type}.${fileTypeItem.key}.`}
            />
            ....
            <InputItem char type='number' data={sizeItem} onChange={(val) => { }} i18nPrefix={`node.${node.type}.${sizeItem.key}.`} />
        </div>
    </div>
};
