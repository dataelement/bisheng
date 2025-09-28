"use client"
import { ChevronLeft } from 'lucide-react'
import type React from "react"
import { useMemo } from "react"
import { useLocalize } from "~/hooks"
import { Button, TooltipAnchor } from "../ui"
import FileIcon from "../ui/icon/File"
import { Sheet, SheetContent, SheetHeader } from "../ui/Sheet"
import DownloadResultFileBtn from './components/DownloadResultFileBtn'
import FilePreview from "./FilePreview"

interface FileItem {
    file_id: string
    file_md5: string
    file_name: string
    file_path: string
    file_url: string
}

interface FilePreviewDrawerProps {
    // 原有方式的 props
    files?: FileItem[]
    currentFileId?: string
    onFileChange?: (fileId: string) => void
    downloadFile?: (file: any) => void

    // 新增：直接文件预览方式的 props
    directFile?: { name: string, url: string }

    // 通用 props
    isOpen: boolean
    onOpenChange: (open: boolean) => void
    onBack?: () => void
    children?: React.ReactNode
}

export default function FilePreviewDrawer({
    files,
    isOpen,
    onOpenChange,
    currentFileId,
    onFileChange,
    downloadFile,
    directFile,
    onBack,
}: FilePreviewDrawerProps) {
    const localize = useLocalize()
    // const [selectedFileId, setSelectedFileId] = useState(currentFileId || files?.[0]?.file_id || "")

    // 获取文件扩展名
    const getFileExtension = (fileName: string): string => {
        const lastDot = fileName.lastIndexOf(".")
        return lastDot !== -1 ? fileName.substring(lastDot + 1) : ""
    }

    // 处理文件切换
    const handleFileChange = (fileId: string) => {
        // setSelectedFileId(fileId)
        onFileChange?.(fileId)
    }

    // 获取当前显示的文件信息
    const currentDisplayFile = useMemo(() => {
        if (directFile) {
            return {
                file_id: 'direct-file',
                ...directFile
            }
        }

        if (files && currentFileId) {
            return files.find((file) => file.file_id === currentFileId)
        }

        return null
    }, [files, currentFileId, directFile])

    if (!isOpen) return null

    return (
        <Sheet open={isOpen} onOpenChange={onOpenChange}>
            <SheetContent className="w-[800px] sm:max-w-[800px] p-0">
                <SheetHeader className="px-6 py-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-3 flex-1">
                            {/* 返回按钮 */}
                            {onBack && (
                                <Button variant="outline" size="icon" onClick={() => onBack()} className="h-8 w-8">
                                    <ChevronLeft className="h-4 w-4" />
                                </Button>
                            )}

                            {/* 文件信息显示 */}
                            <div className="flex items-center space-x-3 flex-1">
                                <div className="flex items-center space-x-3">
                                    {currentDisplayFile && (
                                        <FileIcon
                                            type={getFileExtension(currentDisplayFile.file_name)}
                                            className="w-4 h-4"
                                        />
                                    )}
                                    <TooltipAnchor side="bottom" description={currentDisplayFile?.file_name || localize('com_sop_select_file')}>
                                        <p className="font-medium text-gray-900 truncate max-w-96">
                                            {currentDisplayFile?.file_name || localize('com_sop_select_file')}
                                        </p>
                                    </TooltipAnchor>
                                </div>

                                {/* 下载按钮 */}
                                <TooltipAnchor side="bottom" description={localize('com_ui_download')}>
                                    <DownloadResultFileBtn file={currentDisplayFile} onDownloadFile={downloadFile} />
                                    {/* <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={() => downloadFile?.(currentDisplayFile)}
                                        className="h-8 w-8"
                                        disabled={!currentDisplayFile}
                                    >
                                        <Download size={14} />
                                    </Button> */}
                                </TooltipAnchor>
                            </div>
                        </div>
                    </div>
                </SheetHeader>

                {/* 预览内容区域 */}
                <div className="flex-1 overflow-auto">
                    <FilePreview
                        files={files}
                        fileId={currentFileId}
                        currentDisplayFile={currentDisplayFile}
                    />
                </div>
            </SheetContent>
        </Sheet>
    )
}
