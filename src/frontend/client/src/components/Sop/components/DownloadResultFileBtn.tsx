import { CheckCircle, CircleX, Download, Loader2, X } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { AlertDialog, Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../../ui';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useState } from "react";
import { getMdDownload } from '~/api/linsight';
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
    const handleDownLoad = async (e, type) => {
        e.stopPropagation();
        setIsLoading(true)
        setTitle(type.toUpperCase())
        setIsSuccess(false)
        setIsError(false)
    
        try {
            console.log('开始下载，参数:', {
                file_url: file.file_url,
                file_name: file.file_name,
                to_type: type
            });
    
            const response = await getMdDownload(
                {
                    file_url: file.file_url,
                    file_name: file.file_name
                },
                type
            );
    
            console.log('下载API返回数据类型:', typeof response);
            
            // 处理PDF二进制数据
            let blob;
            if (response instanceof Blob) {
                blob = response;
            } else if (typeof response === 'string' && response.startsWith('%PDF-')) {
                // 如果是PDF二进制字符串，转换为Blob
                blob = new Blob([response], { type: 'application/pdf' });
            } else {
                // 其他情况也尝试创建Blob
                blob = new Blob([response], { 
                    type: type === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' 
                });
            }
    
            console.log('创建的Blob:', blob);
    
            // 创建下载链接
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${file.file_name.replace('.md', '')}.${type}`;
            document.body.appendChild(a);
            a.click();
            
            // 清理
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            setIsSuccess(true);
            console.log('文件下载成功');
    
            // 3秒后自动隐藏成功提示
            setTimeout(() => {
                setIsSuccess(false);
            }, 3000);
    
        } catch (error) {
            console.error('下载失败:', error);
            setIsError(true);
            // 3秒后自动隐藏错误提示
            setTimeout(() => {
                setIsError(false);
            }, 3000);
        } finally {
            setIsLoading(false);
        }
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

