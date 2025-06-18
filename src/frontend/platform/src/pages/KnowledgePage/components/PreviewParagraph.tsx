import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import Tip from "@/components/bs-ui/tooltip/tip";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { cn } from "@/util/utils";
import { debounce } from "lodash-es";
import { CircleX, FileCode, LocateFixed } from "lucide-react";
import { forwardRef, useCallback, useContext, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import AceEditor from "react-ace";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import Vditor from 'vditor';
import 'vditor/dist/index.css';
import useKnowledgeStore from "../useKnowledgeStore";
import { locationContext } from "@/contexts/locationContext";

export const MarkdownView = ({ noHead = false, data }) => {
    const text = useMemo(() =>
        data.text.replaceAll(/(\n\s{4,})/g, '\n   ') // 禁止4空格转代码
            .replace(/(?<![\n\|])\n(?!\n)/g, '\n\n')
        , [data.text])

    return <div className="p-4 bg-white rounded-lg shadow-sm border border-gray-200 hover:shadow-md hover:border-primary transition-shadow w-full">
        {!noHead && <p className="text-sm text-gray-500 flex gap-2 mb-1">
            <span>分段{data.chunkIndex + 1}</span>
            <span>-</span>
            <span>{data.text.length} 字符</span>
        </p>}
        <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeMathjax]}
            linkTarget="_blank"
            className="react-markdown inline-block break-all max-w-full text-sm text-gray-500"
            components={{
                code: ({ node, inline, className, children, ...props }) => {
                    if (children.length) {
                        if (children[0] === "▍") {
                            return (<span className="form-modal-markdown-span"> ▍ </span>);
                        }
                        if (typeof children[0] === "string") {
                            children[0] = children[0].replace("▍", "▍");
                        }
                    }
                    // className 区分代码语言 python json js 
                    const match = /language-(\w+)/.exec(className || "");

                    return !inline ? (
                        <CodeBlock
                            key={Math.random()}
                            language={(match && match[1]) || ""}
                            value={String(children).replace(/\n$/, "")}
                            {...props}
                        />
                    ) : (
                        <code className={className} {...props}> {children} </code>
                    );
                },
            }}
        >
            {text}
        </ReactMarkdown>
    </div>
}

// 原始编辑
const AceEditorCom = ({ markdown, hidden, onChange, onBlur }) => {
    if (hidden) return null

    return <AceEditor
        value={markdown || ''}
        mode="markdown"
        theme={"github"}
        highlightActiveLine={false}
        showPrintMargin={false}
        fontSize={14}
        showGutter={false}
        enableLiveAutocompletion
        name="CodeEditor"
        onChange={onChange}
        onBlur={(e) => onBlur(markdown, () => {
            // 为空时恢复上一次数据
        })}
        onValidate={(e) => console.error('ace validate :>> ', e)}
        className="h-full w-full min-h-80 text-gray-500"
    />
}

// 预览编辑
const VditorEditor = forwardRef(({ defalutValue, hidden, onBlur, onChange }, ref) => {
    const vditorRef = useRef(null);
    const readyRef = useRef(false); // 保证vditor初始化完成后,再调用实例方法,否则报错 Cannot read properties of undefined (reading 'currentMode')
    const valurCacheRef = useRef('');
    const domRef = useRef(null);

    // 处理hook  blur闭包
    const blurRef = useRef(onBlur);
    blurRef.current = onBlur;

    useEffect(() => {
        // console.log('markdown :>> ', markdown);
        const processedMarkdown = defalutValue
            .replace(/^( {4,})/gm, '   ')
        if (!hidden && vditorRef.current && readyRef.current) {
            vditorRef.current.setValue(processedMarkdown);
        } else {
            valurCacheRef.current = processedMarkdown;
        }
    }, [hidden])

    useImperativeHandle(ref, () => ({
        setValue(val) {
            const processedMarkdown = val.replace(/^( {4,})/gm, '   ')
            if (readyRef.current) {
                vditorRef.current?.setValue(processedMarkdown)
            } else {
                valurCacheRef.current = processedMarkdown;
            }
        }
    }))

    useEffect(() => {
        vditorRef.current = new Vditor(domRef.current, {
            cdn: location.origin + '/vditor',
            height: '100%',
            toolbarConfig: {
                hide: true,
                pin: true, 
            },
            mode: 'ir',  // 'sv' for split view, 'ir' for instant rendering
            preview: {
                hljs: {
                    style: ''
                },
                markdown: {
                    toc: true,
                    mark: true,
                },
                math: {
                    "inlineDigit": true
                }
            },
            cache: {
                enable: false,
            },
            after: () => {
                console.log('Vditor is ready');
                readyRef.current = true;

                if (valurCacheRef.current) {
                    vditorRef.current?.setValue(valurCacheRef.current);
                }
                // vditorRef.current.disabled();
            },
            // input: onChange, // 有延时
            blur: () => {
                const value = vditorRef.current?.getValue()
                blurRef.current(
                    value,
                    () => {
                        // 还原
                        const processedMarkdown = defalutValue.replace(/^( {4,})/gm, '   ')
                        vditorRef.current?.setValue(processedMarkdown);
                    }
                );
                onChange(value);
            },
        });

        return () => {
            vditorRef.current?.destroy();
        };
    }, []);

    return <div ref={domRef} className={`${hidden ? 'hidden' : ''} overflow-y-auto border-none file-vditor`}></div>;
});

const EditMarkdown = ({ data, active, fileSuffix, onClick, onDel, onChange, onPositionClick }) => {
    const [edit, setEdit] = useState(false); // 编辑原始格式
    const { appConfig } = useContext(locationContext)

    const [value, setValue] = useState(data.text) // 不支持动态更新,更新文本请重新创建该组件
    const setDebounceValue = useCallback(debounce((value) => {
        setValue(value)
    }, 30), [setValue])
    // 强制覆盖chunk
    const needCoverData = useKnowledgeStore((state) => state.needCoverData);
    const vditorRef = useRef(null);
    useEffect(() => {
        const { index, txt } = needCoverData
        if (data.chunkIndex === index) {
            vditorRef.current.setValue(txt)
            onChange(data.chunkIndex, txt)
        }
    }, [needCoverData])

    const { toast } = useToast()
    const handleBlur = (newValue, restore) => {
        if (!value.trim() || newValue.trim() === '') {
            setValue(data.text)
            restore?.()
            return toast({
                variant: 'error',
                title: '操作失败',
                description: '分段内容不可为空',
            })
        }

        if (data.text === newValue) return // 无需保存
        onChange(data.chunkIndex, newValue)
    }

    return <div
        className={cn("group p-4 py-3 bg-white rounded-lg shadow-sm border border-gray-200 hover:shadow-md hover:border-primary transition-shadow w-full",
            active && 'border-primary')
        }
        onClick={(e) => {
            e.stopPropagation()
            onClick(data.chunkIndex)
        }}
    >
        <div className="text-sm text-gray-500 flex gap-2 justify-between mb-1">
            <div className="flex gap-2 items-center">
                <span>分段{data.chunkIndex + 1}</span>
                <span>-</span>
                <span>{data.text.length} 字符</span>
                <div className="flex gap-2 justify-center items-center">
                    {
                        fileSuffix === 'pdf' && appConfig.enableEtl4lm && <Tip content={"点击定位到原文件"} side={"top"}  >
                            <Button
                                size="icon"
                                variant="ghost"
                                className={cn("size-6 text-primary opacity-0 group-hover:opacity-100")}
                                onClick={onPositionClick}
                            ><LocateFixed size={18} /></Button>
                        </Tip>
                    }
                    {edit
                        ? <div
                            className={cn("size-6 text-primary flex justify-center items-center rounded-sm cursor-pointer opacity-0 group-hover:opacity-100", edit && 'bg-primary text-gray-50')}
                            onClick={() => setEdit(!edit)}><FileCode size={18} /></div>
                        : <Tip content={"点击展示Markdown原文，进行编辑"} side={"top"}  >
                            <div
                                className={cn("size-6 text-primary flex justify-center items-center rounded-sm cursor-pointer opacity-0 group-hover:opacity-100", edit && 'bg-primary text-gray-50')}
                                onClick={() => setEdit(!edit)}><FileCode size={18} /></div>
                        </Tip>}
                </div>
            </div>
            <Tip content={"点击删除分段"} side={"top"}  >
                <Button
                    size="icon"
                    variant="ghost"
                    className={cn("size-6 text-primary opacity-0 group-hover:opacity-100")}
                    onClick={() => onDel(data.chunkIndex, data.text)}
                ><CircleX size={18} /></Button>
            </Tip>
        </div>

        {/* 所见即所得Markdown编辑器 */}
        <VditorEditor ref={vditorRef} hidden={edit} defalutValue={value} onChange={setDebounceValue} onBlur={handleBlur} />
        {/* 普通Markdown编辑器 */}
        <AceEditorCom hidden={!edit} markdown={value} onChange={setDebounceValue} onBlur={handleBlur} />
    </div>
}

// 分段结果列表
export default function PreviewParagraph({ fileId, previewCount, edit, fileSuffix, loading, chunks, onDel, onChange }) {
    const containerRef = useRef(null);
    const [visibleItems, setVisibleItems] = useState(10); // 初始加载数量
    const loadingRef = useRef(false);
    // 选中的分段
    const [selectedChunkIndex, setSelectedChunkIndex, setSelectedChunkDistanceFactor] = useKnowledgeStore((state) => [state.selectedChunkIndex, state.setSelectedChunkIndex, state.setSelectedChunkDistanceFactor]);
    useEffect(() => {
        const fun = () => setSelectedChunkIndex(-1) // 失焦
        document.addEventListener('click', fun)
        return () => document.removeEventListener('click', fun)
    }, [])

    // 懒加载逻辑
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        setVisibleItems(10)

        const handleScroll = () => {
            if (
                !loadingRef.current &&
                container.scrollHeight - container.scrollTop <= container.clientHeight + 100
            ) {
                loadingRef.current = true;
                setVisibleItems(prev => Math.min(prev + 10, chunks.length));
                setTimeout(() => { loadingRef.current = false }, 300);
            }
        };
        container.addEventListener('scroll', handleScroll);
        return () => container.removeEventListener('scroll', handleScroll);
    }, [chunks.length]);

    return <div className="w-full pt-3 pb-10 relative ">
        {loading && (
            <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>
        )}
        <div ref={containerRef} className="h-[calc(100vh-284px)] overflow-y-auto"
            style={{ scrollbarWidth: 'thin' }}
        >
            <div className="space-y-6">
                {chunks.slice(0, visibleItems).map((chunk) => (
                    edit
                        ? <EditMarkdown
                            key={fileId + previewCount + chunk.chunkIndex}
                            data={chunk}
                            fileSuffix={fileSuffix}
                            active={selectedChunkIndex === chunk.chunkIndex}
                            onClick={setSelectedChunkIndex}
                            onPositionClick={setSelectedChunkDistanceFactor}
                            onDel={onDel}
                            onChange={onChange}
                        />
                        : <MarkdownView key={fileId + previewCount + chunk.chunkIndex} data={chunk} />
                ))}
                {!(chunks.length || loading) && <div className="p-4 bg-white rounded-lg shadow-sm border border-gray-200 hover:shadow-md hover:border-primary transition-shadow text-sm text-gray-500 flex gap-2 mb-1"
                >文档解析失败</div>}
            </div>
        </div>
    </div>
};
