"use client"
import { Sheet, SheetContent, SheetHeader } from '@/components/bs-ui/sheet'
import { CheckCircle, ChevronLeft, CircleX, Download, Loader2 } from 'lucide-react'
import type React from "react"
import { useMemo, useState } from "react"
import { useTranslation } from 'react-i18next'
import FilePreview from './FilePreview'
import { Button } from '@/components/bs-ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/bs-ui/tooltip'
import FileIcon from './FileIcon'

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
    vid?: string
}

export default function FilePreviewDrawer({
    files,
    isOpen,
    vid,
    onOpenChange,
    currentFileId,
    onFileChange,
    downloadFile,
    directFile,
    onBack,
    handleExportOther,
    exportState
}: FilePreviewDrawerProps) {
    const { t: localize } = useTranslation()
    // const [selectedFileId, setSelectedFileId] = useState(currentFileId || files?.[0]?.file_id || "")
    const [tooltipOpen, setTooltipOpen] = useState(false)
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
                                    <p className="font-medium text-gray-900 truncate max-w-96">
                                        {currentDisplayFile?.file_name || localize('com_sop_select_file')}
                                    </p>
                                </div>

                                {/* 下载按钮 */}
                                <Button variant="ghost" disabled={!currentDisplayFile}>
                                    {String(currentDisplayFile.file_name).toLowerCase().endsWith('.md') ? (
                                        <Tooltip
                                            open={tooltipOpen}
                                            onOpenChange={setTooltipOpen} // 绑定tooltip状态
                                        >
                                            <TooltipTrigger asChild>
                                                <span onClick={(e) => e.stopPropagation()}>
                                                    <Download size={16} onClick={() => { setTooltipOpen(true) }} />
                                                </span>
                                            </TooltipTrigger>
                                            <TooltipContent side='bottom' align='center' className='bg-white text-gray-800 border border-gray-200'>
                                                <div className='flex flex-col gap-2'>
                                                    <div className='flex gap-2 items-center cursor-pointer hover:bg-gray-100 rounded-md p-1' onClick={(e) => { e.stopPropagation(); downloadFile(currentDisplayFile); setTooltipOpen(false); }}>
                                                        <FileIcon type={'md'} className='size-5' />
                                                        <div className='w-full flex gap-2 items-center'>Markdown</div>
                                                    </div>
                                                    <div className='flex gap-2 items-center rounded-md p-1 cursor-pointer hover:bg-gray-100' onClick={(e) => { e.stopPropagation(); handleExportOther(e, 'pdf', currentDisplayFile); setTooltipOpen(false); }}>
                                                        <FileIcon type={'pdf'} className='size-5' />
                                                        <div className='w-full flex gap-2 items-center'>PDF</div>
                                                    </div>
                                                    <div className='flex gap-2 items-center rounded-md p-1 cursor-pointer hover:bg-gray-100' onClick={(e) => { e.stopPropagation(); handleExportOther(e, 'docx', currentDisplayFile); setTooltipOpen(false); }}>
                                                        <FileIcon type={'docx'} className='size-5' />
                                                        <div className='w-full flex gap-2 items-center'>Docx</div>
                                                    </div>
                                                </div>
                                            </TooltipContent>
                                        </Tooltip>
                                    ) : (
                                        <Download size={16} onClick={(e) => { e.stopPropagation(); downloadFile(currentDisplayFile); }} />

                                    )}
                                </Button>
                            </div>
                        </div>
                    </div>
                </SheetHeader>

                {/* 预览内容区域 */}
                <div className="flex-1 overflow-auto">
                    <FilePreview
                        files={files}
                        fileId={currentFileId}
                        vid={vid}
                        currentDisplayFile={currentDisplayFile}
                        onDownloadFile={downloadFile}
                    />
                </div>
            </SheetContent>
        </Sheet>
    )
}
