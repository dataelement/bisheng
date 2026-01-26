import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import Tip from "@/components/bs-ui/tooltip/tip";
import { locationContext } from "@/contexts/locationContext";
import MessageMarkDown from "@/pages/BuildPage/flow/FlowChat/MessageMarkDown";
import { cn } from "@/util/utils";
import { debounce } from "lodash-es";
import { CircleX, FileCode, LocateFixed } from "lucide-react";
import { forwardRef, useCallback, useContext, useEffect, useImperativeHandle, useRef, useState } from "react";
import AceEditor from "react-ace";
import Vditor from 'vditor';
import 'vditor/dist/index.css';
import useKnowledgeStore from "../useKnowledgeStore";
// 新增：引入国际化hooks
import { useTranslation } from "react-i18next";
import { useMiniDebounce } from "@/util/hook";

export const MarkdownView = ({ noHead = false, data }) => {
    // 新增：使用knowledge命名空间的国际化
    const { t } = useTranslation('knowledge');

    return <div className="p-4 bg-main rounded-lg shadow-sm border border-gray-200 hover:shadow-md hover:border-primary transition-shadow w-full">
        {!noHead && <p className="text-sm text-gray-500 flex gap-2 mb-1">
            <span>{t('chunk')}{data.chunkIndex + 1}</span>
            <span>-</span>
            <span>{data.text.length} {t('characters')}</span>
        </p>}
        <MessageMarkDown message={data.text} />
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
            cdn: location.origin + __APP_ENV__.BASE_URL + '/vditor',
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
            // 1. 校验实例存在 + 初始化完成 + DOM节点存在
            if (vditorRef.current && readyRef.current && domRef.current) {
                try {
                    vditorRef.current.destroy(); // 仅在安全状态下执行销毁
                } catch (error) {
                    console.warn('Vditor销毁时发生异常:', error); // 捕获异常避免阻断流程
                }
            }
            // 2. 清空引用，释放内存
            vditorRef.current = null;
            readyRef.current = false;
        };
    }, []);

    return <div ref={domRef} className={`${hidden ? 'hidden' : ''} overflow-y-auto border-none file-vditor`}></div>;
});

const EditMarkdown = ({ data, active, oneLeft, fileSuffix, onClick, onDel, onChange, onPositionClick }) => {
    const { t } = useTranslation('knowledge');

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
        const _value = value.trim()
        const _newValue = newValue.trim()
        if (!_value || _newValue === '') {
            setValue(data.text)
            restore?.()
            return toast({
                variant: 'error',
                title: t('operationFailed'),
                description: t('chunkContentCannotBeEmpty'),
            })
        }
        // Edit mode does not judge 
        if (!edit && _value === _newValue) return // 无需保存
        // chunk diff
        onChange(data.chunkIndex, newValue)
    }
    const handleBlurDebounced = useMiniDebounce(handleBlur, 300)

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
                <span>{t('chunk')}{data.chunkIndex + 1}</span>
                <span>-</span>
                <span>{data.text.length} {t('characters')}</span>
                <div className="flex gap-2 justify-center items-center">
                    {
                        fileSuffix === 'pdf' && appConfig.enableEtl4lm && <Tip content={t('clickLocateOriginalFile')} side={"top"}  >
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
                        : <Tip content={t('clickShowMarkdownEdit')} side={"top"}  >
                            <div
                                className={cn("size-6 text-primary flex justify-center items-center rounded-sm cursor-pointer opacity-0 group-hover:opacity-100", edit && 'bg-primary text-gray-50')}
                                onClick={() => setEdit(!edit)}><FileCode size={18} /></div>
                        </Tip>}
                </div>
            </div>
            {!oneLeft &&
                <Tip content={t('clickDeleteChunk')} side={"top"}  >
                    <Button
                        size="icon"
                        variant="ghost"
                        className={cn("size-6 text-primary opacity-0 group-hover:opacity-100")}
                        onClick={() => onDel(data.chunkIndex, data.text)}
                    ><CircleX size={18} /></Button>
                </Tip>
            }
        </div>

        {/* 所见即所得Markdown编辑器 */}
        <VditorEditor ref={vditorRef} hidden={edit} defalutValue={value} onChange={setDebounceValue} onBlur={handleBlurDebounced} />
        {/* 普通Markdown编辑器 */}
        <AceEditorCom hidden={!edit} markdown={value} onChange={setDebounceValue} onBlur={handleBlurDebounced} />
    </div>
}

// 分段结果列表
export default function PreviewParagraph({ fileId, page = 1, previewCount, edit, fileSuffix, loading, chunks, className, onDel, onChange }) {
    const { t } = useTranslation('knowledge');

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

    useEffect(() => {
        // 1. 重置懒加载计数（避免显示旧文件的前 N 项）
        setVisibleItems(10);
        // 2. 重置选中的分段（避免跨文件选中旧分段）
        setSelectedChunkIndex(-1);
        // 3. 重置滚动位置（避免新文件显示旧文件的滚动位置）
        if (containerRef.current) {
            containerRef.current.scrollTop = 0;
        }
    }, [page, fileId, setSelectedChunkIndex]);

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

    return <div className="pt-3 relative w-full">
        {loading && (
            <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>
        )}
        <div ref={containerRef} className={`${className} overflow-y-auto`}
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
                            oneLeft={chunks.length === 1}
                            onDel={onDel}
                            onChange={onChange}
                        />
                        : <MarkdownView key={fileId + previewCount + chunk.chunkIndex} data={chunk} />
                ))}
                {!(chunks.length || loading) && <div className="p-4 bg-white rounded-lg shadow-sm border border-gray-200 hover:shadow-md hover:border-primary transition-shadow text-sm text-gray-500 flex gap-2 mb-1">
                    {t('noAnalysisResult')}
                </div>}
            </div>
        </div>
    </div>
};