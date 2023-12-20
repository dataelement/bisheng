import { useContext, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Progress } from "../../components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { alertContext } from "../../contexts/alertContext";
import { subUploadLibFile } from "../../controllers/API";
import { uploadFileWithProgress } from "./upload";

let qid = 1
export default function UploadModal({ id, accept, open, desc = '', children = null, setOpen }) {
    const { t } = useTranslation()
    // const [file, setFile] = useState(null);
    // const [progress, setProgress] = useState(0);
    const { setErrorData, setSuccessData } = useContext(alertContext);
    // size
    const [size, setSize] = useState('1000')
    // 符号
    const [symbol, setSymbol] = useState('\\n\\n')
    const chunkType = useRef('smart')
    const [overlap, setOverlap] = useState('100')

    const [progressList, setProgressList] = useState([])
    const progressCountRef = useRef(0)

    useEffect(() => {
        if (!open) {
            setProgressList([])
            progressCountRef.current = 0
            filePathsRef.current = []
        }
    }, [open])

    const onDrop = (acceptedFiles) => {
        const sizeLimit = 49900000;
        const errorFile = [];
        acceptedFiles.forEach(file => {
            if (file.size > sizeLimit) {
                errorFile.push(file.name);
            }
        });
        if (errorFile.length) return setErrorData({
            title: t('prompt'),
            list: errorFile.map(str => `${t('code.file')}: ${str} ${t('code.sizeExceedsLimit')}`),
        });
        // if (acceptedFiles.length === 1 && acceptedFiles[0].type !== 'application/pdf') {
        //     return
        // }
        setProgressList((list) => {
            return [...list, ...acceptedFiles.map(file => {
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
        progressCountRef.current += acceptedFiles.length;
    }

    // 确定上传文件
    const filePathsRef = useRef([])
    const [loading, setLoading] = useState(false)
    const handleSubmit = async () => {
        const errorList = [];
        // if (!/^\d+$/.test(size)) errorList.push(t('code.setSplitSize'));
        if (!filePathsRef.current.length) errorList.push(t('code.selectFileToUpload'));
        if (errorList.length) return setErrorData({ title: t('prompt'), list: errorList });
        setLoading(true);
        const params: any = {
            file_path: filePathsRef.current,
            knowledge_id: Number(id),
            auto: true
        };
        if (chunkType.current === 'chunk') {
            // Split by ;
            params.separator = symbol.split(/;|；/).map(el => el.replace(/\\([nrtb])/g, function (match, capture) {
                return {
                    'n': '\n',
                    'r': '\r',
                    't': '\t',
                    'b': '\b'
                }[capture];
            }));
            params.chunck_size = Number(/^\d+$/.test(size) ? size : '1000');
            params.auto = false;
            params.chunk_overlap = Number(/^\d+$/.test(overlap) ? overlap : '100') // 异常值使用默认值
        }
        await subUploadLibFile(params);
        setOpen(false);
        setLoading(false);
    }

    // 上传调度
    const [end, setEnd] = useState(true)
    useEffect(() => {
        const requestCount = 3
        // 分类
        let awaits = []
        let peddings = []
        progressList.forEach(item => {
            if (item.await) {
                awaits.push(item)
            } else if (item.pros !== 100) {
                peddings.push(item)
            }
        })

        if (peddings.length || awaits.length) {
            setEnd(false)
            awaits.filter((e, i) => i < requestCount - peddings.length).forEach(item => {
                // 上传任务
                // 标记开始上传
                setProgressList((oldState) => oldState.map(el => {
                    return el.id !== item.id ? el : {
                        ...el,
                        await: false,
                        pros: 1
                    }
                }))
                // 上传
                uploadFileWithProgress(item.file, (count) => {
                    // 更新进度
                    setProgressList((oldState) => oldState.map(el => {
                        return el.id !== item.id ? el : {
                            ...el,
                            pros: count
                        }
                    }))
                }).then(data => {
                    console.log('item.file, end :>> ', item.file, 'end');
                    console.log('filePathsRef.current.length, progressCountRef.current :>> ', filePathsRef.current.length, progressCountRef.current);

                    // setFilePaths
                    if (!data) return setProgressList((oldState) => oldState.map(el => {
                        return el.id !== item.id ? el : {
                            ...el,
                            error: true
                        }
                    }))
                    filePathsRef.current.push(data.file_path)
                    setEnd(filePathsRef.current.length === progressCountRef.current)
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

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[540px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={(e) => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg">{t('code.uploadFile')}</h3>
            <p className="py-4">{desc}</p>
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="w-[460px]">
                    <div {...getRootProps()} className="h-[100px] border border-dashed flex justify-center items-center cursor-pointer">
                        <input {...getInputProps()} />
                        {isDragActive ? <p>{t('code.dropFileHere')}</p> : <p>{t('code.clickOrDragHere')}</p>}
                    </div>
                    <div className=" max-h-[300px] overflow-y-auto no-scrollbar mt-4">
                        {progressList.map((pros) => (
                            <div key={pros.id}>
                                <p className={`max-w-[300px] overflow-hidden text-ellipsis whitespace-nowrap ${pros.error && 'text-red-400'}`}>{pros.file.name}{pros.file.pros === 1 && <span>{t('code.complete')}</span>}</p>
                                <Progress error={pros.error} value={pros.pros} className="w-full" />
                            </div>
                        ))}
                    </div>
                    <Tabs defaultValue="smart" className="w-full mt-4" onValueChange={(val) => chunkType.current = val}>
                        <TabsList className="">
                            <TabsTrigger value="smart" className="roundedrounded-xl">{t('code.smartSplit')}</TabsTrigger>
                            <TabsTrigger value="chunk">{t('code.manualSplit')}</TabsTrigger>
                        </TabsList>
                        <TabsContent value="smart">
                        </TabsContent>
                        <TabsContent value="chunk">
                            <div className="grid gap-4 py-4">
                                <div className="grid grid-cols-5 items-center gap-4">
                                    <Label htmlFor="name" className="text-right col-span-2">{t('code.delimiter')}</Label>
                                    <Input id="name" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder={t('code.delimiterPlaceholder')} className="col-span-3" />
                                    <Label htmlFor="name" className="text-right col-span-2">{t('code.splitLength')}</Label>
                                    <Input id="name" value={size} onChange={(e) => setSize(e.target.value)} placeholder={t('code.splitSizePlaceholder')} className="col-span-3" />
                                    <Label htmlFor="name" className="text-right col-span-2">{t('code.chunkOverlap')}</Label>
                                    <Input id="name" value={overlap} onChange={(e) => setOverlap(e.target.value)} placeholder={t('code.chunkOverlap')} className="col-span-3" />
                                </div>
                            </div>
                        </TabsContent>
                    </Tabs>

                    <div className="flex justify-end gap-4">
                        <Button variant='outline' className="h-8" onClick={() => setOpen(false)}>{t('cancel')}</Button>
                        <Button type="submit" className="h-8" disabled={loading || !end} onClick={() => !loading && handleSubmit()}>{t('create')}</Button>
                    </div>
                </div>
            </div>
        </form>
    </dialog>
};