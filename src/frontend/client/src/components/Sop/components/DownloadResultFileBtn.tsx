import { CheckCircle, CircleX, Download, Loader2, X } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { AlertDialog, Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../../ui';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useState } from "react";
export default function DownloadResultFileBtn({ file, onDownloadFile }) {
    const isMd = /md$/i.test(file.file_name)
    const [isLoading, setIsLoading] = useState(false)
    const [title, setTitle] = useState('PDF')
    const [isSuccess, setIsSuccess] = useState(false)
    const [isError, setIsError] = useState(false)
    const handleClick = (e, url) => {
        e.stopPropagation();
        setIsLoading(true)
        onDownloadFile({
            file_name: file.file_name,
            file_url: url
        })
    }

    const handleDownLoad = (e, type) => {
        e.stopPropagation();
        setIsLoading(true)
        setTitle(type)
        // loading
        setTimeout(() => {
            setIsLoading(false)
            setIsSuccess(true)
        }, 2000)
        setTimeout(() => {
            setIsError(true)
        }, 4000)
    }

    if (!isMd) return <Button variant="ghost" className=' w-6 h-6 p-0'>
        <Download size={16} onClick={(e) => {
            e.stopPropagation();
            onDownloadFile({
                file_name: file.file_name,
                file_url: file.file_url
            })
        }} />
    </Button>

    return (
        <>
            <Tooltip>
                <TooltipTrigger asChild>
                    <span>
                        <Download size={16} className='text-gray-500' />
                    </span>
                </TooltipTrigger>
                <TooltipContent side='bottom' align='center' noArrow className=' bg-white text-gray-800 border border-gray-200'>
                    <div className='flex flex-col gap-2 '>
                        <div className='flex gap-2 items-center cursor-pointer hover:bg-gray-100 rounded-md p-1' onClick={(e) => handleClick(e, file.file_url)}>
                            <FileIcon type={'md'} className='size-5' />
                            <div className='w-full flex gap-2 items-center'>
                                Markdown
                            </div>
                        </div>
                        <div className='flex gap-2 items-center cursor-pointer hover:bg-gray-100 rounded-md p-1' onClick={(e) => handleDownLoad(e, 'pdf')}>
                            <FileIcon type={'pdf'} className='size-5' />
                            <div className='w-full flex gap-2 items-center' >
                                PDF
                            </div>
                        </div>
                        <div className='flex gap-2 items-center cursor-pointer hover:bg-gray-100 rounded-md p-1' onClick={(e) => handleDownLoad(e, 'docx')}>
                            <FileIcon type={'docx'} className='size-5' />
                            <div className='w-full flex gap-2 items-center' >
                                Docx
                            </div>
                        </div>
                    </div>
                </TooltipContent>
            </Tooltip>
            {isLoading && (
                <div className="fixed top-24 right-5 flex items-center gap-2 bg-white p-3 rounded-lg shadow-md z-50">
                    <Loader2 className="size-5 animate-spin text-blue-500" />
                    <div className="text-sm text-gray-800">{title}&nbsp;正在导出，请稍后...&nbsp;&nbsp;</div>
                </div>
            )}
            {isSuccess && (
                <div className="fixed top-24 right-5 flex items-center gap-2 bg-white p-3 rounded-lg shadow-md z-50">
                    <CheckCircle className="size-5 text-green-500" />
                    <div className="text-sm text-gray-800">{title}&nbsp;文件下载成功</div>
                </div>
            )}
            {isError && (
                <div className="fixed top-24 right-5 flex items-center gap-2 bg-white p-3 rounded-lg shadow-md z-50">
                    <CircleX className="size-5 text-red-500" />
                    <div className="text-sm text-gray-800">{title}&nbsp;导出失败</div>
                </div>
            )}
        </>
    )
};

