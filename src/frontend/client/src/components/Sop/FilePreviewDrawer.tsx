"use client"

import type React from "react"

import { useState } from "react"
import { ChevronLeft, Download, X } from "lucide-react"
import { Button, TooltipAnchor } from "../ui"
import FileIcon from "../ui/icon/File"
import { Sheet, SheetContent, SheetHeader } from "../ui/Sheet"
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../ui/Select"
import FilePreview from "./FilePreview"

interface FileItem {
    file_id: string
    file_md5: string
    file_name: string
    file_path: string
    file_url: string
}

interface FilePreviewDrawerProps {
    files: FileItem[]
    isOpen: boolean
    onOpenChange: (open: boolean) => void
    currentFileId?: string
    onFileChange?: (fileId: string) => void
    onBack?: (b) => void
    downloadFile: (file: any) => void
    children?: React.ReactNode // 预览内容组件
}

export default function FilePreviewDrawer({
    files,
    isOpen,
    onOpenChange,
    currentFileId,
    onFileChange,
    downloadFile,
    onBack,
}: FilePreviewDrawerProps) {
    const [selectedFileId, setSelectedFileId] = useState(currentFileId || files[0]?.file_id || "")

    // 获取文件扩展名
    const getFileExtension = (fileName: string): string => {
        const lastDot = fileName.lastIndexOf(".")
        return lastDot !== -1 ? fileName.substring(lastDot + 1) : ""
    }

    // 处理文件切换
    const handleFileChange = (fileId: string) => {
        setSelectedFileId(fileId)
        onFileChange?.(fileId)
    }

    // 获取当前选中的文件
    const currentFile = files.find((file) => file.file_id === selectedFileId)

    return (
        <Sheet open={isOpen} onOpenChange={onOpenChange}>
            <SheetContent className="w-[800px] sm:max-w-[800px] p-0">
                <SheetHeader className=" px-6 py-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-3 flex-1">
                            {/* 返回按钮 */}
                            {onBack && (
                                <Button variant="outline" size="icon" onClick={() => onBack(false)} className="h-8 w-8">
                                    <ChevronLeft className="h-4 w-4" />
                                </Button>
                            )}

                            {/* 文件选择下拉框 */}
                            <div className="flex items-center space-x-3 flex-1">
                                {/* <Select value={selectedFileId} onValueChange={handleFileChange}>
                                    <SelectTrigger className="max-w-80 shadow-none p-0 h-8 px-2 focus:ring-0">
                                        <SelectValue>
                                            <div className="flex items-center space-x-3">
                                                {currentFile && <FileIcon type={getFileExtension(currentFile.file_name)} className="w-4 h-4" />}
                                                <span className="font-medium text-gray-900">
                                                    {currentFile?.file_name || "选择文件"}
                                                </span>
                                            </div>
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {files.map((file) => (
                                            <SelectItem key={file.file_id} value={file.file_id}>
                                                <div className="flex items-center space-x-3">
                                                    <FileIcon type={getFileExtension(file.file_name)} className="w-4 h-4" />
                                                    <span className="text-sm">{file.file_name}</span>
                                                </div>
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select> */}
                                <div className="flex items-center space-x-3">
                                    {currentFile && <FileIcon type={getFileExtension(currentFile.file_name)} className="w-4 h-4" />}
                                    <span className="font-medium text-gray-900">
                                        {currentFile?.file_name || "选择文件"}
                                    </span>
                                </div>

                                {/* 关闭按钮 */}
                                <TooltipAnchor
                                    side="bottom"
                                    description='下载'
                                >
                                    <Button variant="ghost" size="icon" onClick={() => downloadFile(currentFile)} className="h-8 w-8">
                                        <Download size={14} />
                                    </Button>
                                </TooltipAnchor>
                            </div>
                        </div>
                    </div>
                </SheetHeader>

                {/* 预览内容区域 */}
                <div className="flex-1 overflow-auto">
                    <FilePreview files={files} fileId={currentFileId} />
                </div>
            </SheetContent>
        </Sheet>
    )
}
