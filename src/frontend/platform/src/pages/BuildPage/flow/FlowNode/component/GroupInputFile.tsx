import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { WorkflowNode } from "@/types/flow"
import { useMemo, useState, useEffect } from "react"
import { useTranslation } from "react-i18next"
import FileTypeSelect from "./FileTypeSelect"
import InputItem from "./InputItem"
import { Label } from "@/components/bs-ui/label"
import { Badge } from "@/components/bs-ui/badge"
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select"
import { Check } from "lucide-react"

type category = WorkflowNode['group_params'][number]
export enum FileParseMode {
    // 不解析文件
    KeepRaw = 'keep_raw',
    // 解析文件
    ExtractText = 'extract_text'
}

// Per-file-type group (F038). Dialog strategy is grouped by file kind; each group is single-select.
type FileKind = 'doc' | 'image'
// dialog_file_accept value -> which groups are visible. 'file' = document-only.
const KINDS_BY_FILE_TYPE: Record<string, FileKind[]> = {
    all: ['doc', 'image'],
    file: ['doc'],
    image: ['image'],
}
const visibleKinds = (fileType: string): FileKind[] => KINDS_BY_FILE_TYPE[fileType] || ['doc']

// Normalize file_parse_mode (legacy string / map) into a map covering the visible kinds.
const toModeMap = (value: any, fileType: string): Record<FileKind, FileParseMode> => {
    const kinds = visibleKinds(fileType)
    const pick = (k: FileKind): FileParseMode => {
        if (typeof value === 'string' && value) return value as FileParseMode
        if (value && typeof value === 'object' && value[k]) return value[k] as FileParseMode
        return FileParseMode.ExtractText
    }
    return kinds.reduce((acc, k) => ({ ...acc, [k]: pick(k) }), {} as Record<FileKind, FileParseMode>)
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
    // Per-kind strategy map; only the visible kinds are meaningful / persisted.
    const [modeMap, setModeMap] = useState<Record<FileKind, FileParseMode>>(
        () => toModeMap(parsemodeItem?.value, fileTypeItem?.value ?? 'all')
    )

    useEffect(() => {
        const fileType = fileTypeItem?.value ?? 'all'
        setSelectedFileType(fileType)
        setModeMap(toModeMap(parsemodeItem?.value, fileType))
    }, [fileTypeItem, parsemodeItem])

    // Persist only the visible kinds into the node param (keeps the map clean on type switch).
    const persistModeMap = (map: Record<FileKind, FileParseMode>, fileType: string) => {
        const kinds = visibleKinds(fileType)
        const cleaned = kinds.reduce((acc, k) => ({ ...acc, [k]: map[k] }), {} as Record<string, FileParseMode>)
        if (parsemodeItem) parsemodeItem.value = cleaned
    }

    // Union-based visibility of output variables across the visible groups.
    const kinds = visibleKinds(selectedFileType)
    const anyExtract = kinds.some(k => modeMap[k] === FileParseMode.ExtractText)
    const anyKeepRaw = kinds.some(k => modeMap[k] === FileParseMode.KeepRaw)
    const imageKeepRaw = kinds.includes('image') && modeMap.image === FileParseMode.KeepRaw

    const handleStrategyChange = (kind: FileKind, value: FileParseMode) => {
        const next = { ...modeMap, [kind]: value }
        setModeMap(next)
        persistModeMap(next, selectedFileType)
        if (sizeItem) sizeItem.value = sizeItem.value || 15000
        if (filePathItem) filePathItem.value = filePathItem.value || {}
        if (imageFileItem) imageFileItem.value = imageFileItem.value || {}
        onFouceUpdate?.()
    }

    const handleFileTypeChange = (val: string) => {
        setSelectedFileType(val)
        if (fileTypeItem) fileTypeItem.value = val
        // Re-derive the map for the newly visible kinds and prune hidden ones from storage.
        const next = toModeMap(parsemodeItem?.value, val)
        setModeMap(next)
        persistModeMap(next, val)
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

    const renderStrategySelect = (kind: FileKind) => {
        const value = modeMap[kind]
        const labelKey = kind === 'doc' ? 'docFileProcessingStrategy' : 'imageFileProcessingStrategy'
        return (
            <div key={kind} className="node-item flex gap-4 items-center mb-4">
                <Label className="bisheng-label min-w-28 flex items-center gap-1">
                    {t(labelKey)}
                    <QuestionTooltip
                        content={<div className="whitespace-pre-line">{t("fileProcessingStrategyTip")}</div>}
                    />
                </Label>
                <Select value={value} onValueChange={(v) => handleStrategyChange(kind, v as FileParseMode)}>
                    <SelectTrigger className="w-full">
                        {value === FileParseMode.ExtractText ? t("parseFile") : t("notParse")}
                    </SelectTrigger>
                    <SelectContent className="">
                        {[
                            { value: FileParseMode.ExtractText, label: t("parseFile") },
                            { value: FileParseMode.KeepRaw, label: t("notParse") }
                        ].map((option) => (
                            <div
                                key={option.value}
                                data-focus={value === option.value}
                                className="flex justify-between w-full select-none items-center mb-1 last:mb-0 rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                                onClick={() => handleStrategyChange(kind, option.value)}
                            >
                                <span className="w-64 overflow-hidden text-ellipsis">{option.label}</span>
                                {value === option.value && <Check className="h-4 w-4" />}
                            </div>
                        ))}
                    </SelectContent>
                </Select>
            </div>
        )
    }

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

            {/* 文件处理策略 - 按文件类型分组 */}
            <div className="mb-4">
                {kinds.map(renderStrategySelect)}
            </div>

            {/* 动态输出变量 - 按各组并集展示 */}
            <div className="space-y-3">
                {anyExtract && (
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

                {imageKeepRaw && imageFileItem && (
                    <div className="flex justify-between items-center">
                        <div className="flex items-center gap-1">
                            <Label className="bisheng-label">{t(`node.${node.type}.${imageFileItem.key}.label`)}</Label>
                            <QuestionTooltip content={t("extractImages")} />
                        </div>
                        <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">dialog_image_files</Badge>
                    </div>
                )}

                {anyKeepRaw && (
                    <div className="flex justify-between items-center">
                        <div className="flex items-center gap-1">
                            <Label className="bisheng-label">{t("filePath")}</Label>
                            <QuestionTooltip content={t("storeUploadFiles")} />
                        </div>
                        <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">dialog_file_paths</Badge>
                    </div>
                )}
            </div>
        </div>
    </div>
}
