import { AnimatePresence, motion } from 'framer-motion';
import { Button, Switch } from '../ui';

const slideUpAnimation = {
    initial: { y: 100, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    exit: { y: 0, opacity: 1 },
    transition: { duration: 0.3, ease: "easeInOut" }
};

export const TaskControls = ({ stop, tasks, isExecuting }) => {
    console.log('tasks :>> ', tasks);

    return (
        <AnimatePresence>
            {isExecuting && (
                <motion.div
                    className='absolute bottom-6 w-full'
                    {...slideUpAnimation}
                >
                    <div className='relative w-10/12 mx-auto'>
                        <div className='hidden absolute bottom-10 p-6 pb-14 w-full border rounded-2xl bg-white transition-all overflow-hidden'>
                            <h1 className='font-bold mb-3'>任务规划</h1>
                            <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                            <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                            <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                            <p className='text-sm leading-7'>1. 确认⽤户需求 </p>
                        </div>

                        <div className='linsight-card w-full relative'>
                            <div className='flex justify-between'>
                                <div className='flex items-center'>
                                    <span className='bg-[#EEF3FF] border border-[#9EAEFF] px-2 py-1 rounded-md text-primary text-xs'>
                                        任务阶段 1/5
                                    </span>
                                    <span className="pl-4 text-sm">确认用户需求(一级任务名称)</span>
                                </div>

                                <div className='flex gap-2 items-center'>
                                    <span className='text-sm text-gray-600'>显示概览窗口</span>
                                    <Switch />
                                    <Button className='ml-4 text-primary border-primary' variant="outline" onClick={stop}>
                                        终止任务
                                    </Button>
                                </div>
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
                </motion.div>
            )}
        </AnimatePresence>
    );
};