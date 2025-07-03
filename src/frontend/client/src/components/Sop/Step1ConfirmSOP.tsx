import { Check, ChevronDown, CircleCheck, Download, FileText, LucideLoaderCircle, MessageCircleMoreIcon, PencilLineIcon, Star } from 'lucide-react';
import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Select, SelectContent, SelectItem, SelectTrigger } from '~/components/ui/Select';
import { useGetBsConfig } from '~/data-provider';
import { Button, Checkbox, Switch, Textarea } from '../ui';
import { SendIcon } from '~/components/svg';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/Popover';
import Step1ConfirmSOP from './Step1ConfirmSOP';
import Step2ExecuteTask from './Step2ExecuteTask';
import Step3ReviewResult from './Step3ReviewResult';
import StarIcon from '../ui/icon/Star';
import Markdown from '../ui/icon/Markdown';

const StepLabels = ['确认SOP', '执行任务', '审核结果'];

export default function index(params) {
    const location = useLocation();
    console.log('location.pathname', location.pathname); // 应输出 "/sop"

    const [currentStep, setCurrentStep] = useState(1);
    const [isTerminated, setIsTerminated] = useState(false);
    const [showDescription, setShowDescription] = useState(false);

    const handleNext = () => {
        if (!isTerminated) {
            setCurrentStep(prev => Math.min(prev + 1, 3));
        }
    };

    const handleTerminate = () => {
        setIsTerminated(true);
        // 不自动进入第三步
    };

    const handleRestart = () => {
        setIsTerminated(false);
        // 可以添加重置状态的逻辑
    };

    const renderStep = () => {
        switch (currentStep) {
            case 1:
                return <Step1ConfirmSOP onNext={() => setCurrentStep(2)} />;
            case 2:
                return (
                    <Step2ExecuteTask
                        onNext={handleNext}
                        onTerminate={handleTerminate}
                    />
                );
            case 3:
                return <Step3ReviewResult />;
            default:
                return null;
        }
    };

    const [open1, setOpen1] = useState(false);
    const [open2, setOpen2] = useState(false);

    return (
        <div className='h-full bg-gradient-to-b from-[#F4F8FF] to-white'>
            {/* header */}
            <div className="flex items-center justify-between p-4">
                {/* 左侧标题部分 */}
                <div className="flex items-center gap-3">
                    <FileText className="size-4" />
                    <span className="text-base font-medium text-gray-900">
                        生成电动车电池最新技术进展报告
                    </span>
                </div>
                {/* <Skeleton className="h-7 w-[250px] rounded-lg bg-gray-100 opacity-100" /> */}

                {/* 右侧操作区域 */}
                <div className="flex items-center gap-3">
                    {/* 任务描述按钮 */}
                    <Popover open={open2}>
                        <PopoverTrigger asChild>
                            <Button variant="outline" size="sm" className="h-7 px-3 rounded-lg shadow-sm focus-visible:outline-0"
                                onMouseEnter={e => setOpen2(true)}
                                onMouseLeave={e => setOpen2(false)}
                            >
                                <MessageCircleMoreIcon className="size-4" />
                                <span className="text-xs">任务描述</span>
                            </Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-96 border border-[#BCD2FF] rounded-xl bg-[#E5EEFF]">
                            <p className='text-sm font-bold mb-2'>任务描述</p>
                            <p className='text-sm'>生成电动车电池最新技术进展报告</p>
                            <p className='text-sm'>生成电动车电池最新技术进展报告</p>
                            <p className='text-sm'>生成电动车电池最新技术进展报告</p>
                            <p className='text-sm'>生成电动车电池最新技术进展报告</p>
                            <p className='text-sm'>生成电动车电池最新技术进展报告</p>
                        </PopoverContent>
                    </Popover>

                    {/* 版本选择器 */}
                    <Select>
                        <SelectTrigger className="h-7 rounded-lg px-3 border bg-white hover:bg-gray-50 data-[state=open]:border-blue-500">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-normal text-gray-600">任务版本 2025/08/24 29D</span>
                            </div>
                        </SelectTrigger>
                        <SelectContent className="bg-white rounded-lg p-2 w-52 shadow-md">
                            {/* 倒序 当前高亮*/}
                            <SelectItem value="option1" className="text-xs px-3 py-2 hover:bg-gray-50">
                                任务版本 2025/08/24 29D
                            </SelectItem>
                            <SelectItem value="option2" className="text-xs px-3 py-2 hover:bg-gray-50">
                                任务版本 2025/08/24 28D
                            </SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>
            {/* body */}
            <div className='w-full h-[calc(100vh-68px)] p-2 pt-0'>
                {/* loading */}
                {/* <LoadingBox /> */}
                <div className='h-full flex gap-2'>
                    <div className='w-[30%] relative rounded-2xl border border-[#E8E9ED] bg-white overflow-auto'>
                        <div className='flex items-center gap-2 border-b border-b-[#E8E9ED] bg-[#FDFEFF] p-2 px-4 text-[13px] text-[#737780]'>
                            <PencilLineIcon size={14} />
                            SOP详细规划 编辑器
                        </div>
                        <div className='p-8 text-sm'>
                            编辑器内容
                        </div>
                        <div className='absolute bottom-6 w-full'>
                            {!open1 ?
                                <div className='linsight-card w-10/12 mx-auto relative'>
                                    <span className='text-lg'>SOP</span>
                                    <p className='mt-3 text-sm flex gap-2'>
                                        <div className="size-5 rounded-full bg-[radial-gradient(circle_at_center,_white_0%,_white_10%,_#143BFF_80%,_#143BFF_100%)] shadow-xl"></div>
                                        确认是否可以按照 SOP 执⾏任务
                                    </p>
                                    <div className='absolute right-4 bottom-4 flex gap-2'>
                                        <Button variant="outline" className="px-3" onClick={() => setOpen1(true)}>重新生成 SOP</Button>
                                        <Button className="px-6">开始执行</Button>
                                    </div>
                                </div> : <div className='linsight-card w-10/12 mx-auto relative'>
                                    <Textarea placeholder='请在此提出 SOP 重新规划方向的建议' className='border-none ![box-shadow:initial]' />
                                    <div className='flex justify-end gap-2'>
                                        <Button variant="outline" className="px-6" onClick={() => setOpen1(false)}>取消</Button>
                                        {/* 没内容智慧不可点击 */}
                                        <Button className="px-6">确认重新规划</Button> 
                                    </div>
                                </div>
                            }
                        </div>
                    </div>
                    <div className='relative flex-1 flex flex-col h-full rounded-2xl border border-[#E8E9ED] bg-white overflow-hidden'>
                        <div className='flex items-center gap-2 border-b border-b-[#E8E9ED] bg-[#FDFEFF] p-2 px-4 text-[13px] text-[#737780]'>
                            任务流
                        </div>
                        <div className='relative flex-1 pb-40 min-h-0 overflow-auto'>
                            {/* <TaskLoadingBox /> */}
                            {/* 一级二级任务 */}
                            <div className="w-[80%] mx-auto p-5  text-gray-800 leading-relaxed">
                                {/* 一级任务 */}
                                <h2 className="font-semibold mb-4">
                                    确认用户需求
                                </h2>

                                {/* 二级任务 */}
                                <div className="mb-4">
                                    <div className="flex items-center">
                                        <Check size={16} className='bg-gray-300 p-0.5 rounded-full text-white mr-2' />
                                        <span className='text-sm'>正在使用网络搜索 query：2024 固态电池进展</span>
                                    </div>
                                    <div className='flex mt-2'>
                                        <ChevronDown size={18} className='text-gray-500' />
                                        <div className='w-full text-sm text-gray-400 ml-2 leading-6 max-h-24 overflow-auto'>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展2</p>
                                        </div>
                                    </div>
                                </div>

                                <div className="mb-4">
                                    <div className="flex items-center">
                                        <LucideLoaderCircle size={16} className='text-primary mr-2 animate-spin' />
                                        <span className='text-sm'>正在使用网络搜索 query：2024 固态电池进展</span>
                                    </div>
                                    <div className='flex mt-2'>
                                        <ChevronDown size={18} className='text-gray-500' />
                                        <div className='w-full text-sm text-gray-400 ml-2 leading-6 max-h-24 overflow-auto'>
                                            {/* 最新的进展 */}
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p> 
                                            {/* 旧上 新下 */}
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展</p>
                                            <p>正在使⽤⽹络搜索 query：2024 固态电池进展2</p>
                                        </div>
                                    </div>
                                    {/* 展示之后要 叮 一声 
                                        滚动定位到最新的弹窗
                                    */}
                                    <div className='bg-[#F3F4F6] border border-[#dfdede] rounded-2xl px-5 py-4 mt-2 relative'>
                                        <div>
                                            <span className='bg-[#D5E3FF] p-1 px-2 text-xs text-primary rounded-md'>等待输入</span>
                                            <span className='pl-3 text-sm'>您关注哪些材料?(工具的入参取值)</span>
                                        </div>
                                        <div>
                                            <Textarea placeholder="请输入" className='border-none ![box-shadow:initial] pl-0 pr-10 pt-4 h-auto' rows={1} />
                                            {/* 未发送时置灰 */}
                                            <Button className='absolute bottom-4 right-4 size-9 rounded-full p-0 bg-black hover:bg-black/80' ><SendIcon size={24} /></Button>
                                        </div>
                                    </div>
                                </div>

                                <div className='relative mb-6 text-sm px-4 py-3 rounded-lg bg-[#F8F9FB] text-[#303133] leading-6'>
                                    {/* 替换markdown */}
                                    <p>聚焦电池性能瓶颈与产业技术演进之间的关键连接点。首先，从电极材料出发，对主流正极路径（如三元材料、磷酸铁锂、高锰富锂硅基等）进行性能评估与应用适配性分析，重点识别其在能量密度、安全性、资源的共享成本控制之间的平衡机制。同时，围绕负载端探索石墨体系的高端路径、硅碳复合材料的形貌控制技术，以及金属锂负极的界面稳定策略，追踪前沿研究在倍率性能与循环寿命方面的突破路径。</p>
                                    <div className='bg-gradient-to-t w-full h-10 from-[#F8F9FB] from-0% to-transparent to-100% absolute bottom-0'></div>
                                </div>

                                <div>
                                    <p className='text-sm text-gray-500'>根据您的需求，已帮您⽣成电动⻋电池最新技术进展报告</p>
                                    <div className='mt-5 flex flex-wrap gap-3'>
                                        <div className='w-[calc(50%-6px)]  p-2 rounded-2xl border border-[#ebeef2]'>
                                            <div className='bg-[#F4F6FB] h-24 p-4 rounded-lg overflow-hidden'>
                                                <Markdown className='size-24 mx-auto opacity-20' />
                                            </div>
                                            <div className='relative flex pt-3 gap-2 items-center'>
                                                <Markdown className='size-4 min-w-4' />
                                                <span className='text-sm truncate pr-6'>电动⻋电池最新技术进展报告电动⻋电池最新技术进展报告.md</span>
                                                <Button variant="ghost" className='absolute right-1 -bottom-1 w-6 h-6 p-0'>
                                                    <Download size={16} />
                                                </Button>

                                            </div>
                                        </div>
                                        <div className='w-[calc(50%-6px)]  p-2 rounded-2xl border border-[#ebeef2]'>
                                            <div className='bg-[#F4F6FB] h-24 p-4 rounded-lg overflow-hidden'>
                                                <Markdown className='size-24 mx-auto opacity-20' />
                                            </div>
                                            <div className='relative flex pt-3 gap-2 items-center'>
                                                <Markdown className='size-4 min-w-4' />
                                                <span className='text-sm truncate pr-6'>电动⻋电池最新技术进展报告电动⻋电池最新技术进展报告.md</span>
                                                <Button variant="ghost" className='absolute right-1 -bottom-1 w-6 h-6 p-0'>
                                                    <Download size={16} />
                                                </Button>

                                            </div>
                                        </div>
                                        {
                                            new Array(10).fill('xx').map((e, i) =>
                                                <div key={i} className='w-[calc(50%-6px)]  p-2 rounded-2xl border border-[#ebeef2]'>
                                                    <div className='bg-[#F4F6FB] h-24 p-4 rounded-lg overflow-hidden'>
                                                        <Markdown className='size-24 mx-auto opacity-20' />
                                                    </div>
                                                    <div className='relative flex pt-3 gap-2 items-center'>
                                                        <Markdown className='size-4 min-w-4' />
                                                        <span className='text-sm truncate pr-6'>电动⻋电池最新技术进展报告电动⻋电池最新技术进展报告.md</span>
                                                        <Button variant="ghost" className='absolute right-1 -bottom-1 w-6 h-6 p-0'>
                                                            <Download size={16} />
                                                        </Button>

                                                    </div>
                                                </div>
                                            )
                                        }
                                    </div>
                                </div>
                            </div>

                        </div>

                        {/* 功能条 */}
                        <div className='absolute bottom-6 w-full'>
                            <div className='relative w-10/12 mx-auto'>
                                {/* 概览窗口 */}
                                <div className='absolute bottom-10 p-6 pb-14 w-full border rounded-2xl bg-white transition-all overflow-hidden'>
                                    <h1 className='font-bold mb-3'>任务规划</h1>
                                    <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                                    <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                                    <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                                    <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                                </div>
                                <div className='linsight-card w-full relative'>
                                    <div className='flex justify-between'>
                                        <div className='flex items-center'>
                                            <span className='bg-[#EEF3FF] border border-[#9EAEFF] px-2 py-1 rounded-md text-primary text-xs'>任务阶段 1/5</span>
                                            <span className="pl-4 text-sm">确认用户需求(一级任务名称)</span>
                                        </div>
                                        <div className='flex gap-2 items-center'>
                                            <span className='text-sm text-gray-600'>显示概览窗口</span>
                                            <Switch />
                                            {/* 暂停任务 || */}
                                            <Button className='ml-4 text-primary border-primary' variant="outline">终止任务</Button>
                                        </div>
                                    </div>
                                    {/* <div className='flex items-center text-sm'>
                                    <Check size={16} className='bg-emerald-500 p-0.5 rounded-full text-white mr-2' />
                                    <span>任务已完成，评价任务帮助下次做得更好。</span>
                                </div>
                                <div className='flex gap-2 mt-4'>
                                    <StarIcon className='text-primary' />
                                    <StarIcon className="text-gray-400" />
                                    <StarIcon className="text-gray-400" />
                                    <StarIcon className="text-gray-400" />
                                    <StarIcon className="text-gray-400" />
                                </div>
                                大于3个星星关闭
                                否则出areatext
                                        <AreaText placeholder="请告诉我们如何改进，您的反馈将用于下次任务优化" />  可拖拽高度
                                        <CheckBox />基于反馈重新运行
                                <Button className='absolute right-4 bottom-4 ml-4 text-primary border-primary' variant="outline">反馈意见</Button>
                                <Button>取消</Button> 关闭弹窗 */}
                                </div>
                            </div>
                        </div>

                    </div>
                </div>
            </div>
        </div>
    );
};


const LoadingBox = () => {

    return <div className='h-full bg-white border border-[#E8E9ED] rounded-xl flex flex-col justify-center text-center'>
        <div className="lingsi-border-box mx-auto">
            <div className='w-[194px] h-[102px] bg-no-repeat mx-auto rounded-md'
                style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/linsi-load.png)` }}></div>
        </div>
        <h1 className='text-2xl mt-10'>为您提供详细 SOP，以确保任务精准</h1>
        <p className='mt-5'>灵思正在为您规划 SOP...</p>
    </div>
}

const TaskLoadingBox = () => {
    const { data: bsConfig } = useGetBsConfig()

    return <div className='flex flex-col h-full justify-center text-center bg-gradient-to-b from-[#F4F8FF] to-white'>
        <div className='size-10 mx-auto'>
            <img className='size-full grayscale opacity-20' src={__APP_ENV__.BASE_URL + bsConfig?.sidebarIcon.image} alt="" />
        </div>
        <p className='text-sm text-gray-400 mt-7'>确认SOP规划后，任务开始运行</p>
    </div>
}

