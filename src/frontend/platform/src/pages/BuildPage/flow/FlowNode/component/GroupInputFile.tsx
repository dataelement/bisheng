import { Switch } from "@/components/bs-ui/switch"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { WorkflowNode } from "@/types/flow"
import { useMemo, useState, useEffect } from "react"
import { useTranslation } from "react-i18next"
import FileTypeSelect from "./FileTypeSelect"
import InputItem from "./InputItem"
import { Label } from "@/components/bs-ui/label"
import { Badge } from "@/components/bs-ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { Check } from "lucide-react"

type category = WorkflowNode['group_params'][number]
export enum FileParseMode {
    // 不解析文件
    KeepRaw = 'keep_raw',
    // 解析文件
    ExtractText = 'extract_text'
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
    const [fileStrategy, setFileStrategy] = useState<FileParseMode>(parsemodeItem.value)
    const [selectedFileType, setSelectedFileType] = useState<any>(null)

    // 初始化
    useEffect(() => {
        // 初始化文件处理策略
        if (filePathItem && filePathItem.value && Object.keys(filePathItem.value).length > 0) {
            setFileStrategy(FileParseMode.KeepRaw)
        } else {
            setFileStrategy(FileParseMode.ExtractText)
        }

        // 初始化文件类型
        if (fileTypeItem?.value) {
            setSelectedFileType(fileTypeItem.value)
        }
    }, [filePathItem, fileTypeItem])

    // 处理文件策略变化
    const handleStrategyChange = (value: FileParseMode.ExtractText | FileParseMode.KeepRaw) => {
        setFileStrategy(value)

        // 更新文件处理策略参数
        if (parsemodeItem) {
            parsemodeItem.value = value;
        }

        // 重置相关变量值
        if (value === FileParseMode.ExtractText) {
            // 解析模式：启用解析结果长度配置
            if (sizeItem) {
                sizeItem.value = sizeItem.value || 1000;
            }
            // 清空文件路径变量
            if (filePathItem) {
                filePathItem.value = filePathItem.value || {};
            }
            // 清空图片文件变量
            if (imageFileItem) {
                imageFileItem.value = imageFileItem.value || {};
            }
        } else {
            // 原始文件模式：设置文件路径变量
            if (filePathItem) {
                filePathItem.value = filePathItem.value || {};
            }
            // 设置图片文件变量（如果文件类型不是文档）
            if (imageFileItem && selectedFileType !== 'file') {
                imageFileItem.value = imageFileItem.value || {};
            }
            // 禁用解析结果长度配置
            if (sizeItem) {
                sizeItem.value = sizeItem.value || 0;
            }
        }
        if (onFouceUpdate) {
            onFouceUpdate();
        }
    }

    // 处理文件类型变化
    const handleFileTypeChange = (val: any) => {
        setSelectedFileType(val)

        // 更新文件类型参数
        if (fileTypeItem) {
            fileTypeItem.value = val;
        }

        // 更新图片文件变量隐藏状态
        if (imageFileItem) {
            imageFileItem.hidden = val === 'file';

            // 如果切换到文档类型且当前是原始文件模式，清空图片文件变量
            if (val === 'file' && fileStrategy === FileParseMode.KeepRaw) {
                imageFileItem.value = {};
            }
            // 如果切换到非文档类型且当前是原始文件模式，设置图片文件变量
            if (val !== 'file' && fileStrategy === FileParseMode.KeepRaw && !imageFileItem.value) {
                imageFileItem.value = {};
            }
        }

        if (onFouceUpdate) {
            onFouceUpdate();
        }
    }

    // 处理开关变化
    const handleSwitchToggle = (checked: boolean) => {
        if (titleItem) {
            titleItem.value = checked;
        }
        setOpen(checked);

        if (onFouceUpdate) {
            onFouceUpdate();
        }
    }

    return <div className="px-4 py-2 border-t">
        <div className="mt-2 mb-3 flex justify-between items-center">
            <div className="flex gap-1 items-center">
                <p className='text-sm font-bold'>{t(`node.${node.type}.${titleItem.key}.label`)}</p>
                {titleItem.help && <QuestionTooltip content={t(`node.${node.type}.${titleItem.key}.help`)} ></QuestionTooltip>}
            </div>
            <Switch
                className=""
                checked={open}
                onCheckedChange={handleSwitchToggle}
            />
        </div>

        {/* 只修改开关展开后的内容 */}
        <div className={!open && 'hidden'}>
            {/* 上传文件类型 - 始终显示 */}
            <div className="mb-4">
                <FileTypeSelect
                    data={fileTypeItem}
                    onChange={handleFileTypeChange}
                    i18nPrefix={`node.${node.type}.${fileTypeItem?.key}.`}
                />
            </div>

            {/* 文件处理策略 - 始终显示 */}
            <div className="mb-4">
                <div className="node-item flex gap-4 items-center mb-4">
                    <Label className="bisheng-label min-w-28 flex items-center gap-1">
                        {t("fileProcessingStrategy")}
                        <QuestionTooltip
                            content={
                                <div className="whitespace-pre-line">
                                    {t("fileProcessingStrategyTip")}
                                </div>
                            }
                        />
                    </Label>
                    <Select value={fileStrategy} onValueChange={handleStrategyChange}>
                        <SelectTrigger className="w-full">
                            {fileStrategy === FileParseMode.ExtractText ? t("parseFile") : t("notParse")}
                        </SelectTrigger>
                        <SelectContent className="">
                            {[
                                { value: FileParseMode.ExtractText, label: t("parseFile") },
                                { value: FileParseMode.KeepRaw, label: t("notParse") }
                            ].map((option) => (
                                <div
                                    key={option.value}
                                    data-focus={fileStrategy === option.value}
                                    className="flex justify-between w-full select-none items-center mb-1 last:mb-0 rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                                    onClick={() => handleStrategyChange(option.value as FileParseMode.ExtractText | FileParseMode.KeepRaw)}
                                >
                                    <span className="w-64 overflow-hidden text-ellipsis">
                                        {option.label}
                                    </span>
                                    {fileStrategy === option.value && <Check className="h-4 w-4" />}
                                </div>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            </div>

            {/* 动态输出变量 */}
            <div className="space-y-3">
                {fileStrategy === FileParseMode.ExtractText ? (
                    // 情况3：选择解析 - 显示解析相关配置
                    <>
                        {sizeItem && (
                            <InputItem
                                char
                                type='number'
                                data={sizeItem}
                                onChange={(val) => {
                                    sizeItem.value = val;
                                    // onStatusChange(sizeItem.key, { param: sizeItem });
                                    if (onFouceUpdate) onFouceUpdate();
                                }}
                                i18nPrefix={`node.${node.type}.${sizeItem.key}.`}
                            />
                        )}

                        <div className="flex justify-between items-center">
                            <Label className="bisheng-label">
                                {t("fileParseResult")}
                            </Label>
                            <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">
                                dialog_files_content
                            </Badge>
                        </div>
                    </>
                ) : (
                    // 选择不解析 - 根据文件类型显示不同变量
                    <>
                        {/* 图片文件 - 仅当文件类型不是文档时显示 */}
                        {selectedFileType !== 'file' && imageFileItem && (
                            <div className="flex justify-between items-center">
                                <div className="flex items-center gap-1">
                                    <Label className="bisheng-label">
                                        {t(`node.${node.type}.${imageFileItem.key}.label`)}
                                    </Label>
                                    <QuestionTooltip content={t("extractImages")} />
                                </div>
                                <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">
                                    dialog_image_files
                                </Badge>
                            </div>
                        )}

                        {/* 文件路径 - 始终显示 */}
                        <div className="flex justify-between items-center">
                            <div className="flex items-center gap-1">
                                <Label className="bisheng-label">
                                    {t("filePath")}
                                </Label>
                                <QuestionTooltip content={t("storeUploadFiles")} />
                            </div>
                            <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">
                                dialog_file_paths
                            </Badge>
                        </div>
                    </>
                )}
            </div>
        </div>
    </div>
}