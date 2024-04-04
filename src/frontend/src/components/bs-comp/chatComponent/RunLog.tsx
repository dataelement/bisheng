import { LoadIcon } from "@/components/bs-icons/loading";
import { ToastIcon } from "@/components/bs-icons/toast";
import { cname } from "@/components/bs-ui/utils";
import { useAssistantStore } from "@/store/assistantStore";
import { CaretDownIcon } from "@radix-ui/react-icons";
import { useState } from "react";

export default function RunLog({ data }) {
    const [open, setOpen] = useState(false)

    // 该组件只有在助手测试页面用到，临时使用耦合方案，取 toollist来匹配 name
    const assistantState = useAssistantStore(state => state.assistantState)

    let lost = false
    let title = ''
    const status = data.end ? '已使用' : '正在使用'
    if (data.category === 'flow') {
        const flow = assistantState.flow_list?.find(flow => flow.id === data.message.tool_key)
        if (!flow) throw new Error('调试日志无法匹配到使用的技能详情，id:' + data.message.tool_key)

        lost = flow.status === 0
        title = lost ? `${flow.name} 已下线` : `${status} ${flow.name}`
    } else if (data.category === 'tool') {
        const tool = assistantState.tool_list?.find(tool => tool.tool_key === data.message.tool_key)
        if (!tool) throw new Error('调试日志无法匹配到使用的工具详情，id:' + data.message.tool_key)

        title = `${status} ${tool.name}`
    } else if (data.category === 'knowledge') {
        title = `${data.end ? '已搜索' : '正在搜索'} 知识库`
    }

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="flex justify-between items-center px-4 py-2 shadow-xl cursor-pointer" onClick={() => setOpen(!open)}>
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        data.end ? <ToastIcon type={lost ? 'error' : 'success'} /> :
                            <LoadIcon className="text-primary duration-300" />
                    }
                    <span>{title}</span>
                </div>
                <CaretDownIcon className={open && 'rotate-180'} />
            </div>
            <div className={cname('bg-gray-100 px-4 py-2 text-gray-500 overflow-hidden text-sm ', open ? 'h-auto' : 'h-0 p-0')}>
                <p>{data.thought}</p>
            </div>
        </div>
    </div>
};
