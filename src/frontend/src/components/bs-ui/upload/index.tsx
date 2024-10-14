import { UploadIcon } from "@/components/bs-icons/upload";
import axios from "axios";
import { X } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { Progress } from "../progress";
import { useToast } from "../toast/use-toast";
import { cname } from "../utils";

const CancelToken = axios.CancelToken;
const uploadFileWithProgress = async ({ url, fileName, file, callback, cancel = null }): Promise<any> => {
    try {
        const formData = new FormData();
        formData.append(fileName, file);

        const config = {
            headers: { 'Content-Type': 'multipart/form-data;charset=utf-8' },
            onUploadProgress: (progressEvent) => {
                const { loaded, total } = progressEvent;
                const progress = Math.round((loaded * 100) / total);
                console.log(`Upload progress: ${file.name} ${progress}%`);
                callback(progress)
                // You can update your UI with the progress information here
            },
            cancelToken: new CancelToken(function executor(c) {
                if (cancel) cancel = c;
            })
        };

        // Convert the FormData to binary using the FileReader API
        const data = await axios.post(url, formData, config);

        data && callback(100);

        console.log('Upload complete:', data);
        return data.data
        // Handle the response data as needed
    } catch (error) {
        console.error('Error uploading file:', error);
        return ''
        // Handle errors
    }
};

let qid = 1
const Upload = forwardRef(({
    url,
    fileName = 'file',
    accept,
    size = 50,
    progressClassName = '',
    onFileCountChange = () => { },
    onBeforeUpload = (files) => { }
}: any, ref) => {
    const { t } = useTranslation()

    const [progressList, setProgressList] = useState([])
    const progressCountRef = useRef(0)
    const { message } = useToast()
    // 确定上传文件
    const filePathsRef = useRef([])
    const failFilesRef = useRef([]) // 记录上传失败的文件

    useImperativeHandle(ref, () => ({
        getUploadResult() {
            return [progressList.length, filePathsRef.current, failFilesRef.current]
        }
    }));

    const onDrop = (acceptedFiles) => {
        const sizeLimit = size * 1024 * 1024;
        const errorFile = [];
        const files = []
        acceptedFiles.forEach(file => {
            file.size < sizeLimit ?
                files.push(file) :
                errorFile.push(file.name);
        });
        errorFile.length && message({
            title: t('prompt'),
            description: errorFile.map(str => `${t('code.file')}: ${str} ${t('code.sizeExceedsLimit')}`),
        });
        if (!files.length) return
        // if (acceptedFiles.length === 1 && acceptedFiles[0].type !== 'application/pdf') {
        //     return
        // }
        onBeforeUpload(files)
        setProgressList((list) => {
            return [...list, ...files.map(file => {
                return {
                    id: qid++,
                    file,
                    await: true,
                    size: sizeLimit,
                    pros: 0,
                    error: false
                }
            })];
        });
        progressCountRef.current += files.length;
    }

    // 上传调度
    const [end, setEnd] = useState(true)
    useEffect(() => {
        const requestCount = 3
        // 分类
        let awaits = [] // 排队上传的任务
        let peddings = [] // 上传中的任务
        progressList.forEach(item => {
            if (item.await) {
                awaits.push(item)
            } else if (item.pros !== 100 && !item.error) {
                peddings.push(item)
            }
        })

        // 处理未完成的任务
        if (peddings.length || awaits.length) {
            setEnd(false)
            // 任务补位
            awaits.filter((e, i) => i < requestCount - peddings.length).forEach(task => {
                // task为补位任务
                // 标记开始上传
                setProgressList((oldState) => oldState.map(el => {
                    return el.id !== task.id ? el : {
                        ...el,
                        await: false,
                        pros: 1
                    }
                }))
                // 上传{ url, fileName = 'file', file, callback }
                uploadFileWithProgress({
                    url, fileName, file: task.file, callback: (count) => {
                        // 更新进度
                        setProgressList((oldState) => oldState.map(el => {
                            return el.id !== task.id ? el : {
                                ...el,
                                pros: count
                            }
                        }))
                    }
                }).then(({ data }) => {
                    // console.log('task.file, end :>> ', task.file, 'end');
                    // console.log('filePathsRef.current.length, progressCountRef.current :>> ', filePathsRef.current.length, progressCountRef.current);
                    if (data) {
                        filePathsRef.current.push({ id: task.id, name: task.file.name, path: data.file_path })
                        onFileCountChange(filePathsRef.current.length, progressCountRef.current)
                    } else {
                        failFilesRef.current.push({ id: task.id, name: task.file.name })
                        setProgressList((oldState) => oldState.map(el => {
                            return el.id !== task.id ? el : {
                                ...el,
                                error: true
                            }
                        }))
                    }

                    setEnd(filePathsRef.current.length + failFilesRef.current.length === progressCountRef.current)
                })
            })
        }

    }, [progressList])

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        accept: {
            'application/*': accept.map(str => `.${str}`)
        },
        useFsAccessApi: false,
        onDrop
    });

    return <div>
        <div {...getRootProps()} className="group h-[100px] border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
            <input {...getInputProps()} />
            <UploadIcon className="group-hover:text-primary" />
            {isDragActive ? <p className="text-gray-400 text-sm">{t('code.dropFileHere')}</p> : <p className="text-gray-400 text-sm">{t('code.clickOrDragHere')}</p>}
        </div>
        <div className={cname('overflow-y-auto no-scrollbar mt-4', progressClassName)}>
            {progressList.map((pros) => (
                <div key={pros.id}>
                    <p className={`max-w-[300px] overflow-hidden text-ellipsis whitespace-nowrap ${pros.error && 'text-red-400'}`}>{pros.file.name}{pros.file.pros === 1 && <span>{t('code.complete')}</span>}</p>
                    <div className="w-full flex">
                        <Progress error={pros.error} value={pros.pros} />
                        <X className="hover:bg-gray-200 ml-2 cursor-pointer" onClick={() => {
                            setProgressList((oldState) => oldState.filter(el => el.id !== pros.id));
                            filePathsRef.current = filePathsRef.current.filter(el => el.id !== pros.id)
                            failFilesRef.current = failFilesRef.current.filter(el => el.id !== pros.id)
                            onFileCountChange(filePathsRef.current.length, --progressCountRef.current)
                        }} />
                    </div>
                </div>
            ))}
        </div>
    </div>
});

export default Upload