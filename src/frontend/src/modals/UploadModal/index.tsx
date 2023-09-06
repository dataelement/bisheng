import { useContext, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Progress } from "../../components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { alertContext } from "../../contexts/alertContext";
import { subUploadLibFile } from "../../controllers/API";
import { uploadFileWithProgress } from "./upload";

let qid = 1
export default function UploadModal({ id, open, desc = '', children = null, setOpen }) {

    // const [file, setFile] = useState(null);
    // const [progress, setProgress] = useState(0);
    const { setErrorData, setSuccessData } = useContext(alertContext);
    // size
    const [size, setSize] = useState('1000')
    // 符号
    const [symbol, setSymbol] = useState('\\n\\n')
    const chunkType = useRef('smart')

    const [progressList, setProgressList] = useState([])

    useEffect(() => {
        if (!open) {
            setProgressList([])
            filePathsRef.current = []
        }
    }, [open])

    const onDrop = (acceptedFiles) => {
        const size = 4990000
        const errorFile = []
        acceptedFiles.forEach(file => {
            file.size > size && errorFile.push(file.name)
        });
        if (errorFile.length) return setErrorData({
            title: "文件不能超50M",
            list: errorFile.map(str => `文件：${str}超过50M`),
        })
        // if (acceptedFiles.length === 1 && acceptedFiles[0].type !== 'application/pdf') {
        //     return 
        // }

        const _file = acceptedFiles[0]
        setProgressList((list) => {
            return [...list, ...acceptedFiles.map(file => {
                return {
                    id: qid++,
                    file,
                    await: true,
                    size: size,
                    pros: 0,
                    error: false
                }
            })]
        })
    };
    // 确定上传文件
    const filePathsRef = useRef([])
    const [loading, setLoading] = useState(false)
    const handleSubmit = async () => {
        const errorList = []
        if (!/^\d+$/.test(size)) errorList.push('请设置文件切分大小')
        if (!filePathsRef.current.length) errorList.push('请先选择文件上传')
        if (errorList.length) return setErrorData({ title: '提示', list: errorList })
        setLoading(true)
        const params = {
            file_path: filePathsRef.current,
            knowledge_id: Number(id),
            chunck_size: Number(size)
        }
        if (chunkType.current === 'chunk') params.symbol = symbol
        await subUploadLibFile(params)
        setOpen(false)
        setLoading(false)
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
                    // setFilePaths
                    if (!data) return setProgressList((oldState) => oldState.map(el => {
                        return el.id !== item.id ? el : {
                            ...el,
                            error: true
                        }
                    }))
                    filePathsRef.current.push(data.file_path)
                    setEnd(filePathsRef.current.length === progressList.length)
                })
            })
        }

    }, [progressList])

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        accept: {
            // 'application/*': ['.doc']
            'application/*': ['.doc', '.docx', '.pdf', '.ppt', '.pptx', '.tsv', '.xlsx'],
            'image/*': ['.jpeg', '.png', '.jpg', '.tiff'],
            'text/*': ['.csv', '.html', '.json', '.md', '.msg', '.txt', '.xml'],
        },
        onDrop
    });

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[540px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg">上传文件</h3>
            <p className="py-4">{desc}</p>
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="w-[440px]">
                    <div {...getRootProps()} className="h-[100px] border border-dashed flex justify-center items-center cursor-pointer">
                        <input {...getInputProps()} />
                        {isDragActive ? <p>将文件拖拽到这里上传</p> : <p>点击或将文件拖拽到这里上传</p>}
                    </div>
                    <div className=" max-h-[300px] overflow-y-auto no-scrollbar mt-4">
                        {progressList.map(pros => (
                            <div key={pros.id}>
                                <p className={`max-w-[300px] overflow-hidden text-ellipsis whitespace-nowrap ${pros.error && 'text-red-400'}`}>{pros.file.name}{pros.file.pros === 1 && <span>完成</span>}</p>
                                <Progress error={pros.error} value={pros.pros} className="w-full" />
                            </div>
                        ))}
                    </div>
                    <div className="grid gap-4 py-4">
                        <div className="grid grid-cols-4 items-center gap-4">
                            <Label htmlFor="name" className="text-right">文件切分大小</Label>
                            <Input id="name" value={size} onChange={(e) => setSize(e.target.value)} placeholder="切分大小" className="col-span-3" />
                        </div>
                    </div>
                    {/* <Tabs defaultValue="smart" className="w-full" onValueChange={(val) => chunkType.current = val}>
                        <TabsList className="">
                            <TabsTrigger value="smart" className="roundedrounded-xl">智能语义切分</TabsTrigger>
                            <TabsTrigger value="chunk">手动切分</TabsTrigger>
                        </TabsList>
                        <TabsContent value="smart">
                            <div className="grid gap-4 py-4">
                                <div className="grid grid-cols-4 items-center gap-4">
                                    <Label htmlFor="name" className="text-right">文件切分大小</Label>
                                    <Input id="name" value={size} onChange={(e) => setSize(e.target.value)} placeholder="切分大小" className="col-span-3" />
                                </div>
                            </div>
                        </TabsContent>
                        <TabsContent value="chunk">
                            <div className="grid gap-4 py-4">
                                <div className="grid grid-cols-4 items-center gap-4">
                                    <Label htmlFor="name" className="text-right">文件切分大小</Label>
                                    <Input id="name" value={size} onChange={(e) => setSize(e.target.value)} placeholder="切分大小" className="col-span-3" />
                                    <Label htmlFor="name" className="text-right">切分符号</Label>
                                    <Input id="name" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="切分符号" className="col-span-3" />
                                </div>
                            </div>
                        </TabsContent>
                    </Tabs> */}

                    <div className="flex justify-end gap-4">
                        <Button variant='outline' className="h-8" onClick={() => setOpen(false)}>取消</Button>
                        <Button type="submit" className="h-8" disabled={!end} onClick={() => !loading && handleSubmit()}>创建</Button>
                    </div>
                </div>
            </div>
        </form>
    </dialog>
};
