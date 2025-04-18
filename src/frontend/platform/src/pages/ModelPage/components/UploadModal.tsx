

import { useContext, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { Progress } from "../../../components/bs-ui/progress";
import { alertContext } from "../../../contexts/alertContext";
import { generateUUID } from "../../../utils";
import { UploadIcon } from "@/components/bs-icons/upload";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

interface IProps {
    accept: string[],
    fileName: string,
    onUpload: (file, func) => void,
    onSubmit: (res) => void,
    onClose: () => void,
    loading?: boolean,
    desc?: string,
    children?: React.ReactNode
}

export default function UploadModal({
    fileName, loading = false, desc = '', accept, children, onUpload, onSubmit, onClose
}: IProps) {

    const { t } = useTranslation()
    const { end, tasks, onDrop, getResult } = useUpload(true, 50, fileName, onUpload)

    // upload config
    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        accept: {
            'application/*': accept.map(str => `.${str}`)
        },
        useFsAccessApi: false,
        onDrop
    });

    return <Dialog open onOpenChange={() => onClose()}>
        <DialogContent className="sm:max-w-[425px]">
            <DialogHeader>
                <DialogTitle>{t('code.uploadFile')}</DialogTitle>
                <DialogDescription>{desc}</DialogDescription>
            </DialogHeader>
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="w-[460px]">
                    {/* 拖拽区 */}
                    <div {...getRootProps()} className="group h-[100px] border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
                        <input {...getInputProps()} />
                        <UploadIcon className="group-hover:text-primary" />
                        {isDragActive ? <p className="text-gray-400 text-sm">{t('code.dropFileHere')}</p> : <p className="text-gray-400 text-sm">{t('code.clickOrDragHere')}</p>}
                    </div>
                    {/* 进度条 */}
                    <div className=" max-h-[300px] overflow-y-auto no-scrollbar mt-4">
                        {tasks.map((task) => (
                            <div key={task.id}>
                                <p className={`max-w-[300px] overflow-hidden text-ellipsis whitespace-nowrap ${task.error && 'text-red-400'}`}>{task.file.name}</p>
                                <Progress error={task.error} value={task.schedule} className="w-full" />
                            </div>
                        ))}
                    </div>
                    {/* 插槽 */}
                    <div>
                        {children}
                    </div>
                </div>
            </div>
            <DialogFooter>
                <Button variant='outline' className="h-8" onClick={onClose}>{t('cancel')}</Button>
                <Button type="submit" className="h-8" disabled={loading || !end} onClick={() => !loading && onSubmit(getResult())}>
                    {loading && <span className="loading loading-spinner loading-xs"></span>}
                    {t('create')}
                </Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
};

interface ProcessItem {
    id: string;
    /** 文件对象 */
    file: any;
    /** 是否等待上传中 */
    await: boolean;
    /** 上传进度0-100 */
    schedule: number;
    /** 上传是否遇到错误 */
    error: boolean;
}

const useUpload = (open, maxSize, fileKey, uploadFunc) => {
    const { t } = useTranslation()
    const { setErrorData } = useContext(alertContext);

    const [progressList, setProgressList] = useState<ProcessItem[]>([])
    // 文件总数
    const fileCountRef = useRef(0)
    // 记录上传完成的文件
    const filePathsRef = useRef([])
    // 记录上传失败的文件
    const failNamesRef = useRef([])
    // 重置上传文件列表
    useEffect(() => {
        if (!open) {
            setProgressList([])
            fileCountRef.current = 0
            filePathsRef.current = []
            failNamesRef.current = []
        }
    }, [open])

    const onDrop = (acceptedFiles) => {
        const sizeLimit = maxSize * 1024 * 1024;
        const errorFile = [];
        const files = []

        // 校验文件大小限制，并给予提示
        acceptedFiles.forEach(file => {
            file.size < sizeLimit ?
                files.push(file) :
                errorFile.push(file.name);
        });
        errorFile.length && setErrorData({
            title: t('prompt'),
            list: errorFile.map(str => `${t('code.file')}: ${str} ${t('code.sizeExceedsLimit')}`),
        });
        if (!files.length) return

        // 追加新文件到上传队列
        setProgressList((list) => {
            return [...list, ...files.map(file => {
                return {
                    id: generateUUID(8),
                    file,
                    await: true,
                    schedule: 0,
                    error: false
                }
            })];
        });
        // 更新总数
        fileCountRef.current += files.length;
    }

    // 上传函数
    const uploadFileWithProgress = async (file, callback): Promise<any> => {
        try {
            const formData = new FormData();
            formData.append(fileKey, file);

            const config = {
                headers: { 'Content-Type': 'multipart/form-data;charset=utf-8' },
                onUploadProgress: (progressEvent) => {
                    const { loaded, total } = progressEvent;
                    const progress = Math.round((loaded * 100) / total);
                    console.log(`Upload progress: ${file.name} ${progress}%`);
                    callback(progress)
                    // You can update your UI with the progress information here
                },
            };

            // Convert the FormData to binary using the FileReader API
            const data = await uploadFunc(formData, config);

            data && callback(100);

            console.log('Upload complete:', data);
            return data
            // Handle the response data as needed
        } catch (error) {
            console.error('Error uploading file:', error);
            return ''
            // Handle errors
        }
    };

    // 上传调度
    const [end, setEnd] = useState(true)
    useEffect(() => {
        const maxRequestCount = 3 // 最大并发数
        // 分类
        let awaitTasks = [] // 排队上传的任务
        let peddingTasks = [] // 上传中的任务
        // 任务分组
        progressList.forEach(item => {
            if (item.await) {
                awaitTasks.push(item)
            } else if (item.schedule !== 100 && !item.error) {
                peddingTasks.push(item)
            }
        })

        // 处理未完成的任务
        if (peddingTasks.length || awaitTasks.length) {
            setEnd(false)
            // 任务补位（maxRequestCount - 正在请求数 = 空位数）
            awaitTasks.filter((e, i) => i < maxRequestCount - peddingTasks.length).forEach(task => {
                // 记录开始上传标记
                setProgressList((oldState) => oldState.map(_task => {
                    return _task.id === task.id ? {
                        ..._task,
                        await: false,
                        schedule: 1
                    } : _task
                }))
                // 上传
                uploadFileWithProgress(task.file, (count) => {
                    // 更新进度
                    setProgressList((oldState) => oldState.map(_task => {
                        return _task.id === task.id ? {
                            ..._task,
                            schedule: count
                        } : _task
                    }))
                }).then(data => {
                    if (data) {
                        filePathsRef.current.push(data)
                    } else {
                        failNamesRef.current.push(task.file.name)
                        setProgressList((oldState) => oldState.map(el => {
                            return el.id !== task.id ? el : {
                                ...el,
                                error: true
                            }
                        }))
                    }
                    // 判断所有任务处理完成
                    setEnd(filePathsRef.current.length + failNamesRef.current.length === fileCountRef.current)
                })
            })
        }

    }, [progressList])

    return {
        end,
        tasks: progressList,
        onDrop,
        getResult: () => [filePathsRef.current, failNamesRef.current]
    }
}