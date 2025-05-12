import { LoadIcon } from "@/components/bs-icons/loading";
import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "@/components/bs-ui/select";
import { downloadFile } from "@/util/utils";
import { Check, ChevronsRightIcon, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../flowStore";
import NodeLogo from "./NodeLogo";
import { ResultText } from "./RunTest";

const enum Status {
    normal = 'normal',
    loading = 'loading',
    success = 'success',
    error = 'error'
}

// 日志组件
export default function RunLog({ node, children }) {
    const [state, setState] = useState<Status>(Status.normal)
    const setRunCache = useFlowStore(state => state.setRunCache) // 缓存TODO
    const [data, setData] = useState<any>([])
    const { t } = useTranslation('flow')
    // 订阅日志事件
    useEffect(() => {
        const buildData = (data) => {
            if (data) {
                /**
                 * newData
                 * key: {type, value}  
                 * "current_time": {type: "param", value: "2023-11-20 16:00:00"}
                 */
                const newData = data.reduce((res, item) => {
                    if (['file', 'variable'].includes(item.type)) {
                        const key = item.key.split('.')
                        res.set(key[key.length - 1], { type: item.type, label: '', value: item.value });
                    } else {
                        res.set(item.key, { type: item.type, label: '', value: item.value });
                    }
                    return res;
                }, new Map()); // 使用 Map 保持插入顺序

                let hasKeys = [];
                const isFormInputNode = node.type === 'input' && node.tab.value === 'form_input'
                // 根据node params替换newData的key值 替换为name
                node.group_params.forEach(group => {
                    group.params.forEach(param => {
                        // 尝试去value中匹配 (input-form; preset-quesitons)
                        if (Array.isArray(param.value) && param.value.some(el => newData.has(el.key))) {
                            param.value.forEach(value => {
                                if (!newData.has(value.key)) return;
                                newData.get(value.key)['label'] = value.label || value.key;
                                hasKeys.push(value.key);
                            });
                        } else if (newData.has(param.key)) {
                            if (param.hidden) return newData.delete(param.key);
                            newData.get(param.key)['label'] = param.label || param.key;
                            hasKeys.push(param.key);
                        } else if (param.key === 'tool_list') {
                            // tool
                            param.value.some(p => {
                                if (newData.has(p.tool_key)) {
                                    newData.get(p.tool_key)['label'] = p.label;
                                    hasKeys.push(p.tool_key);
                                }
                            });
                        } else if (isFormInputNode && param.key === 'form_input') {
                            param.value.forEach(value => {
                                value.file_type === 'file' && newData.delete(value.image_file);
                            })
                        }
                    });
                });

                return Array.from(newData.entries()).map(([key, value]) => ({
                    label: ['file', 'variable'].includes(value.type) && !key.startsWith('output_') ? key : value.label || key,
                    type: value.type,
                    value: value.value,
                }))
            }
        }

        const onNodeLogEvent = (e) => {
            const { nodeId, action, data } = e.detail
            if (nodeId !== node.id && nodeId !== '*') return
            data && setData(data.map(d => buildData(d)))
            setState(action)
        }
        window.addEventListener('nodeLogEvent', onNodeLogEvent)
        return () => {
            window.removeEventListener('nodeLogEvent', onNodeLogEvent)
        }
    }, [])

    const noLog = useMemo(() => {
        return ['report', 'end'].includes(node.type)
    }, [node])

    if (state === Status.normal) return children;

    if (state === Status.loading) return (
        <div className='bisheng-node-top flex items-center'>
            <LoadIcon className="text-primary mr-2" />
            <span className='text-sm text-primary'>{t('running')}</span>
        </div>
    );

    if (state === Status.success) return (
        <div className='bisheng-node-top flex justify-between bg-[#E6FBF1] dark:bg-[#303134]'>
            <div className='flex items-center gap-2 text-sm'>
                <div className='rounded-full w-4 h-4 bg-[#00C78C] text-gray-50 flex items-center justify-center'><Check size={14} /></div>
                <span>{t('runSuccess')}</span>
            </div>
            {!noLog && <Log type={node.type} name={node.name} data={data} />}
        </div>
    );

    return (
        <div className='bisheng-node-top flex justify-between bg-[#FCEAEA] dark:bg-[#303134]'>
            <div className='flex items-center gap-2 text-sm'>
                <div className='rounded-full w-4 h-4 bg-[#F04438] text-gray-50 flex items-center justify-center'><X size={14} /></div>
                <span>{t('runFailed')}</span>
            </div>
            {!noLog && <Log type={node.type} name={node.name} data={data} />}
        </div>
    );
};


// 日志模板
const Log = ({ type, name, data }) => {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const { t } = useTranslation('flow')
    const [currentIndex, setCurrentIndex] = useState(0)
    // key
    const currentData = useMemo(() =>
        data[currentIndex] || [], [data, currentIndex]
    )

    const handleClickOutside = (event) => {
        if (ref.current && !ref.current.contains(event.target)) {
            setOpen(false);
        }
    };

    useEffect(() => {
        if (open) {
            document.addEventListener("click", handleClickOutside);
        } else {
            document.removeEventListener("click", handleClickOutside);
        }
        return () => {
            document.removeEventListener("click", handleClickOutside);
        };
    }, [open]);

    return (
        <div className="relative" ref={ref}>
            <div
                className="flex items-center text-primary text-sm cursor-pointer"
                onClick={() => setOpen(!open)}
            >
                <span><span>{t('viewLogs')}</span></span>
                <span>
                    <ChevronsRightIcon size={18} />
                </span>
            </div>
            {open && (
                <div className="absolute top-0 left-full w-96 rounded-lg shadow-lg p-2 bg-[#F7F8FB] dark:bg-[#303134] z-10">
                    <div className="flex justify-between items-center mb-2">
                        <div className="relative z-10 flex gap-2">
                            <NodeLogo type={type} colorStr={name} />
                            <span className="truncate block">{name}</span>
                        </div>
                        <X size={18} className="cursor-pointer" onClick={() => setOpen(false)} />
                    </div>
                    {data.length > 1 && <div className="mb-2">
                        <Select value={currentIndex + ""} onValueChange={(val => setCurrentIndex(Number(val)))}>
                            <SelectTrigger className="w-[180px]">
                                {/* <SelectValue /> */}
                                <span>第 {currentIndex + 1} 轮运行结果</span>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    {
                                        data.map((_, index) => <SelectItem key={index} value={index + ""}>第 {index + 1} 轮运行结果</SelectItem>)
                                    }
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>}
                    <div className="">
                        {currentData.map((item) => item.type === 'file' ?
                            <ResultFile title={item.label} name={name} fileUrl={item.value} key={item.label + currentIndex} />
                            : <ResultText title={item.label} value={item.value} key={item.label + currentIndex} />)}
                    </div>
                </div>
            )}
        </div>
    );
};

// 下载文件
export const ResultFile = ({ title, name, fileUrl }: { title: string, name: string, fileUrl: string }) => {
    const { flow } = useFlowStore();

    const handleDownload = (e) => {
        downloadFile(fileUrl, `${flow.name}_${name}_检索结果`)
    }

    return <div className="mb-2 rounded-md border bg-search-input text-sm shadow-sm">
        <div className="border-b px-2 flex justify-between items-center">
            <p>{title}</p>
        </div>
        <textarea defaultValue={'检索结果过长,请下载后查看'} disabled className="w-full h-12 p-2 block text-muted-foreground dark:bg-black " />
        <Button onClick={handleDownload} className="h-6 mt-2">下载完整内容</Button>
    </div>
}