import { useToast } from "@/components/bs-ui/toast/use-toast";
import { cname, generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import DropZone from "./DropZone";
import ProgressItem from "./ProgressItem";

export interface Progress {
    id: string,
    file: File,
    fileName: string,
    progress: ProgressStatus,
    error: boolean
}

export const enum ProgressStatus {
    Await = 'await',
    Uploading = 'uploading',
    End = 'end'
}

const KnowledgeUploadComponent = ({
    size = 50,
    progressClassName = '',
    onFileChange,
    onSelectFile
}) => {
    const { t } = useTranslation()
    const { message } = useToast()

    const [progressList, setProgressList] = useState<Progress[]>([])
    const progressCountRef = useRef(0) // 文件总数
    const { appConfig } = useContext(locationContext)

    const successFilesRef = useRef([]) // 记录上传成功的文件
    const failFilesRef = useRef([]) // 记录上传失败的文件
    // 上传任务调度(追加,)
    useEffect(() => {
        onSelectFile(progressList.length)
        if (progressList.length === 0) return

        const MaximumTask = 6 // 最大并发
        const [uploadingList, awaitingList] = progressList.reduce(([uploading, awaitList], pros) => {
            if (pros.progress === ProgressStatus.Await) {
                return [uploading, [...awaitList, pros]]
            } else if (pros.progress === ProgressStatus.Uploading) {
                return [[...uploading, pros], awaitList]
            }
            return [uploading, awaitList]
        }, [[], []])

        if (awaitingList.length === 0 && uploadingList.length === 0) {
            console.log('所有文件上传完成 :>> ');
            onFileChange(successFilesRef.current, failFilesRef.current)
        } else if (awaitingList.length > 0 && uploadingList.length < MaximumTask) {
            let runCount = 0
            setProgressList((oldState) => {
                return oldState.map((pros) => {
                    if (pros.progress === ProgressStatus.Await && runCount++ < MaximumTask - uploadingList.length) {
                        console.log('开启上传任务 +1 :>> ', pros.id);
                        return {
                            ...pros,
                            progress: ProgressStatus.Uploading
                        }
                    } else {
                        return pros
                    }
                })
            })
        }
    }, [progressList])

    // beforeupload
    const handleDrop = (acceptedFiles) => {
        // 校验超大小文件
        const sizeLimit = appConfig.uploadFileMaxSize * 1024 * 1024;
        const [bigFiles, files] = acceptedFiles.reduce(
            ([big, small], file) => {
                if (progressList.some(pros => pros.fileName === file.name)) return [big, small] // 过滤重复文件
                return file.size < sizeLimit
                    ? [big, [...small, file]]
                    : [[...big, file.name], small]
            },
            [[], []]
        );
        bigFiles.length && message({
            title: t('prompt'),
            description: bigFiles.map(str => `${t('code.file')}: ${str} ${t('code.sizeExceedsLimit', { size })}`),
        });
        if (!files.length) return
        // 追加上传文件
        setProgressList((list) => {
            return [...list, ...files.map(file => {
                return {
                    id: generateUUID(6),
                    file,
                    fileName: file.name,
                    progress: ProgressStatus.Await,
                    error: false
                }
            })];
        });
        progressCountRef.current += files.length;
    }

    const handleUploadResult = (id: string, result: any) => {
        console.log('上传完成+1 :>> ', id);
        setProgressList((list) => list.map((pros) => (
            pros.id === id ? {
                ...pros,
                progress: ProgressStatus.End,
                error: !result.file_path
            } : pros
        )))
        
        // 临时去重方式
        successFilesRef.current = successFilesRef.current.filter((pros) => pros.id !== id)
        failFilesRef.current = failFilesRef.current.filter((pros) => pros.id !== id)
        
        result.file_path
            ? successFilesRef.current.push(result)
            : failFilesRef.current.push(result)
    }

    const handleDelete = (id: string) => {
        successFilesRef.current = successFilesRef.current.filter((pros) => pros.id !== id)
        failFilesRef.current = failFilesRef.current.filter((pros) => pros.id !== id)
        setProgressList((list) => list.filter((pros) => pros.id !== id))
    }

    return <div className="">
        <DropZone onDrop={handleDrop} />
        <div className={cname('overflow-y-auto mt-4 space-y-2', progressClassName)}>
            {progressList.map((pros) =>
                <ProgressItem
                    key={pros.id}
                    item={pros}
                    onResulte={handleUploadResult}
                    onDelete={handleDelete}
                />
            )}
        </div>
    </div>
};

export default KnowledgeUploadComponent