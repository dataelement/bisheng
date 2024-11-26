import { LoadIcon } from "@/components/bs-icons/loading";
import { Check, ChevronsRightIcon, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
                <span>查看日志</span>
                <span>
                    <ChevronsRightIcon size={18} />
                </span>
            </div>
            {open && (
                <div className="absolute top-0 left-full w-96 rounded-lg shadow-lg p-2 bg-[#F7F8FB] z-10">
                    <div className="flex justify-between items-center mb-2">
                        <div className="relative z-10 flex gap-2">
                            <NodeLogo type={type} colorStr={name} />
                            <span className="truncate block">{name}</span>
                        </div>
                        <X size={18} className="cursor-pointer" onClick={() => setOpen(false)} />
                    </div>
                    <div className="">
                        {data.map(item => <ResultText title={item.label} text={item.value} key={item.label} />)}
                    </div>
                </div>
            )}
        </div>
    );
};


export default function RunLog({ node, children }) {
    const [state, setState] = useState<Status>(Status.normal)
    const [data, setData] = useState<any[]>([])

    // 订阅日志事件
    useEffect(() => {
        const onNodeLogEvent = (e) => {
            const { nodeId, action, data } = e.detail
            if (nodeId !== node.id && nodeId !== '*') return

            setState(action)
            setData(data)
        }
        window.addEventListener('nodeLogEvent', onNodeLogEvent)
        return () => {
            window.removeEventListener('nodeLogEvent', onNodeLogEvent)
        }
    }, [])

    const noLog = useMemo(() => {
        return ['report', 'end'].includes(node.type)
    }, [node])

    if (state === Status.normal) return children

    if (state === Status.loading) return <div className='bisheng-node-top flex items-center'>
        <LoadIcon className="text-primary mr-2" />
        <span className='text-sm text-primary'>运行中</span>
    </div>

    if (state === Status.success) return < div className='bisheng-node-top flex justify-between bg-[#E6FBF1] [#FCEAEA]' >
        <div className='flex items-center gap-2 text-sm'>
            <div className='rounded-full w-4 h-4 bg-[#00C78C] text-gray-50 flex items-center justify-center'><Check size={14} /></div>
            <span>运行成功</span>
        </div>
        {!noLog && <Log type={node.type} name={node.name} data={data} />}
    </div>

    return <div className='bisheng-node-top flex justify-between bg-[#FCEAEA]'>
        <div className='flex items-center gap-2 text-sm'>
            <div className='rounded-full w-4 h-4 bg-[#F04438] text-gray-50 flex items-center justify-center'><X size={14} /></div>
            <span>运行失败</span>
        </div>
        {!noLog && <Log type={node.type} name={node.name} data={data} />}
    </div>
};
