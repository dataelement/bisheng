import { LoadIcon } from "@/components/bs-icons/loading";
import { ToastIcon } from "@/components/bs-icons/toast";
import { cname } from "@/components/bs-ui/utils";
import { useAssistantStore } from "@/store/assistantStore";
import { CaretDownIcon } from "@radix-ui/react-icons";
import { useState } from "react";

export default function RunLog({ data }) {
    const [open, setOpen] = useState(false)

    // 该组件只有在助手测试页面用到，临时使用耦合方案，取 toollist来匹配 name
    const toolList = useAssistantStore(state => state.assistantState.tool_list)
    const tool = toolList?.find(tool => tool.tool_key === data.message.tool_key) || { name: '工具' }

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="flex justify-between items-center px-4 py-2 shadow-xl cursor-pointer" onClick={() => setOpen(!open)}>
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        data.end ? <ToastIcon type='success' /> :
                            <LoadIcon className="text-primary duration-300" />
                    }
                    <span>{data.end ? '已使用 ' : '正在使用 '}{tool.name}</span>
                </div>
                <CaretDownIcon className={open && 'rotate-180'} />
            </div>
            <div className={cname('bg-gray-100 px-4 py-2 text-gray-500 overflow-hidden text-sm ', open ? 'h-auto' : 'h-0 p-0')}>
                <p>{data.thought}</p>
            </div>
        </div>
    </div>
};
