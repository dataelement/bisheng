import { ChevronDownSquare, ChevronUpSquare } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { useEffect, useRef, useState } from "react";
import { Input } from "../../../components/ui/input";
import FileView from "./FileView";
import { getSourceChunksApi, splitWordApi } from "../../../controllers/API";
import { ChatMessageType } from "../../../types/chat";
import React from "react";

// 顶部答案区
const Anwser = ({ msg, onInit, onAdd }) => {
    const [html, setHtml] = useState('')
    const pRef = useRef(null)

    // init
    useEffect(() => {
        onInit([])
        msg && splitWordApi(msg).then((res) => {
            // 匹配
            const reg = new RegExp(`(${res.data.join('|')})`, 'g')
            setHtml(msg.replace(reg, '<span>$1</span>'))
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
const ResultPanne = ({ chatId, words, data, onClose, onAdd, children }: { chatId: string, words: string[], data: ChatMessageType, onClose: any, onAdd: any, children: any }) => {
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
    const [file, setFile] = useState(null)
    const loadFiles = () => {
        if (!words.length) return setFiles([])
        getSourceChunksApi(chatId, data.id, words.join(';')).then((_files) => {
            setFiles(_files)
            // 默认打开第一个文件
            _files && setFile(_files[0])
        })
    }

    useEffect(() => {
        loadFiles()
    }, [data, words])

    return <div className="flex gap-4 mt-4" style={{ height: 'calc(100vh - 10rem)' }}>
        {/* left */}
        <div className="w-[300px] bg-gray-100 rounded-md py-4 px-2 h-full overflow-y-auto no-scrollbar">
            {/* label */}
            <div className="flex flex-wrap gap-2">
                {words.map((str, i) => <div key={str} className="badge badge-info gap-2 text-gray-600">{str}<span className="cursor-pointer" onClick={() => onClose(i)}>x</span></div>)}
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
                {files.map(_file =>
                    <div key={_file.id} onClick={() => setFile(_file)} className={`rounded-xl bg-[#fff] hover:bg-gray-200 flex items-center px-4 mb-2 relative min-h-16 cursor-pointer ${file?.id === _file.id && 'bg-gray-200'}`}>
                        <p className="">{_file.fileName}</p>
                        <span className="absolute right-1 bottom-1 text-blue-400 text-sm">{_file.score}</span>
                    </div>
                )}
                {!files.length && <p className="text-sm text-center mt-10 text-gray-500">无匹配的源文件</p>}
            </div>
        </div>
        {/* file panne */}
        {file && children(file)}
    </div>
}

export default function ResouceModal({ chatId, data, open, setOpen }: { chatId: string, data: ChatMessageType, open: boolean, setOpen: (b: boolean) => void }) {
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
    const MemoizedFileView = React.memo(FileView);

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <div className=" rounded-xl px-4 py-6 bg-[#fff] shadow-lg dark:bg-background w-[80%]" onClick={e => e.stopPropagation()}>
            {open && <div>
                <Anwser msg={data.message || data.thought} onInit={setKeywords} onAdd={handleAddWord}></Anwser>
                <ResultPanne words={keywords} chatId={chatId} data={data} onClose={handleDelKeyword} onAdd={handleAddWord}>
                    {(file) => <MemoizedFileView data={file}></MemoizedFileView>}
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
