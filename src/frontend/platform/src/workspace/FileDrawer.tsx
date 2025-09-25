"use client"

import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet"
import { sopApi } from "@/controllers/API/linsight"
import { Download, Eye } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import FileIcon from "./FileIcon"


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
}

export default function TaskFiles({ title, files, isOpen, onOpenChange, downloadFile, onPreview }: FileDrawerProps) {
    const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set())
    const [isDownloading, setIsDownloading] = useState(false)
    const { t: localize } = useTranslation();

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
        if (checked) {
            newSelected.add(fileId)
        } else {
            newSelected.delete(fileId)
        }
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
        setTimeout(() => {
            setIsDownloading(false)
        }, 2000);
    }

    const isAllSelected = selectedFiles.size === files.length && files.length > 0
    const isIndeterminate = selectedFiles.size > 0 && selectedFiles.size < files.length

    return (
        <Sheet open={isOpen} onOpenChange={onOpenChange}>
            <SheetContent className="w-[600px] sm:max-w-[600px] p-4">
                <SheetHeader className="">
                    <div className="flex items-center justify-between">
                        <SheetTitle>{localize('com_sop_view_all_files')}</SheetTitle>
                    </div>

                    {/* 全选和批量下载控制栏 */}
                    <div className="flex items-center justify-between pt-4 h-10">
                        <div className="flex items-center space-x-2">
                            <Checkbox
                                id="select-all"
                                checked={isAllSelected}
                                onCheckedChange={handleSelectAll}
                                className="rounded-full"
                                ref={(ref) => {
                                    if (ref) {
                                        ref.indeterminate = isIndeterminate
                                    }
                                }}
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
                        <div key={file.file_id} className="group flex items-center space-x-3 p-3 rounded-lg hover:bg-gray-50">
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

                            <div className="flex items-center space-x-2 group-hover:visible invisible">
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => {
                                        if (file.file_name.split('.').pop() === 'html') {
                                            return window.open(`${__APP_ENV__.BASE_URL}/html?url=${encodeURIComponent(file.file_url)}`, '_blank')
                                        }
                                        onPreview?.(file.file_id)
                                    }}
                                >
                                    <Eye className="h-4 w-4 text-gray-500" />
                                </Button>

                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => downloadFile(file)}
                                >
                                    <Download className="h-4 w-4 text-gray-500" />
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            </SheetContent>
        </Sheet>
    )
}
