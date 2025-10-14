import { CheckCircle, CircleX, Download, Loader2, X } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { AlertDialog, Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../../ui';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useState, useRef, useEffect } from "react";
import { getMdDownload } from '~/api/linsight';
import { useToastContext } from '~/Providers';

export default function DownloadResultFileBtn({ file, onDownloadFile }) {
    const isMd = /md$/i.test(file.file_name)
    const [isLoading, setIsLoading] = useState(false)
    const [title, setTitle] = useState('PDF')
    const [isSuccess, setIsSuccess] = useState(false)
    const [isError, setIsError] = useState(false)
    const { showToast } = useToastContext();
    
    // 1. 创建 ref 来存储定时器ID
    const timerRef = useRef(null);

    // 2. 组件卸载时清除定时器
    useEffect(() => {
        return () => {
            if (timerRef.current) {
                clearTimeout(timerRef.current);
            }
        };
    }, []);

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
        setIsLoading(true);
        setTitle(type.toUpperCase());
        setIsSuccess(false);
        setIsError(false);
        // 新增：存储接口返回的具体错误信息
        let apiErrorMsg = `${type.toUpperCase()}导出失败，请稍后重试`;
        
        // 清除旧定时器
        if (timerRef.current) {
            clearTimeout(timerRef.current);
        }
    
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
    
            // 关键步骤1：识别并解析JSON格式的错误响应
            let isErrorResponse = false;
            let validFileData = response; // 存储最终用于生成文件的数据
    
            // 情况1：响应是Blob，先判断是否为JSON错误（后端返回200但内容是JSON错误）
            if (response instanceof Blob) {
                const blobType = response.type || '';
                // 若Blob类型是JSON，说明是错误信息
                if (blobType.includes('application/json')) {
                    // 将Blob转为文本，解析JSON错误数据
                    const errorText = await new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.onerror = reject;
                        reader.readAsText(response);
                    });
    
                    try {
                        const errorData = JSON.parse(errorText);
                        // 匹配接口返回的错误结构（status_code、status_message、data）
                        if (errorData.status_code && errorData.status_code !== 200) {
                            apiErrorMsg = errorData.status_message || apiErrorMsg;
                            // 补充显示详细错误（如Playwright安装提示）
                            if (errorData.data) {
                                // 简化长错误文本，保留关键指引（避免提示框过长）
                                const simplifiedDetail = errorData.data.includes('playwright install')
                                    ? '（需执行"playwright install"安装浏览器依赖）'
                                    : `（详情：${errorData.data.slice(0, 80)}...）`;
                                apiErrorMsg += simplifiedDetail;
                            }
                            isErrorResponse = true;
                        }
                    } catch (parseErr) {
                        // 解析JSON失败，说明是正常文件Blob，不处理
                        isErrorResponse = false;
                    }
                }
            } 
            // 情况2：响应是普通对象，直接判断是否为错误（如{status_code:10003,...}）
            else if (typeof response === 'object' && response !== null) {
                if (response.status_code && response.status_code !== 200) {
                    apiErrorMsg = response.status_message || apiErrorMsg;
                    isErrorResponse = true;
                }
            }
    
            // 若检测到错误响应，直接抛出错误触发catch逻辑
            if (isErrorResponse) {
                throw new Error(apiErrorMsg);
            }
    
            // 关键步骤2：处理正常的文件数据（生成Blob）
            let blob;
            if (validFileData instanceof Blob) {
                blob = validFileData;
            } 
            // 兼容PDF二进制字符串格式（如以%PDF-开头的字符串）
            else if (typeof validFileData === 'string' && validFileData.startsWith('%PDF-')) {
                blob = new Blob([validFileData], { type: 'application/pdf' });
            } 
            // 其他情况：按文件类型设置MIME，生成Blob
            else {
                const mimeType = type === 'pdf' 
                    ? 'application/pdf' 
                    : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
                blob = new Blob([validFileData], { type: mimeType });
            }
    
            console.log('创建的Blob:', blob);
    
            // 生成下载链接并触发下载
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            // 优化文件名：用正则替换.md后缀，避免重复（如xxx.md.pdf → xxx.pdf）
            a.download = `${file.file_name.replace(/\.md$/i, '')}.${type}`;
            document.body.appendChild(a);
            a.click();
    
            // 清理资源，避免内存泄漏
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
    
            setIsSuccess(true);
            console.log(`${type.toUpperCase()}文件下载成功`);
    
            // 3秒后自动隐藏成功提示
            timerRef.current = setTimeout(() => {
                setIsSuccess(false);
                timerRef.current = null;
            }, 3000);
    
        } catch (error) {
            console.error(`${type.toUpperCase()}下载失败:`, error);
            setIsError(true);
            showToast({ status: 'error', message: apiErrorMsg });
            
            // 3秒后自动隐藏错误提示
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

