"use client"

import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet"
import { sopApi } from "@/controllers/API/linsight"
import { CheckCircle, CircleX, Download, Eye, Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import FileIcon from "./FileIcon"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/bs-ui/tooltip"

interface FileItem {
    file_id: string
    file_md5: string
    file_name: string
    file_path: string
    file_url: string
}

interface FileDrawerProps {
    title: string
    files: FileItem[]
    isOpen: boolean
    onOpenChange: (open: boolean) => void
    downloadFile: (file: any) => void
    onBatchDownload?: (urls: string[]) => Promise<void>
    onPreview?: (fileId: string) => void
    handleExportOther: (e: React.MouseEvent, type: string, file: FileItem) => void
    exportState: {
        loading: boolean
        success: boolean
        error: boolean
        title: string
    }
}

export default function TaskFiles({ title, files, isOpen, onOpenChange, downloadFile, onPreview, handleExportOther, exportState }: FileDrawerProps) {
    const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set())
    const [isDownloading, setIsDownloading] = useState(false)
    const { t: localize } = useTranslation();
    const [hoveredId, setHoveredId] = useState<string | null>(null)
    const [tooltipOpenIds, setTooltipOpenIds] = useState<Set<string>>(new Set())

    // 获取文件扩展名
    const getFileExtension = (fileName: string): string => {
        const lastDot = fileName.lastIndexOf(".")
        return lastDot !== -1 ? fileName.substring(lastDot + 1) : ""
    }

    // 处理全选/取消全选
    const handleSelectAll = (checked: boolean) => {
        if (checked) {
            setSelectedFiles(new Set(files.map((file) => file.file_id)))
        } else {
            setSelectedFiles(new Set())
        }
    }

    // 处理单个文件选择
    const handleFileSelect = (fileId: string, checked: boolean) => {
        const newSelected = new Set(selectedFiles)
        checked ? newSelected.add(fileId) : newSelected.delete(fileId)
        setSelectedFiles(newSelected)
    }

    // 处理批量下载
    const handleBatchDownload = async () => {
        if (selectedFiles.size === 0) return
        setIsDownloading(true)
        const downloadFiles = files.filter((file) => selectedFiles.has(file.file_id)).map((file) => ({
            file_url: file.file_url,
            file_name: file.file_name
        }))
        sopApi.batchDownload({ fileName: (title || 'downloadFile') + '.zip', files: downloadFiles })
        setTimeout(() => setIsDownloading(false), 2000);
    }

    const isAllSelected = selectedFiles.size === files.length && files.length > 0
    const isIndeterminate = selectedFiles.size > 0 && selectedFiles.size < files.length

    // 图标显示条件：鼠标移入 或 弹窗打开
    const shouldShowIcon = (fileId: string) => {
        return hoveredId === fileId || tooltipOpenIds.has(fileId)
    }

    // 弹窗关闭时重置状态
    useEffect(() => {
        if (!isOpen) {
            setTooltipOpenIds(new Set())
            setHoveredId(null)
        }
    }, [isOpen])

    return (
        <Sheet open={isOpen} onOpenChange={onOpenChange}>
            <SheetContent className="w-[600px] sm:max-w-[600px] p-4 ">
                {exportState.loading && (
                    <div className="fixed top-24 right-5 flex items-center gap-2 bg-white p-3 rounded-lg shadow-md z-500">
                        <Loader2 className="size-5 animate-spin text-blue-500" />
                        <div className="text-sm text-gray-800">{exportState.title}&nbsp;正在导出，请稍后...&nbsp;&nbsp;</div>
                    </div>
                )}
                {exportState.success && (
                    <div className="fixed top-24 right-5 flex items-center gap-2 bg-white p-3 rounded-lg shadow-md z-500">
                        <CheckCircle className="size-5 text-green-500" />
                        <div className="text-sm text-gray-800">{exportState.title}&nbsp;文件下载成功</div>
                    </div>
                )}
                {exportState.error && (
                    <div className="fixed top-24 right-5 flex items-center gap-2 bg-white p-3 rounded-lg shadow-md z-500">
                        <CircleX className="size-5 text-red-500" />
                        <div className="text-sm text-gray-800">导出失败</div>
                    </div>
                )}

                <SheetHeader className="px-3">
                    <div className="flex items-center justify-between">
                        <SheetTitle>{localize('com_sop_view_all_files')}</SheetTitle>
                    </div>
                    <div className="flex items-center justify-between pt-4 h-10">
                        <div className="flex items-center space-x-2">
                            <Checkbox
                                id="select-all"
                                checked={isAllSelected}
                                onCheckedChange={handleSelectAll}
                                className="rounded-full"
                                ref={(ref) => { if (ref) ref.indeterminate = isIndeterminate }}
                            />
                            <label htmlFor="select-all" className="text-sm font-medium cursor-pointer">
                                {localize('com_sop_select_all')}
                            </label>
                        </div>
                        {selectedFiles.size > 0 && (
                            <Button
                                size="sm"
                                onClick={handleBatchDownload}
                                disabled={isDownloading}
                                className="h-8 px-3 text-xs"
                            >
                                {localize('com_sop_batch_download')} ↓
                            </Button>
                        )}
                    </div>
                </SheetHeader>

                {/* 文件列表 */}
                <div className="space-y-1 h-[calc(100vh-100px)] overflow-auto pb-10">
                    {files.map((file) => (
                        <div
                            key={file.file_id}
                            className="group flex items-center space-x-3 p-3 rounded-lg hover:bg-gray-50"
                            onMouseEnter={() => setHoveredId(file.file_id)}
                            onMouseLeave={() => setHoveredId(null)}
                        >
                            <Checkbox
                                id={`file-${file.file_id}`}
                                checked={selectedFiles.has(file.file_id)}
                                onCheckedChange={(checked) => handleFileSelect(file.file_id, checked as boolean)}
                                className="rounded-full "
                            />

                            <div className="flex items-center space-x-3 flex-1">
                                <FileIcon className='size-5 min-w-4' type={getFileExtension(file.file_name)} />
                                <span className="text-sm text-gray-900 flex-1">{file.file_name}</span>
                            </div>

                            <div className="items-center space-x-2 group-hover:opacity-100 flex opacity-0">
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    // style={{ visibility: shouldShowIcon(file.file_id) ? 'visible' : 'hidden' }}
                                    onClick={() => {
                                        if (file.file_name.split('.').pop() === 'html') {
                                            return window.open(`${__APP_ENV__.BASE_URL}/html?url=${encodeURIComponent(file.file_url)}`, '_blank')
                                        }
                                        onPreview?.(file.file_id)
                                    }}
                                >
                                    <Eye className="h-4 w-4 text-gray-500" />
                                </Button>

                                {/* 下载按钮：同时支持 hover 和 click 触发下拉窗口 */}
                                <Button
                                    variant="ghost"
                                >
                                    {String(file.file_name).toLowerCase().endsWith('.md') ? (
                                        <Tooltip
                                            open={tooltipOpenIds.has(file.file_id)}
                                            delayDuration={0}
                                            onOpenChange={(open) => {
                                                const newSet = new Set(tooltipOpenIds);
                                                open ? newSet.add(file.file_id) : newSet.delete(file.file_id);
                                                setTooltipOpenIds(newSet);
                                            }}
                                        >
                                            <TooltipTrigger asChild>
                                                <span
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        // 点击切换状态（点击后即使鼠标离开也保持打开）
                                                        const newSet = new Set(tooltipOpenIds);
                                                        if (newSet.has(file.file_id)) {
                                                            newSet.delete(file.file_id);
                                                        } else {
                                                            newSet.add(file.file_id);
                                                        }
                                                        setTooltipOpenIds(newSet);
                                                    }}
                                                >
                                                    <Download size={16} />
                                                </span>
                                            </TooltipTrigger>
                                            <TooltipContent side='bottom' align='center' className='bg-white text-gray-800 border border-gray-200'>
                                                <div className='flex flex-col gap-2'>
                                                    <div
                                                        className='flex gap-2 items-center cursor-pointer hover:bg-gray-100 rounded-md p-1'
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            downloadFile(file);
                                                            const newSet = new Set(tooltipOpenIds);
                                                            newSet.delete(file.file_id);
                                                            setTooltipOpenIds(newSet);
                                                        }}
                                                    >
                                                        <FileIcon type={'md'} className='size-5' />
                                                        <div className='w-full flex gap-2 items-center'>Markdown</div>
                                                    </div>
                                                    <div
                                                        className='flex gap-2 items-center rounded-md p-1 cursor-pointer hover:bg-gray-100'
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            handleExportOther(e, 'pdf', file);
                                                            const newSet = new Set(tooltipOpenIds);
                                                            newSet.delete(file.file_id);
                                                            setTooltipOpenIds(newSet);
                                                        }}
                                                    >
                                                        <FileIcon type={'pdf'} className='size-5' />
                                                        <div className='w-full flex gap-2 items-center'>PDF</div>
                                                    </div>
                                                    <div
                                                        className='flex gap-2 items-center rounded-md p-1 cursor-pointer hover:bg-gray-100'
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            handleExportOther(e, 'docx', file);
                                                            const newSet = new Set(tooltipOpenIds);
                                                            newSet.delete(file.file_id);
                                                            setTooltipOpenIds(newSet);
                                                        }}
                                                    >
                                                        <FileIcon type={'docx'} className='size-5' />
                                                        <div className='w-full flex gap-2 items-center'>Docx</div>
                                                    </div>
                                                </div>
                                            </TooltipContent>
                                        </Tooltip>
                                    ) : (
                                        <Download size={16} onClick={(e) => { e.stopPropagation(); downloadFile(file); }} />
                                    )}
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            </SheetContent>
        </Sheet>
    )
}