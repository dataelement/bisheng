import axios from 'axios';
import { Check, ChevronDown, Download, Hourglass, LucideLoaderCircle, Pause } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { SendIcon } from '~/components/svg';
import { playDing } from '~/utils';
import { Button, Textarea } from '../ui';
import MarkdownIcon from '../ui/icon/Markdown';
import { SopStatus } from './SOPEditor';
import Markdown from '../Chat/Messages/Content/Markdown';

const Task = ({ task, lvl1 = false, que, sendInput, children = null }) => {
    const [isHistoryExpanded, setIsHistoryExpanded] = useState(false);
    const [inputValue, setInputValue] = useState('');

    // 根据状态选择对应的图标
    const renderStatusIcon = () => {
        switch (task.status) {
            // case "not_started":
            case "user_input":
                return <Pause size={16} className='min-w-4 p-0.5 rounded-full mr-2' />;
            case "user_input_completed":
            case "in_progress":
                return <LucideLoaderCircle size={16} className='min-w-4 text-primary mr-2 animate-spin' />;
            case "success":
                return <Check size={16} className='min-w-4 bg-gray-300 p-0.5 rounded-full text-white mr-2' />;
            default:
                return <Hourglass size={16} className='min-w-4 bg-gray-300 p-0.5 rounded-full text-white mr-2 animate-pulse' />;
        }
    };

    // 处理发送输入
    const handleSendInput = () => {
        if (inputValue.trim()) {
            sendInput({
                task_id: task.id,
                user_input: inputValue
            });
            setInputValue(''); // 清空输入框
        }
    };

    // 处理回车键发送
    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendInput();
        }
    };

    useEffect(() => {
        if (task.event_type === "user_input") {
            console.log('ding :>> ', task.event_type, task);
            playDing()
        }
    }, [task.status])

    const history = useMemo(() => {
        const result = [];
        const startMap = new Map(); // 存储未匹配的 start 消息: call_id -> message
        for (const msg of task.history) {
            if (msg.status === 'start') {
                // 存储或覆盖同 call_id 的 start
                startMap.set(msg.call_id, msg);
            } else if (msg.status === 'end') {
                // 检查是否有匹配的 start
                if (startMap.has(msg.call_id)) {
                    // 移除对应的 start
                    startMap.delete(msg.call_id);
                }
                // 总是添加 end 消息
                result.push(msg.call_reason);
            }
        }

        // 添加所有未匹配的 start 消息
        for (const startMsg of startMap.values()) {
            result.push(startMsg.call_reason);
        }

        return result;
    }, [task.history])

    const historyContainerRef = useRef(null);

    useEffect(() => {
        if (isHistoryExpanded && historyContainerRef.current) {
            // 滚动到底部
            historyContainerRef.current.scrollTop = historyContainerRef.current.scrollHeight;
        }
    }, [isHistoryExpanded, history]);

    return (
        <div className="mb-4">
            <div className="flex items-center">
                {renderStatusIcon()}
                {
                    lvl1 ? <h2 className="font-semibold">{que}.{task.name}</h2> :
                        <span className='text-sm'>{que}.{task.name}</span>
                }
            </div>

            {/* 历史记录部分 - 可折叠 */}
            {history?.length !== 0 && (
                <div className='mt-2'>
                    <div
                        className='flex'
                        onClick={() => setIsHistoryExpanded(!isHistoryExpanded)}
                    >
                        <ChevronDown
                            size={18}
                            className={`text-gray-500 cursor-pointer transition-transform ${isHistoryExpanded ? 'rotate-180' : ''}`}
                        />
                        {
                            isHistoryExpanded ? <div ref={historyContainerRef} className='w-full text-sm text-gray-400 ml-2 leading-6 max-h-60 overflow-auto'>
                                {history.map((_history, index) => (
                                    <p key={index}>{_history}</p>
                                ))}
                            </div> : <span className='w-full text-sm text-gray-400 ml-2 leading-6'>{history[history.length - 1]}</span>
                        }
                    </div>
                </div>
            )}

            {/* 等待输入部分 */}
            {task.event_type === "user_input" && (
                <div className='bg-[#F3F4F6] border border-[#dfdede] rounded-2xl px-5 py-4 mt-2 relative'>
                    <div>
                        <span className='bg-[#D5E3FF] p-1 px-2 text-xs text-primary rounded-md'>等待输入</span>
                        <span className='pl-3 text-sm'>{task.call_reason}</span>
                    </div>
                    <div>
                        <Textarea
                            placeholder="请输入"
                            className='border-none ![box-shadow:initial] pl-0 pr-10 pt-4 h-auto'
                            rows={1}
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onKeyDown={handleKeyDown}
                        />
                        <Button
                            className='absolute bottom-4 right-4 size-9 rounded-full p-0 bg-black hover:bg-black/80'
                            onClick={handleSendInput}
                            disabled={!inputValue.trim()}
                        >
                            <SendIcon size={24} />
                        </Button>
                    </div>
                </div>
            )}

            {children}
        </div>
    );
};


export const TaskFlowContent = ({ tasks, status, summary, files, sendInput }) => {
    console.log('TaskFlowContent tasks :>> ', tasks, files);


    const downloadFile = (file) => {
        const { file_name, file_url } = file;
        const url = `${__APP_ENV__.BASE_URL}/bisheng/${file_url}`
        return axios.get(url, { responseType: "blob" }).then((res: any) => {
            const blob = new Blob([res.data]);
            const link = document.createElement("a");
            link.href = URL.createObjectURL(blob);
            link.download = file_name;
            link.click();
            URL.revokeObjectURL(link.href);
        }).catch(console.error);
    }

    return (
        <div className="w-[80%] mx-auto p-5 text-gray-800 leading-relaxed">
            {!tasks?.length && status === SopStatus.Running && <LucideLoaderCircle size={16} className='text-primary mr-2 animate-spin' />}
            {
                tasks?.map((task, i) => <Task key={task.id} que={i + 1} lvl1 task={task} sendInput={sendInput} >
                    {
                        task.children?.map((_task, i) => <Task key={_task.id} que={i + 1} task={_task} sendInput={sendInput} />)
                    }
                </Task>
                )
            }

            {
                summary && <div className='relative mb-6 text-sm px-4 py-3 rounded-lg bg-[#F8F9FB] text-[#303133] leading-6'>
                    <Markdown content={summary} isLatestMessage={true} webContent={false} />
                    <div className='bg-gradient-to-t w-full h-10 from-[#F8F9FB] from-0% to-transparent to-100% absolute bottom-0'></div>
                </div>
            }

            {files && files.length > 0 &&
                <div>
                    {/* <p className='text-sm text-gray-500'>xxxxxxxxxxxxxxxxx</p> */}
                    <div className='mt-5 flex flex-wrap gap-3'>
                        {files?.map((file) => (
                            <div key={file.file_id} className='w-[calc(50%-6px)] p-2 rounded-2xl border border-[#ebeef2]'>
                                <div className='bg-[#F4F6FB] h-24 p-4 rounded-lg overflow-hidden'>
                                    <MarkdownIcon className='size-24 mx-auto opacity-20' />
                                </div>
                                <div className='relative flex pt-3 gap-2 items-center'>
                                    <MarkdownIcon className='size-4 min-w-4' />
                                    <span className='text-sm truncate pr-6'>{file.file_name}</span>
                                    <Button variant="ghost" className='absolute right-1 -bottom-1 w-6 h-6 p-0'>
                                        <Download size={16} onClick={() => downloadFile(file)} />
                                    </Button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            }
        </div>
    );
};