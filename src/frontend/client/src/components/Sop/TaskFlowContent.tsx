import { Check, ChevronDown, Download, LucideLoaderCircle, PauseCircle } from 'lucide-react';
import React, { useEffect } from 'react';
import { SendIcon } from '~/components/svg';
import { Button, Textarea } from '../ui';


// 二级任务
import { useState } from 'react';
import Markdown from '../ui/icon/Markdown';
import { playDing } from '~/utils';

const Task = ({ task, lvl1 = false, que, sendInput, children = null }) => {
    const [isHistoryExpanded, setIsHistoryExpanded] = useState(false);
    const [inputValue, setInputValue] = useState('');

    // 根据状态选择对应的图标
    const renderStatusIcon = () => {
        switch (task.status) {
            // case "not_started":
            case "user_input":
                return <PauseCircle size={16} className='p-0.5 rounded-full mr-2' />;
            case "user_input_completed":
            case "in_progress":
                return <LucideLoaderCircle size={16} className='text-primary mr-2 animate-spin' />;
            case "success":
                return <Check size={16} className='bg-gray-300 p-0.5 rounded-full text-white mr-2' />;
            default:
                return null;
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
            {task.history?.length !== 0 && (
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
                            isHistoryExpanded ? <div className='w-full text-sm text-gray-400 ml-2 leading-6 max-h-24 overflow-auto'>
                                {task.history.map((history, index) => (
                                    <p key={index}>{history}</p>
                                ))}
                            </div> : <span className='w-full text-sm text-gray-400 ml-2 leading-6'>{task.history[task.history.length - 1]}</span>
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


export const TaskFlowContent = ({ tasks, summary, files, sendInput }) => {
    console.log('TaskFlowContent tasks :>> ', tasks, files);


    const downloadFile = (file) => {
        const { name, url } = file;
        console.log('name, url :>> ', name, url);
    }
    //

    return (
        <div className="w-[80%] mx-auto p-5 text-gray-800 leading-relaxed">
            {!tasks?.length && <LucideLoaderCircle size={16} className='text-primary mr-2 animate-spin' />}
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
                    <p>{summary}</p>
                    <div className='bg-gradient-to-t w-full h-10 from-[#F8F9FB] from-0% to-transparent to-100% absolute bottom-0'></div>
                </div>
            }

            {files && files.length > 0 &&
                <div>
                    <p className='text-sm text-gray-500'>xxxxxxxxxxxxxxxxx</p>
                    <div className='mt-5 flex flex-wrap gap-3'>
                        {files?.map((file, i) => (
                            <div key={i} className='w-[calc(50%-6px)] p-2 rounded-2xl border border-[#ebeef2]'>
                                <div className='bg-[#F4F6FB] h-24 p-4 rounded-lg overflow-hidden'>
                                    <Markdown className='size-24 mx-auto opacity-20' />
                                </div>
                                <div className='relative flex pt-3 gap-2 items-center'>
                                    <Markdown className='size-4 min-w-4' />
                                    <span className='text-sm truncate pr-6'>{file.name}</span>
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