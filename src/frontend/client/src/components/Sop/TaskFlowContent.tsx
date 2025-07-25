import axios from 'axios';
import {
    ArrowRight,
    BookOpen,
    Check, ChevronDown,
    Download,
    FileText,
    LucideLoaderCircle, Pause,
    Search,
    WrenchIcon
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { SendIcon } from '~/components/svg';
import { playDing } from '~/utils';
import Markdown from '../Chat/Messages/Content/Markdown';
import { Button, Textarea } from '../ui';
import FileIcon from '../ui/icon/File';
import FilePreviewDrawer from './FilePreviewDrawer';
import { SopStatus } from './SOPEditor';
import FileDrawer from './TaskFiles';

const Tool = ({ data }) => {
    const { name: toolName, step_type, params } = data;
    // 工具名称映射
    const nameMap = {
        web_search: "正在联网搜索",
        search_knowledge_base: "正在检索知识库",
        list_files: "正在查询目录",
        get_file_details: "正在获取文件详细信息",
        search_files: "正在搜索文件",
        read_text_file: "正在阅读文件",
        write_text_file: "正在向文件添加内容",
        replace_file_lines: "正在编辑文件",
        default: `正在使用 ${toolName} 工具`
    };

    // 参数键名映射
    const paramKeyMap = {
        web_search: () => params.query,
        search_knowledge_base: () => params.query,
        list_files: () => params.directory_path,
        get_file_details: () => params.file_path.split('/').pop(),
        search_files: () => params.pattern,
        read_text_file: () => params.file_path.split('/').pop(),
        write_text_file: () => params.file_path.split('/').pop(),
        replace_file_lines: () => params.file_path.split('/').pop(),
        default: () => '',
    };

    // 图标映射 - 使用组件形式
    const iconMap = {
        web_search: Search,
        search_knowledge_base: BookOpen,
        list_files: FileText,
        get_file_details: FileText,
        search_files: FileText,
        read_text_file: FileText,
        write_text_file: FileText,
        replace_file_lines: FileText,
        default: WrenchIcon
    };

    if (step_type !== 'tool_call') {
        return null
    }

    // 获取显示名称
    const displayName = nameMap[toolName] || nameMap.default;

    // 获取参数键名
    const paramValue = params && paramKeyMap[toolName] || paramKeyMap.default;

    // 获取图标
    const Icon = iconMap[toolName] || iconMap.default;

    return (
        <div className='inline-flex items-center gap-2 bg-[#F9FAFD] border rounded-full my-1.5 px-3 py-1.5 text-muted-foreground'>
            <Icon size={16} />
            <div className='flex gap-4 truncate'>
                <span className='text-xs text-gray-600'>{displayName}</span>
                <span className='text-xs text-[#82868C]'>{paramValue()}</span>
            </div>
        </div>
    )
}

const Task = ({ task, lvl1 = false, que, sendInput, children = null }) => {
    const [isHistoryExpanded, setIsHistoryExpanded] = useState(true);
    const [inputValue, setInputValue] = useState('');

    // 根据状态选择对应的图标
    const renderStatusIcon = () => {
        const status = (task.children?.some(child => child.status === 'user_input') && 'user_input') || task.status;
        switch (status) {
            case "failed":
            case "terminated":
                return <Pause size={18} className='min-w-4 p-0.5 rounded-full mr-2' />;
            // case "user_input":
            // case "user_input_completed":
            // case "in_progress":
            //     return <Hourglass size={16} className='min-w-4 [#BAC1CD] p-0.5 rounded-full text-white mr-2 animate-pulse' />;
            case "success":
                return <Check size={16} className='min-w-4 bg-[#BAC1CD] p-0.5 rounded-full text-white mr-2' />;
            default:
                return <LucideLoaderCircle size={16} className='min-w-4 text-primary mr-2 animate-spin' />;
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
        const result: any = [];
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
                msg.call_reason && result.push(msg);
            }
        }

        // 添加所有未匹配的 start 消息
        for (const startMsg of startMap.values()) {
            startMsg.call_reason && result.push(startMsg);
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

    // 未开始执行的任务不展示
    if (task.status === 'not_started') {
        return null;
    }

    return (
        <div className={`${lvl1 ? '' : 'pl-10'}`}>
            <div className={`flex items-start relative`}>
                <ChevronDown
                    size={18}
                    className={`absolute top-0 -left-6 text-gray-500 mt-0.5 cursor-pointer transition-transform 
                                ${isHistoryExpanded ? 'rotate-180' : ''} 
                                ${history.length ? 'visible' : 'invisible'}
                            `}
                    onClick={() => setIsHistoryExpanded(!isHistoryExpanded)}
                />
                {lvl1 && <div className='mt-[5px]'>{renderStatusIcon()}</div>}
                {
                    lvl1 ? <h2 className="font-semibold mb-4">{que}.{task.name}</h2> :
                        <span className='text-sm mb-3'>{que}.{task.name}</span>
                }
            </div>

            {/* 历史记录部分 - 可折叠 */}
            {history?.length !== 0 && (
                <div className='mb-2'>
                    <div className='flex'>
                        {
                            isHistoryExpanded ? <div ref={historyContainerRef} className={`${lvl1 ? 'pl-6' : 'pl-0'} w-full text-sm text-gray-400 leading-6 max-h-60 scroll-hover`}>
                                {history.map((_history, index) => (
                                    <div>
                                        <p key={index}>{_history.call_reason}</p>
                                        <Tool data={_history} />
                                    </div>
                                ))}
                            </div> : null
                        }
                    </div>
                </div>
            )}

            {/* 等待输入部分 */}
            {task.event_type === "user_input" && (
                <div className='bg-[#F3F4F6] border border-[#dfdede] rounded-2xl px-5 py-4 my-2 relative'>
                    <div>
                        <span className='bg-[#D5E3FF] p-1 px-2 text-xs text-primary rounded-md'>等待输入</span>
                        <span className='pl-3 text-sm'>{task.call_reason}</span>
                    </div>
                    <div>
                        <Textarea
                            id={task.id}
                            placeholder="请输入"
                            className='border-none ![box-shadow:initial] pl-0 pr-10 pt-4 h-auto'
                            rows={1}
                            value={inputValue}
                            maxLength={200}
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


export const TaskFlowContent = ({ tasks, status, summary, files, allFiles, sendInput }) => {
    console.log('TaskFlowContent tasks :>> ', tasks, files);
    const [isDrawerOpen, setIsDrawerOpen] = useState(false)
    const [isPreviewOpen, setIsPreviewOpen] = useState(false)
    const [currentPreviewFileId, setCurrentPreviewFileId] = useState<string>("")
    useFoucsInput(tasks);

    const mergeFiles = useMemo(() => {
        const mergedFiles = [...files, ...allFiles];
        return mergedFiles;
    }, [files, allFiles]);

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
            {!!tasks?.length && <div className='pl-6'>
                <p className='text-sm text-gray-400 mt-6 mb-4'>规划任务执行路径：</p>
                {tasks.map((task, i) => (
                    <p key={task.id} className='leading-7'>{i + 1}. {task.name}</p>
                ))}
                <p className='text-sm text-gray-400 mt-6 mb-4'>接下来为你执行对应任务：</p>
            </div>}
            {/* 任务 */}
            {!tasks?.length && status === SopStatus.Running && <LucideLoaderCircle size={16} className='text-primary mr-2 animate-spin' />}
            {
                tasks?.map((task, i) => <Task key={task.id} que={i + 1} lvl1 task={task} sendInput={sendInput} >
                    {
                        task.children?.map((_task, i) => <Task key={_task.id} que={i + 1} task={_task} sendInput={sendInput} />)
                    }
                </Task>
                )
            }
            {/* 总结 */}
            {
                summary && <div className='relative mb-6 text-sm px-4 py-3 rounded-lg bg-[#F8F9FB] text-[#303133] leading-6'>
                    <Markdown content={summary} isLatestMessage={true} webContent={false} />
                    <div className='bg-gradient-to-t w-full h-10 from-[#F8F9FB] from-0% to-transparent to-100% absolute bottom-0'></div>
                </div>
            }
            {/* 结果文件 */}
            {files && files.length > 0 &&
                <div>
                    {/* <p className='text-sm text-gray-500'></p> */}
                    <div className='mt-5 flex flex-wrap gap-3'>
                        {files?.map((file) => (
                            <div
                                key={file.file_id}
                                onClick={() => {
                                    setCurrentPreviewFileId(file.file_id);
                                    setIsPreviewOpen(true);
                                }}
                                className='w-[calc(50%-6px)] p-2 rounded-2xl border border-[#ebeef2] cursor-pointer'
                            >
                                <div className='bg-[#F4F6FB] h-24 p-4 rounded-lg overflow-hidden'>
                                    <FileIcon type={file.file_name.split('.').pop().toLowerCase()} className='size-24 mx-auto opacity-20' />
                                </div>
                                <div className='relative flex pt-3 gap-2 items-center'>
                                    <FileIcon type={file.file_name.split('.').pop().toLowerCase()} className='size-4 min-w-4' />
                                    <span className='text-sm truncate pr-6'>{file.file_name}</span>
                                    <Button variant="ghost" className='absolute right-1 -bottom-1 w-6 h-6 p-0'>
                                        <Download size={16} onClick={(e) => {
                                            e.stopPropagation();
                                            downloadFile(file)
                                        }} />
                                    </Button>
                                </div>
                            </div>
                        ))}
                    </div>
                    {/*  预览所有文件列表 */}
                    {
                        allFiles.length > files.length && <div className='mt-2.5'>
                            <div
                                onClick={() => setIsDrawerOpen(true)}
                                className='w-[calc(50%-6px)] p-2 rounded-2xl border border-[#ebeef2] cursor-pointer'
                            >
                                <div className='bg-[#F4F6FB] h-24 p-6 rounded-lg overflow-hidden'>
                                    <FileIcon type="dir" className='size-24 mx-auto opacity-20' />
                                </div>
                                <div className='relative flex pt-3 gap-2 items-center'>
                                    <FileIcon type="dir" className='size-4 min-w-4' />
                                    <span className='text-sm truncate pr-6'>查看此任务中的所有文件</span>
                                    <Button variant="ghost" className='absolute right-1 -bottom-1 w-6 h-6 p-0'>
                                        <ArrowRight size={16} />
                                    </Button>
                                </div>
                            </div>
                        </div>
                    }
                </div>
            }
            {/* 文件列表抽屉 */}
            <FileDrawer
                files={allFiles}
                isOpen={isDrawerOpen}
                onOpenChange={setIsDrawerOpen}
                downloadFile={downloadFile}
                onPreview={(id) => {
                    setCurrentPreviewFileId(id);
                    setIsDrawerOpen(false)
                    setIsPreviewOpen(true)
                }}
            />
            {/* 文件预览抽屉 */}
            <FilePreviewDrawer
                files={mergeFiles}
                isOpen={isPreviewOpen}
                onOpenChange={setIsPreviewOpen}
                downloadFile={downloadFile}
                currentFileId={currentPreviewFileId}
                onFileChange={(fileId) => setCurrentPreviewFileId(fileId)}
                onBack={setIsPreviewOpen}
            >
            </FilePreviewDrawer>
        </div >
    );
};


/**
 * 自动定位用户输入框
 * @param tasks 
 */
const useFoucsInput = (tasks: any) => {
    const [inputQueue, setInputQueue] = useState<string[]>([]); // 待处理的输入任务队列
    const [currentFocusId, setCurrentFocusId] = useState(''); // 当前聚焦的任务ID
    console.log('inputQueue :>> ', inputQueue);
    // 当任务变化时更新输入队列
    useEffect(() => {
        // 找出所有需要输入的新任务
        const newInputTasks = tasks
            .filter((task: any) => task.status === 'user_input' && !inputQueue.includes(task.id))
            .map(task => task.id);

        // 二级任务(同时只有一个二级任务下有待输入input)
        const hasUserInputTask = tasks.find((task: any) => task.children?.find((_task: any) => _task.status === 'user_input'));
        if (hasUserInputTask) {
            hasUserInputTask.children
                .filter((_task: any) => _task.status === 'user_input' && !inputQueue.includes(_task.id))
                .forEach(_task => newInputTasks.push(_task.id));
        }

        if (newInputTasks.length > 0) {
            // 将新任务添加到队列末尾
            setInputQueue((prev) => {
                const res = [...newInputTasks]
                setCurrentFocusId(res[0] || '')
                return res;
            });

        } else {
            setCurrentFocusId(newInputTasks[0] || '');
        }
    }, [tasks]);

    // 当输入队列变化时自动聚焦
    useEffect(() => {
        if (currentFocusId) {
            const dom = document.getElementById(currentFocusId);
            console.log('dom :>> ', dom);
            if (dom) {
                dom?.focus();
                // 平滑滚动到输入框位置
                dom.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        }
    }, [currentFocusId]);
}