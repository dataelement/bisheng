import { CheckIcon, ChevronDown, CircleAlert, Loader2 } from "lucide-react";
import { useRecoilState } from "recoil";
import { useMemo, useState } from "react";
import { chatsState } from "../store/atoms";
import { cn } from "~/utils";

export default function MessageRunlog({ data }) {
    const [open, setOpen] = useState(false)

    // 该组件只有在助手测试页面用到，临时使用耦合方案，取 toollist来匹配 name
    const [_chatsState] = useRecoilState(chatsState)
    const assistantState = useMemo(() => {
        return _chatsState[data.chat_id].flow
    }, [_chatsState, data])

    const [title, lost] = useMemo(() => {
        let lost = false
        let title = ''
        const status = data.end ? '已使用' : '正在使用'
        if (data.category === 'flow') {
            const flow = assistantState.flow_list?.find(flow => flow.id === data.message.tool_key)
            // if (!flow) throw new Error('调试日志无法匹配到使用的技能详情，id:' + data.message.tool_key)
            if (flow) {
                lost = flow.status === 1
                title = lost ? `${flow.name} 已下线` : `${status} ${flow.name}`
            } else {
                title = '技能已被删除，无法获取技能名'
            }
        } else if (data.category === 'tool') {
            const tool = assistantState.tool_list?.find(tool => tool.tool_key === data.message.tool_key)
            // if (!tool) throw new Error('调试日志无法匹配到使用的工具详情，id:' + data.message.tool_key)

            title = tool ? `${status} ${tool.name}` : '工具已被删除，无法获取工具名'
        } else if (data.category === 'knowledge') {
            const knowledge = assistantState.knowledge_list?.find(knowledge => knowledge.id === parseInt(data.message.tool_key))
            // if (!knowledge) throw new Error('调试日志无法匹配到使用的知识库详情，id:' + data.message.tool_key)

            title = knowledge ? `${data.end ? '已搜索' : '正在搜索'} ${knowledge.name}` : '知识库已被删除，无法获取知识库名'
        } else {
            title = data.end ? '完成' : '思考中'
        }
        return [title, lost]
    }, [assistantState, data])

    // 没任何匹配的工具，隐藏
    if (assistantState.tool_list.length + assistantState.knowledge_list.length
        + assistantState.flow_list.length === 0) return null

    return <div className="py-1">
        <div className="rounded-sm border max-w-[90%]">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer" onClick={() => setOpen(!open)}>
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        data.end ? (lost ? <div className="w-5 h-5 bg-red-500 rounded-full p-1" >
                            <CircleAlert size={14} className='text-white' />
                        </div> : <div className="w-5 h-5 bg-[#05B353] rounded-full p-1" >
                            <CheckIcon size={14} className='text-white' />
                        </div>) :
                            <Loader2 className="text-primary duration-300 animate-spin" />
                    }
                    <span>{title}</span>
                </div>
                <ChevronDown className={open && 'rotate-180'} />
            </div>
            <div className={cn('bg-[#F5F6F8] dark:bg-[#313336] px-4 py-2 overflow-hidden text-sm ', open ? 'h-auto' : 'h-0 p-0')}>
                {data.thought.split('\n').map((line, index) => (
                    <p className="text-md mb-1 text-muted-foreground" key={index}>{line}</p>
                ))}
            </div>
        </div>
    </div>
};
