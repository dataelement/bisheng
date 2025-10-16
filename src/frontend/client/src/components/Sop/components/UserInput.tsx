import { X, ChevronUp, ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { checkFileParseStatus } from "~/api/linsight";
import { File_Accept } from "~/common";
import { AttachmentIcon } from "~/components/svg";
import SendIcon from "~/components/svg/SendIcon";
import { Button, Textarea } from "~/components/ui";
import { FileIcon } from "~/components/ui/icon/File/FileIcon";
import { useGetBsConfig, useUploadFileMutation } from "~/data-provider";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { getFileExtension } from "~/utils";

interface UploadingFile {
    id: string
    file: File
    progress: number
    abortController: AbortController
    status: "uploading" | "success" | "error"
    result?: any
}

export default function UserInput({ taskId, history = {}, disable = false, onSendInput }) {
    const localize = useLocalize()
    const [inputValue, setInputValue] = useState(history.user_input || "")
    const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>(history?.files?.map(file => ({
        id: file.file_id,
        file: new File([], file.original_filename),
        progress: 100,
        abortController: null,
        status: '',
        result: {
            name: file.original_filename,
            size: 0
        }
    })) || [])
    const [isDragOver, setIsDragOver] = useState(false)
    const [collapsed, setCollapsed] = useState(false)
    const [isInput, setIsInput] = useState(disable)
    const fileInputRef = useRef<HTMLInputElement>(null)
    // 新增：用于动画的容器Ref（获取折叠区域真实高度）
    const collapseContainerRef = useRef<HTMLDivElement>(null)
    // 解析中
    console.log('uploadingFiles :>> ', history, uploadingFiles);
    const { showToast } = useToastContext();
    const isParsing = useMemo(() => {
        return uploadingFiles.some((file) => file.status === "success")
    }, [uploadingFiles])
    // 更新文件上传解析状态
    useEffect(() => {
        const files = uploadingFiles.filter((file) => file.status === "success");
        if (files.length > 0) {
            const intervalId = setInterval(async () => {
                const res = await checkFileParseStatus(files.map((f) => f.result.file_id));
                const statusMap = new Map(res.data.map(item => [item.file_id, item.parsing_status]));

                setUploadingFiles((prev) => {
                    return prev.reduce((result, file) => {
                        const fileId = file.result.file_id; // 假设 file 对象中有 file_id 字段
                        if (statusMap.has(fileId)) {
                            const status = statusMap.get(fileId);
                            if (status === 'completed' && file.status !== '') {
                                // 将解析状态更新为空，并保留文件
                                result.push({ ...file, status: '', result: { ...file.result, parsing_status: 'completed' } });
                            } else if (status === 'failed') {
                                // 失败文件，显示错误消息，且不加入结果数组
                                showToast({ message: localize('com_file_parse_failed_auto_removed', { 0: file.result.filename }), status: 'error' });
                            } else {
                                // 其他状态保持文件不变
                                result.push(file);
                            }
                        } else {
                            result.push(file);
                        }
                        return result;
                    }, []);
                });
            }, 2000);

            // 清理定时器
            return () => clearInterval(intervalId);
        }
    }, [uploadingFiles]);



    const uploadFile = useUploadFileMutation({
        onSuccess: (data, variables) => {
            console.log("upload success", data)
            const tempFileId = data.temp_file_id

            setUploadingFiles((prev) =>
                prev.map((file) => (file.id === tempFileId ? { ...file, status: "success", progress: 100, result: data } : file)),
            )
        },
        onError: (_error, variables) => {
            const error = _error
            console.log("upload error", error)
            const formData = variables.body as FormData
            const fileId = formData.get("file_id") as string

            setUploadingFiles((prev) =>
                prev.map((file) => (file.id === fileId ? { ...file, status: "error", progress: 0 } : file)),
            )
        },
    })

    const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
        const files = event.target.files
        if (!files) return

        handleFiles(Array.from(files))

        // 清空input
        if (fileInputRef.current) {
            fileInputRef.current.value = ""
        }
    }

    const handleFiles = (files: File[]) => {
        files.forEach((file) => {
            const fileId = `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
            const abortController = new AbortController()

            // 添加到上传列表
            const uploadingFile: UploadingFile = {
                id: fileId,
                file,
                progress: 0,
                abortController,
                status: "uploading",
            }

            setUploadingFiles((prev) => [...prev, uploadingFile])

            // 创建FormData并开始上传
            const formData = new FormData()
            formData.append("file", file)
            formData.append("file_id", fileId)
            formData.append("file_name", file.name)

            window.isLinsight = true // TODO: 临时方案，后续需要优化
            uploadFile.mutate({
                body: formData,
                signal: abortController.signal,
            })
        })
    }

    const handleDragEnter = (e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragOver(true)
    }

    const handleDragLeave = (e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        // 只有当离开整个容器时才设置为false
        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
            setIsDragOver(false)
        }
    }

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
    }

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragOver(false)

        const files = Array.from(e.dataTransfer.files)
        if (files.length > 0) {
            handleFiles(files)
        }
    }

    const handleCancelUpload = (fileId: string) => {
        setUploadingFiles((prev) => {
            const file = prev.find((f) => f.id === fileId)
            if (file && file.status === "uploading") {
                file.abortController.abort()
            }
            return prev.filter((f) => f.id !== fileId)
        })
    }

    const getFileType = (fileName: string) => {
        return fileName.split(".").pop()?.toLowerCase()
    }

    // Process the sent input
    const handleSendInput = () => {
        if (inputValue.trim()) {
            setCollapsed(true)
            setIsInput(true)
            // console.log('object :>> ', {
            //     task_id: taskId,
            //     user_input: inputValue,
            //     files: uploadingFiles.map((file) => file.result)
            // });
            onSendInput({
                task_id: taskId,
                user_input: inputValue,
                files: uploadingFiles.map((file) => file.result)
            })
            // setUploadingFiles([])
            // setInputValue("")
        }
    }

    // Handle Enter key to send
    const handleKeyDown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            handleSendInput()
        }
    }

    const { data: bsConfig } = useGetBsConfig()
    const accept = useMemo(() => {
        return bsConfig?.enable_etl4lm
            ? File_Accept.Linsight_Etl4lm
            : File_Accept.Linsight
    }, [bsConfig])

    return (
        <div
            className={`border rounded-lg my-2 relative transition-all duration-200 ${isDragOver ? "border-blue-400 border-2 bg-blue-50" : "border-[#dfdede]"
                }`}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
        >
            {isDragOver && (
                <div className="absolute inset-0 bg-blue-50/90 border-2 border-dashed border-blue-400 rounded-2xl flex items-center justify-center z-10">
                    <div className="text-blue-600 text-center">
                        <div className="text-lg font-medium">{localize('com_addAnything')}</div>
                        <div className="text-sm opacity-75">{localize('com_dropAnyFileToAdd')}</div>
                    </div>
                </div>
            )}

            <div className="border-b flex items-center justify-between">
                <div className="flex items-center">
                    {!isInput ? <span className="bg-[#D5E3FF] m-2 ml-3 p-1 px-3 text-xs text-primary rounded-md">
                        {localize("com_sop_waiting_input")}
                    </span> :
                        <span className="bg-green-100 m-2 ml-3 p-1 px-3 text-xs text-green-800 rounded-md text-bold">
                            {localize("com_sop_input")}
                        </span>
                    }
                    <p className="m-2">{history.params?.call_title}</p>
                </div>
                <button
                    type="button"
                    className="m-2 mr-3 p-1 rounded-md hover:bg-gray-100 text-gray-700 transition-colors"
                    aria-label={collapsed ? localize("com_action_expand") : localize("com_action_collapse")}
                    onClick={() => setCollapsed((v) => !v)}
                >
                    {collapsed ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
                </button>
            </div>
            <div
                ref={collapseContainerRef}
                className="overflow-hidden transition-all duration-300 ease-in-out"
                style={{
                    maxHeight: collapsed ? 0 : collapseContainerRef.current?.scrollHeight + "px",
                    opacity: collapsed ? 0 : 1, // 配合透明度增强动画效果
                    padding: collapsed ? 0 : "0 2px", // 折叠时清除内边距
                }}
            >
                <div className="m-2">
                    <span className="pl-3 text-sm ">{history.params?.call_content}</span>
                </div>

                {uploadingFiles.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-2 px-3">
                        {uploadingFiles.map((uploadingFile) => (
                            <div
                                key={uploadingFile.id}
                                className="group min-w-52 relative flex items-center gap-2 border bg-white p-2 rounded-2xl cursor-default"
                            >
                                {!disable && <span
                                    className="opacity-0 group-hover:opacity-100 absolute p-0.5 right-1.5 top-1.5 bg-black text-white rounded-full cursor-pointer transition-opacity hover:bg-gray-800"
                                    onClick={() => handleCancelUpload(uploadingFile.id)}
                                >
                                    <X size={14} />
                                </span>
                                }
                                <FileIcon loading={uploadingFile.status !== ""} type={getFileType(uploadingFile.file.name)} />
                                <div className="flex-1">
                                    <div className="max-w-48 text-sm font-medium text-gray-700 truncate">{uploadingFile.file.name}</div>
                                    {['uploading', 'success'].includes(uploadingFile.status) ? null
                                        // <div className="text-xs text-gray-500">
                                        //     {localize("com_inputfiles_uploading")} {uploadingFile.progress}%
                                        // </div>
                                        // ) : uploadingFile.status === "success" ? (
                                        //     <div className="text-xs text-green-600">{localize("com_inputfiles_parsing")}</div>
                                        : uploadingFile.status === "error" ? (
                                            <div className="text-xs text-red-500">上传失败</div>
                                        ) : (
                                            uploadingFile.file.size ? <div className="text-xs text-gray-500">{getFileExtension(uploadingFile.file.name)}</div> : null
                                        )}
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                <div className="bg-gray-50 rounded-lg pl-2 m-2 pb-10"> {/* 增加底部内边距，避免按钮被遮挡 */}
                    <Textarea
                        id={taskId}
                        placeholder={localize("com_sop_please_input")}
                        className="border-none bg-transparent ![box-shadow:initial] pl-0 pr-2 pt-2 h-auto"
                        rows={1}
                        value={inputValue}
                        maxLength={10000}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={handleKeyDown}
                        disabled={isInput}
                    />

                    <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        className="hidden"
                        onChange={handleFileSelect}
                        accept={accept}
                    />

                    <Button
                        variant={"ghost"}
                        className="absolute bottom-4 right-14 size-9 rounded-full p-0 hover:bg-gray-200 transition-colors"
                        onClick={() => fileInputRef.current?.click()}
                        disabled={isInput}
                    >
                        <AttachmentIcon />
                    </Button>
                    <Button
                        className="absolute bottom-4 right-4 size-9 rounded-full p-0 bg-black hover:bg-black/80 transition-colors"
                        onClick={handleSendInput}
                        disabled={!inputValue.trim() || isInput || isParsing}
                    >
                        <SendIcon size={24} />
                    </Button>
                </div>
            </div>
        </div>
    )
}
