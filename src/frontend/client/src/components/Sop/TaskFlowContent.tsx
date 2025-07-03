import { Check, ChevronDown, Download, LucideLoaderCircle } from 'lucide-react';
import { SendIcon } from '~/components/svg';
import { Button, Textarea } from '../ui';
import Markdown from '../ui/icon/Markdown';
import { playDing } from '~/utils';

export const TaskFlowContent = ({ tasks, sendInput }) => {
    // adsf

    // playDing()

    return (
        <div className="w-[80%] mx-auto p-5 text-gray-800 leading-relaxed">
            <h2 className="font-semibold mb-4">确认用户需求</h2>

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
                <div className='bg-[#F3F4F6] border border-[#dfdede] rounded-2xl px-5 py-4 mt-2 relative'>
                    <div>
                        <span className='bg-[#D5E3FF] p-1 px-2 text-xs text-primary rounded-md'>等待输入</span>
                        <span className='pl-3 text-sm'>您关注哪些材料?(工具的入参取值)</span>
                    </div>
                    <div>
                        <Textarea placeholder="请输入" className='border-none ![box-shadow:initial] pl-0 pr-10 pt-4 h-auto' rows={1} />
                        <Button className='absolute bottom-4 right-4 size-9 rounded-full p-0 bg-black hover:bg-black/80' >
                            <SendIcon size={24} />
                        </Button>
                    </div>
                </div>
            </div>

            <div className='relative mb-6 text-sm px-4 py-3 rounded-lg bg-[#F8F9FB] text-[#303133] leading-6'>
                <p>聚焦电池性能瓶颈与产业技术演进之间的关键连接点。首先，从电极材料出发，对主流正极路径（如三元材料、磷酸铁锂、高锰富锂硅基等）进行性能评估与应用适配性分析，重点识别其在能量密度、安全性、资源的共享成本控制之间的平衡机制。同时，围绕负载端探索石墨体系的高端路径、硅碳复合材料的形貌控制技术，以及金属锂负极的界面稳定策略，追踪前沿研究在倍率性能与循环寿命方面的突破路径。</p>
                <div className='bg-gradient-to-t w-full h-10 from-[#F8F9FB] from-0% to-transparent to-100% absolute bottom-0'></div>
            </div>

            <div>
                <p className='text-sm text-gray-500'>根据您的需求，已帮您⽣成电动⻋电池最新技术进展报告</p>
                <div className='mt-5 flex flex-wrap gap-3'>
                    {new Array(10).fill('xx').map((e, i) => (
                        <div key={i} className='w-[calc(50%-6px)] p-2 rounded-2xl border border-[#ebeef2]'>
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
                    ))}
                </div>
            </div>
        </div>
    );
};