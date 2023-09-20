import { ChevronDownSquare, ChevronUpSquare } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { useEffect, useRef, useState } from "react";
import { Input } from "../../../components/ui/input";
import FileView from "./FileView";
import { getSourceChunksApi, splitWordApi } from "../../../controllers/API";

// 
const Anwser = ({ id, onInit, onAdd }) => {
    const [html, setHtml] = useState('')
    const pRef = useRef(null)

    // init
    useEffect(() => {
        onInit([])
        const testStr = '评测集是用于评估场景准确率的数据集，其中包含了该场景的标准答案。评测集用于对模型或系统的性能进行评估和比较。在评测集中，用户需要对样本进行标注，将正确的标注结果作为评测准确率的标准答案。通过评估模型在评测集上的表现，可以了解其准确率和性能。'
        testStr && splitWordApi(testStr).then((res) => {
            // 匹配
            const reg = new RegExp(`(${res.data.join('|')})`, 'g')
            setHtml(testStr.replace(reg, '<span>$1</span>'))
            onInit(res.data)
        })
    }, [])

    // add 
    useEffect(() => {
        const handleclick = (e) => {
            if (e.target.tagName === 'SPAN') {
                onAdd(e.target.innerText)
            }
        }
        pRef.current.addEventListener('click', handleclick)
        return () => pRef.current?.removeEventListener('click', handleclick)
    }, [])

    return <div className="bg-gray-100 rounded-md py-4 px-2">
        <p ref={pRef} className="anwser-souce" dangerouslySetInnerHTML={{ __html: html }}></p>
    </div>
}

// 
const ResultPanne = ({ data, onClose, onAdd }) => {
    const [editCustomKey, setEditCustomKey] = useState(false)
    const inputRef = useRef(null)

    const handleAddKeyword = (str: string) => {
        setEditCustomKey(false)
        if (!str) return
        if (inputRef.current) inputRef.current.value = ''
        onAdd(str)
    }

    // 文件s
    const [files, setFiles] = useState([])
    const [file, setFile] = useState({})
    const loadFiles = () => {
        if (!data.length) return setFiles([])
        getSourceChunksApi('1', '1', data.join(';')).then(res => {
            console.log('res :>> ', res);
        })
        const arr = [
            { name: 'studio使用手册', chunk: 2 },
            { name: 'STUDIO使用手册STUDIO使用手册STUDIO使用手册', chunk: 1 },
            { name: 'MFp使用手册', chunk: 3 }
        ]
        setFiles(arr.splice(0, data.length + 1))
    }

    useEffect(() => {
        loadFiles()
    }, [data])

    return <div className="flex gap-4 mt-4" style={{ height: 'calc(100vh - 10rem)' }}>
        {/* left */}
        <div className="w-[300px] bg-gray-100 rounded-md py-4 px-2 h-full overflow-y-auto no-scrollbar">
            {/* label */}
            <div className="flex flex-wrap gap-2">
                {data.map((str, i) => <div key={str} className="badge badge-info gap-2 text-gray-600">{str}<span className="cursor-pointer" onClick={() => onClose(i)}>x</span></div>)}
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
                        <div className="badge badge-info gap-2 cursor-pointer font-bold text-gray-600" onClick={() => setEditCustomKey(true)}><span>+自定义</span></div>
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
                {!files.length && <p className="text-sm text-center mt-10 text-gray-500">无匹配的源文件</p>}
            </div>
        </div>
        {/* file panne */}
        {/* {children()} */}
    </div>
}

export default function ResouceModal({ id, open, setOpen }) {
    // labels
    const [keywords, setKeywords] = useState([])
    const handleAddWord = (word: string) => {
        // 去重 更新
        setKeywords(oldWords => oldWords.find(wd => wd === word) ? oldWords : [...oldWords, word])
    }

    const handleDelKeyword = (index: number) => {
        setKeywords(keywords.filter((wd, i) => i !== index))
    }

    // 记忆
    // useEffect(() => {
    //     const KEYWORDS_LOCAL_KEY = 'KEYWORDS_LOCAL'
    //     setKeywords(JSON.parse(localStorage.getItem(KEYWORDS_LOCAL_KEY) || '[]'))

    //     return () => localStorage.setItem(KEYWORDS_LOCAL_KEY, JSON.stringify(keywords))
    // }, [])

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <div className=" rounded-xl px-4 py-6 bg-[#fff] shadow-lg dark:bg-background w-[80%]" onClick={e => e.stopPropagation()}>
            {open && <div>
                <Anwser id={id} onInit={setKeywords} onAdd={handleAddWord}></Anwser>
                <ResultPanne data={keywords} onClose={handleDelKeyword} onAdd={handleAddWord}>
                    {/* {() => <FileView></FileView>} */}
                </ResultPanne>
            </div>}
        </div>
    </dialog>
};

// const useRefState = (state) => {
//     const [data, setData] = useState(state)
//     const ref = useRef(state)
//     return [data, ref, (nState) => {
//         setData(nState)
//         ref.current = nState
//     }]
// }
