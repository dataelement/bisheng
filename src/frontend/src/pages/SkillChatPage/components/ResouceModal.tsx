import { ChevronDownSquare, ChevronUpSquare } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { useEffect, useRef, useState } from "react";
import { Input } from "../../../components/ui/input";

export default function ResouceModal({ open, setOpen }) {
    // keyword
    const [keywords, setKeywords] = useState([])
    const [editCustomKey, setEditCustomKey] = useState(false)
    const inputRef = useRef(null)

    const handleAddKeyword = (str: string) => {
        setEditCustomKey(false)
        if (!str) return
        setKeywords(wds => wds.find(el => el === str) ? wds : [...wds, str])
        if (inputRef.current) inputRef.current.value = ''
    }

    const handleDelKeyword = (index: number) => {
        setKeywords(keywords.filter((wd, i) => i !== index))
    }

    // 文件
    const [files, setFiles] = useState([])

    const loadFiles = () => {
        const arr = [
            { name: 'studio使用手册', chunk: 2 },
            { name: 'STUDIO使用手册STUDIO使用手册STUDIO使用手册', chunk: 1 },
            { name: 'MFp使用手册', chunk: 3 }
        ]
        setFiles(arr.splice(0, keywords.length + 1))
    }

    useEffect(() => {
        loadFiles()
    }, [keywords])

    // 记忆
    useEffect(() => {
        const KEYWORDS_LOCAL_KEY = 'KEYWORDS_LOCAL'
        setKeywords(JSON.parse(localStorage.getItem(KEYWORDS_LOCAL_KEY) || '[]'))

        return () => localStorage.setItem(KEYWORDS_LOCAL_KEY, JSON.stringify(keywords))
    }, [])

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <div className=" rounded-xl px-4 py-6 bg-[#fff] shadow-lg dark:bg-background w-[80%]" onClick={e => e.stopPropagation()}>
            <div className="bg-gray-100 rounded-md py-4 px-2">
                <p className="anwser-souce"><span onClick={() => handleAddKeyword('评测集')}>评测集</span>是用于评估场景准确率的数据集，其中包含了该场景的<span onClick={() => handleAddKeyword('标准答案')}>标准答案</span>。评测集用于对模型或系统的性能进行评估和比较。在评测集中，用户需要对样本进行标注，将正确的标注结果作为评测准确率的标准答案。通过评估模型在评测集上的表现，可以了解其准确率和性能。
                </p>
            </div>
            <div className="flex gap-4 mt-4" style={{ height: 'calc(100vh - 10rem)' }}>
                {/* left */}
                <div className="w-[300px] bg-gray-100 rounded-md py-4 px-2 h-full overflow-y-auto no-scrollbar">
                    {/* label */}
                    <div className="flex flex-wrap gap-2">
                        {keywords.map((str, i) => <div key={str} className="badge badge-info gap-2"><span className="cursor-pointer" onClick={() => handleDelKeyword(i)}>x</span>{str}</div>)}
                        {
                            editCustomKey ? <div className="badge badge-info gap-2 cursor-pointer"><Input ref={inputRef} className="w-20 h-4 py-0"
                                onKeyDown={(event) => {
                                    if (event.key === "Enter" && !event.shiftKey) {
                                        handleAddKeyword(inputRef.current.value);
                                    }
                                }}
                                onBlur={() => {
                                    handleAddKeyword(inputRef.current.value);
                                }}></Input></div> :
                                <div className="badge badge-info gap-2 cursor-pointer" onClick={() => setEditCustomKey(true)}><span>+自定义</span></div>
                        }
                    </div>
                    {/* files */}
                    <div className="mt-4">
                        {files.map(file =>
                            <div key={file.name} className="rounded-xl bg-[#fff] hover:bg-gray-200 flex items-center px-4 mb-2 relative min-h-16 cursor-pointer">
                                <p className="">{file.name}</p>
                                <span className="absolute right-1 bottom-1 text-blue-400 text-sm">chunk {file.chunk}</span>
                            </div>
                        )}
                    </div>
                </div>
                {/* file panne */}
                <div className="flex-1 bg-gray-100 rounded-md py-4 px-2 relative">
                    <div className="file-view"></div>
                    <div className="absolute right-2 top-2 flex flex-col">
                        <Button variant="ghost" className=""><ChevronUpSquare /></Button>
                        <Button variant="ghost" disabled><ChevronDownSquare /></Button>
                    </div>
                </div>
            </div>
        </div>
    </dialog>
};
