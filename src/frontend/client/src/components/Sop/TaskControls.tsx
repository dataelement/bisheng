import { AnimatePresence, motion } from 'framer-motion';
import { Check } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useGetBsConfig, useGetUserLinsightCountQuery } from '~/data-provider';
import { Button, Checkbox, Switch, Textarea } from '../ui';
import StarIcon from '../ui/icon/Star';
import { SopStatus } from './SOPEditor';

interface Task {
    id: string;
    name: string;
}

interface TaskControlsProps {
    onStop: () => void;
    onFeedback: (rating: number, comment: string, restart: boolean, cancel?: boolean) => void;
    current: Task | null;
    tasks: Task[];
    status: SopStatus;
    feedbackProvided: boolean;
}

const slideUpAnimation = {
    initial: { y: 100, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    exit: { y: 0, opacity: 1 },
    transition: { duration: 0.3, ease: "easeInOut" }
};


export const TaskControls = ({
    onStop,
    onFeedback,
    current,
    tasks,
    status,
    feedbackProvided
}: TaskControlsProps) => {
    const [showOverview, setShowOverview] = useState(false);

    const isRunning = status === SopStatus.Running;
    const isCompleted = status === SopStatus.completed;
    const userRequestedStop = status === SopStatus.Stoped && !feedbackProvided;
    const showTask = isRunning || isCompleted || userRequestedStop;

    const currentStep = useMemo(() => (
        current ? tasks.findIndex(t => t.id === current.id) + 1 : 1
    ), [current, tasks]);

    const [stoped, setStoped] = useState(userRequestedStop)
    const handleStopClick = () => {
        setStoped(true)
        onStop()
    }

    const feedback = (rating: number, comment: string, restart: boolean, cancel?: boolean) => {
        onFeedback(rating, comment, restart, cancel)
    }

    return (
        <AnimatePresence>
            {showTask && (
                <motion.div
                    className='absolute bottom-6 w-full'
                    {...slideUpAnimation}
                >
                    <div className='relative w-10/12 mx-auto'>
                        {
                            !isCompleted && <div className={`${!showOverview && 'hidden'} absolute bottom-10 p-6 pb-14 w-full border rounded-2xl bg-white transition-all overflow-hidden`}>
                                <h1 className='font-bold mb-3'>任务规划</h1>
                                {tasks.map((task, i) => (
                                    <p key={task.id} className='text-sm leading-7'>{i + 1}. {task.name}</p>
                                ))}
                            </div>
                        }

                        {(isRunning || userRequestedStop) && (
                            <div className='linsight-card w-full relative'>
                                <div className='flex justify-between'>
                                    <div className='flex items-center'>
                                        {tasks.length > 0 && (
                                            <span className='whitespace-nowrap bg-[#EEF3FF] border border-[#9EAEFF] px-2 py-1 rounded-md text-primary text-xs'>
                                                任务阶段 {currentStep}/{tasks.length}
                                            </span>
                                        )}
                                        <span className="pl-4 text-sm">{current?.name || ''}</span>
                                    </div>

                                    <div className='flex gap-2 items-center'>
                                        <span className='whitespace-nowrap text-sm text-gray-600'>显示概览窗口</span>
                                        <Switch onCheckedChange={setShowOverview} />
                                        {
                                            !stoped && !userRequestedStop && <Button
                                                className='ml-4 text-primary border-primary'
                                                variant="outline"
                                                onClick={handleStopClick}
                                            >
                                                终止任务
                                            </Button>
                                        }
                                    </div>
                                </div>
                            </div>
                        )}
                        {isCompleted && (
                            <div className='relative'>
                                <div className={`absolute bottom-14 p-6 pt-3 pb-14 w-full border rounded-3xl bg-gradient-to-r from-[#C0FDD4] to-[#DFFFED]`}>
                                    <div className='flex items-center text-sm'>
                                        <Check size={16} className='bg-emerald-500 p-0.5 rounded-full text-white mr-2' />
                                        <span>任务已完成</span>
                                    </div>
                                </div>
                                <div className='linsight-card w-full relative'>
                                    <div className='flex items-center text-sm'>
                                        <span>请评价任务，帮助灵思下次做得更好。</span>
                                    </div>
                                    <FeedbackComponent onFeedback={feedback} />
                                </div>
                            </div>
                        )}
                    </div>
                </motion.div>
            )}
        </AnimatePresence>
    );
};


const FeedbackComponent = ({ onFeedback }: { onFeedback: TaskControlsProps['onFeedback'] }) => {
    const [rating, setRating] = useState(0);
    const [shouldRestart, setShouldRestart] = useState(false);
    const [comment, setComment] = useState('');
    const { data: bsConfig } = useGetBsConfig()
    const { data: count, refetch } = useGetUserLinsightCountQuery()
    useEffect(() => {
        refetch()
    }, [])

    const handleSubmit = useCallback(() => {
        onFeedback(rating, comment, shouldRestart);
    }, [rating, comment, shouldRestart, onFeedback]);

    const handleCancel = useCallback(() => {
        onFeedback(rating, comment, shouldRestart, true);
    }, [rating, comment, shouldRestart, onFeedback]);

    return (
        <div className="relative">
            <div className='flex gap-2 mt-4'>
                {[1, 2, 3, 4, 5].map((star) => (
                    <div
                        key={star}
                        onClick={() => {
                            setRating(star);
                            if (star > 3) onFeedback(star, '', false);
                        }}
                    >
                        <StarIcon
                            className={`cursor-pointer ${star <= rating ? 'text-yellow-400' : 'text-gray-400'}`}
                        />
                    </div>
                ))}
            </div>

            {rating > 0 && rating < 4 && (
                <div className="mt-4 space-y-4">
                    <Textarea
                        placeholder="请告诉我们如何改进，您的反馈将用于下次任务优化"
                        value={comment}
                        className='resize-y'
                        onChange={(e) => setComment(e.target.value)}
                    />
                    <div className="flex justify-between items-center">
                        <div className="flex items-center">
                            <Checkbox
                                checked={shouldRestart}
                                disabled={bsConfig?.linsight_invitation_code && count === 0}
                                onCheckedChange={setShouldRestart}
                            />
                            <label className="text-sm pl-2">基于反馈重新运行</label>
                            {bsConfig?.linsight_invitation_code && <label className='text-sm pl-2'>（剩余任务次数 {count} 次）</label>}
                        </div>
                        <div className="flex gap-2">
                            <Button variant="outline" onClick={handleCancel}>
                                取消
                            </Button>
                            <Button
                                disabled={!comment.trim()}
                                onClick={handleSubmit}
                            >
                                提交反馈
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};