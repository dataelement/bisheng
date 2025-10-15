import { CheckCircle, CircleX, Download, Loader2, X } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { AlertDialog, Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../../ui';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useState, useRef, useEffect } from "react";
import { getMdDownload } from '~/api/linsight';
import { useToastContext } from '~/Providers';

export default function DownloadResultFileBtn({ file, onDownloadFile, onTooltipOpenChange }) {
    const isMd = /md$/i.test(file.file_name)
    const [isLoading, setIsLoading] = useState(false)
    const [title, setTitle] = useState('PDF')
    const [isSuccess, setIsSuccess] = useState(false)
    const [isError, setIsError] = useState(false)
    const { showToast } = useToastContext();
    const [tooltipOpen, setTooltipOpen] = useState(false); 
    const timerRef = useRef(null);

    // 弹窗状态变化时通知父组件（核心：保持与Eye图标的状态联动）
    useEffect(() => {
        onTooltipOpenChange?.(tooltipOpen);
    }, [tooltipOpen, onTooltipOpenChange]);

    useEffect(() => {
        return () => {
            if (timerRef.current) {
                clearTimeout(timerRef.current);
            }
        };
    }, []);

    const handleClick = (e, url) => {
        e.stopPropagation();
        e.nativeEvent.stopImmediatePropagation()
        onDownloadFile({
            file_name: file.file_name,
            file_url: url
        })
    }

    const handleDownLoad = async (e, type) => {
        e.stopPropagation();
        e.nativeEvent.stopImmediatePropagation()
        setIsLoading(true);
        setTooltipOpen(false)
        if(type === 'docx'){
            setTitle('Docx')
        }else{
            setTitle(type);
        }
        setIsSuccess(false);
        setIsError(false);
        let apiErrorMsg = `${type}导出失败，请稍后重试`;
        
        if (timerRef.current) {
            clearTimeout(timerRef.current);
        }
    
        try {
            const response = await getMdDownload(
                {
                    file_url: file.file_url,
                    file_name: file.file_name
                },
                type
            );
    
            let isErrorResponse = false;
            let validFileData = response;
    
            if (response instanceof Blob) {
                const blobType = response.type || '';
                if (blobType.includes('application/json')) {
                    const errorText = await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.onerror = reject;
                        reader.readAsText(response);
                    });
    
                    try {
                        const errorData = JSON.parse(errorText);
                        if (errorData.status_code && errorData.status_code !== 200) {
                            apiErrorMsg = errorData.status_message || apiErrorMsg;
                            isErrorResponse = true;
                        }
                    } catch (parseErr) {
                        isErrorResponse = false;
                    }
                }
            } else if (typeof response === 'object' && response !== null) {
                if (response.status_code && response.status_code !== 200) {
                    apiErrorMsg = response.status_message || apiErrorMsg;
                    isErrorResponse = true;
                }
            }
    
            if (isErrorResponse) {
                throw new Error(apiErrorMsg);
            }
    
            let blob;
            if (validFileData instanceof Blob) {
                blob = validFileData;
            } else if (typeof validFileData === 'string' && validFileData.startsWith('%PDF-')) {
                blob = new Blob([validFileData], { type: 'application/pdf' });
            } else {
                const mimeType = type === 'pdf' 
                    ? 'application/pdf' 
                    : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
                blob = new Blob([validFileData], { type: mimeType });
            }
    
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${file.file_name.replace(/\.md$/i, '')}.${type}`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
    
            setIsSuccess(true);
            timerRef.current = setTimeout(() => {
                setIsSuccess(false);
                timerRef.current = null;
            }, 3000);
    
        } catch (error) {
            console.error(`${type.toUpperCase()}下载失败:`, error);
            setIsError(true);
            timerRef.current = setTimeout(() => {
                setIsError(false);
                timerRef.current = null;
            }, 3000);
        } finally {
            setIsLoading(false);
        }
    };

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
            <Tooltip open={tooltipOpen} onOpenChange={setTooltipOpen}>
                <TooltipTrigger asChild>
                    <span onClick={(e) => e.stopPropagation()}>
                        <Download size={16} className='text-gray-500' onClick={()=>{setTooltipOpen(true)}}/>
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