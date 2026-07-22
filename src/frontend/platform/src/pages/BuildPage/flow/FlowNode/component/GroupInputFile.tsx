import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { WorkflowNode } from "@/types/flow"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import FileTypeSelect from "./FileTypeSelect"
import InputItem from "./InputItem"
import { Label } from "@/components/bs-ui/label"
import { Badge } from "@/components/bs-ui/badge"
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select"
import { Check } from "lucide-react"

type category = WorkflowNode['group_params'][number]

// F038 (单选 + 输出变量联动): dialog strategy is a single choice over the whole
// upload. Variables follow the unified rule (path always, image by upload type,
// content when parsing). No per-kind grouping / map.
export enum FileParseMode {
    // 解析文件内容
    ExtractText = 'extract_text',
    // 不解析（原始文件）
    KeepRaw = 'keep_raw',
}

// Legacy / superseded values (single string already fine; the old {doc,image}
// map is normalized to a single representative value for backward display).
const toMode = (value: any): FileParseMode => {
    if (typeof value === 'string' && value) return value as FileParseMode
    if (Array.isArray(value) && value.length) return value[0] as FileParseMode
    if (value && typeof value === 'object') {
        const first = value.doc || value.image || Object.values(value)[0]
        if (first) return first as FileParseMode
    }
    return FileParseMode.ExtractText
}

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
    const filePathItem = useMemo(() => cate.params.find(item => item.key === 'dialog_file_paths'), [cate.params])
    const imageFileItem = useMemo(() => cate.params.find(item => item.key === 'dialog_image_files'), [cate.params])
    const parsemodeItem = useMemo(() => cate.params.find(item => item.key === 'file_parse_mode'), [cate.params])

    const [open, setOpen] = useState(titleItem.value ?? false)
    const [selectedFileType, setSelectedFileType] = useState<string>(fileTypeItem?.value ?? 'all')
    const [mode, setMode] = useState<FileParseMode>(() => toMode(parsemodeItem?.value))

    useEffect(() => {
        setSelectedFileType(fileTypeItem?.value ?? 'all')
        setMode(toMode(parsemodeItem?.value))
    }, [fileTypeItem, parsemodeItem])

    // Unified variable rule: path always; image when upload type allows; content when parsing.
    const isExtract = mode === FileParseMode.ExtractText
    const showImage = selectedFileType !== 'file' // 'file' = document-only

    const handleStrategyChange = (value: FileParseMode) => {
        setMode(value)
        if (parsemodeItem) parsemodeItem.value = value // single string
        if (sizeItem) sizeItem.value = sizeItem.value || 15000
        if (filePathItem) filePathItem.value = filePathItem.value || {}
        if (imageFileItem) imageFileItem.value = imageFileItem.value || {}
        onFouceUpdate?.()
    }

    const handleFileTypeChange = (val: string) => {
        setSelectedFileType(val)
        if (fileTypeItem) fileTypeItem.value = val
        if (imageFileItem) {
            imageFileItem.hidden = val === 'file'
            if (val === 'file') imageFileItem.value = {}
        }
        onFouceUpdate?.()
    }

    const handleSwitchToggle = (checked: boolean) => {
        if (titleItem) titleItem.value = checked
        setOpen(checked)
        onFouceUpdate?.()
    }

    const strategyOptions = [
        { value: FileParseMode.ExtractText, label: t("parseFile") },
        { value: FileParseMode.KeepRaw, label: t("notParse") },
    ]

    return <div className="px-4 py-2 border-t">
        <div className="mt-2 mb-3 flex justify-between items-center">
            <div className="flex gap-1 items-center">
                <p className='text-sm font-bold'>{t(`node.${node.type}.${titleItem.key}.label`)}</p>
                {titleItem.help && <QuestionTooltip content={t(`node.${node.type}.${titleItem.key}.help`)} ></QuestionTooltip>}
            </div>
            <Switch checked={open} onCheckedChange={handleSwitchToggle} />
        </div>

        <div className={!open && 'hidden'}>
            {/* 上传文件类型 */}
            <div className="mb-4">
                <FileTypeSelect
                    data={fileTypeItem}
                    onChange={handleFileTypeChange}
                    i18nPrefix={`node.${node.type}.${fileTypeItem?.key}.`}
                />
            </div>

            {/* 文件处理策略 - 单选 */}
            <div className="node-item flex gap-4 items-center mb-4">
                <Label className="bisheng-label min-w-28 flex items-center gap-1">
                    {t("fileProcessingStrategy")}
                    <QuestionTooltip
                        content={<div className="whitespace-pre-line">{t("fileProcessingStrategyTip")}</div>}
                    />
                </Label>
                <Select value={mode} onValueChange={(v) => handleStrategyChange(v as FileParseMode)}>
                    <SelectTrigger className="w-full">
                        {isExtract ? t("parseFile") : t("notParse")}
                    </SelectTrigger>
                    <SelectContent className="">
                        {strategyOptions.map((option) => (
                            <div
                                key={option.value}
                                data-focus={mode === option.value}
                                className="flex justify-between w-full select-none items-center mb-1 last:mb-0 rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700"
                                onClick={() => handleStrategyChange(option.value)}
                            >
                                <span className="w-64 overflow-hidden text-ellipsis">{option.label}</span>
                                {mode === option.value && <Check className="h-4 w-4" />}
                            </div>
                        ))}
                    </SelectContent>
                </Select>
            </div>

            {/* 动态输出变量 - 统一规则联动 */}
            <div className="space-y-3">
                {isExtract && (
                    <>
                        {sizeItem && (
                            <InputItem
                                char
                                type='number'
                                data={sizeItem}
                                onChange={(val) => {
                                    sizeItem.value = val
                                    onFouceUpdate?.()
                                }}
                                i18nPrefix={`node.${node.type}.${sizeItem.key}.`}
                            />
                        )}
                        <div className="flex justify-between items-center">
                            <Label className="bisheng-label">{t("fileParseResult")}</Label>
                            <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">dialog_files_content</Badge>
                        </div>
                    </>
                )}

                {showImage && imageFileItem && (
                    <div className="flex justify-between items-center">
                        <div className="flex items-center gap-1">
                            <Label className="bisheng-label">{t(`node.${node.type}.${imageFileItem.key}.label`)}</Label>
                            <QuestionTooltip content={t("extractImages")} />
                        </div>
                        <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">dialog_image_files</Badge>
                    </div>
                )}

                {/* 文件路径 - 恒展示 */}
                <div className="flex justify-between items-center">
                    <div className="flex items-center gap-1">
                        <Label className="bisheng-label">{t("filePath")}</Label>
                        <QuestionTooltip content={t("storeUploadFiles")} />
                    </div>
                    <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">dialog_file_paths</Badge>
                </div>
            </div>
        </div>
    </div>
}
