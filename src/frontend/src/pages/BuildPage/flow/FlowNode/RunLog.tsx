import { LoadIcon } from "@/components/bs-icons/loading";
import { Check, ChevronsRightIcon, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import NodeLogo from "./NodeLogo";
import { ResultText } from "./RunTest";

const enum Status {
    normal = 'normal',
    loading = 'loading',
    success = 'success',
    error = 'error'
}

const Log = ({ type, name, data }) => {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const { t } = useTranslation('flow')

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
                    <div className="">
                        {Object.keys(data).map(key => <ResultText title={key} value={data[key]} key={key} />)}
                    </div>
                </div>
            )}
        </div>
    );
};


export default function RunLog({ node, children }) {
    const [state, setState] = useState<Status>(Status.normal)
    const [data, setData] = useState<any>({})
    const { t } = useTranslation('flow')

    // 订阅日志事件
    useEffect(() => {
        const onNodeLogEvent = (e) => {
            const { nodeId, action, data } = e.detail
            if (nodeId !== node.id && nodeId !== '*') return

            if (data) {
                // newData  key: {id: value}
                const newData = data.reduce((res, item) => {
                    if (item.type === 'variable') {
                        const key = item.key.split('.')
                        res[key[key.length - 1]] = item.value
                    } else {
                        res[item.key] = item.value
                    }
                    return res
                }, {})
                let result = {};
                let hasKeys = []

                node.group_params.forEach(group => {
                    group.params.forEach(param => {
                        if (newData[param.key] !== undefined) {
                            result[param.label || param.key] = newData[param.key];
                            hasKeys.push(param.key)
                        } else if (param.key === 'tool_list') {
                            // tool
                            param.value.some(p => {
                                if (newData[p.tool_key] !== undefined) {
                                    result[p.label] = newData[p.tool_key];
                                    hasKeys.push(p.tool_key)
                                    return true
                                }
                            })
                        } else if (Array.isArray(param.value) && param.value.some(el => newData[el.key])) {
                            // 尝试去value中匹配
                            const value = param.value.find(el => newData[el.key])
                            result[value.label] = newData[value.key];
                            hasKeys.push(value.key)
                        }
                    });
                });

                for (let key in newData) {
                    if (!hasKeys.includes(key)) {
                        result[key] = newData[key];
                    }
                }
                setData(result)
            }
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
