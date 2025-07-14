import { AnimatePresence, motion } from 'framer-motion';
import { Button, Checkbox, Switch, Textarea } from '../ui';
import { SopStatus } from './SOPEditor';
import { useMemo, useState } from 'react';
import StarIcon from '../ui/icon/Star';
import { Check } from 'lucide-react';

const slideUpAnimation = {
    initial: { y: 100, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    exit: { y: 0, opacity: 1 },
    transition: { duration: 0.3, ease: "easeInOut" }
};

export const TaskControls = ({ onStop, onFeedback, current, tasks, status }) => {
    const [showOverview, setShowOverview] = useState(false);
    const showTask = [SopStatus.Running, SopStatus.completed].includes(status)

    const step = useMemo(() => {
        return current ? tasks.findIndex(t => t.id === current.id) + 1 : 1;
    }, [current, tasks])

    const [stoped, setStoped] = useState(false)
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
                        <div className={`${!showOverview && 'hidden'} absolute bottom-10 p-6 pb-14 w-full border rounded-2xl bg-white transition-all overflow-hidden`}>
                            <h1 className='font-bold mb-3'>任务规划</h1>
                            {tasks?.map(task => <p key={task.id} className='text-sm leading-7'>{task.name}</p>)}
                        </div>

                        {status === SopStatus.Running ? <div className='linsight-card w-full relative'>
                            <div className='flex justify-between'>
                                <div className='flex items-center'>
                                    <span className='whitespace-nowrap bg-[#EEF3FF] border border-[#9EAEFF] px-2 py-1 rounded-md text-primary text-xs'>
                                        任务阶段 {step}/{tasks?.length}
                                    </span>
                                    <span className="pl-4 text-sm">{current?.name || ''}</span>
                                </div>

                                <div className='flex gap-2 items-center'>
                                    <span className='whitespace-nowrap text-sm text-gray-600'>显示概览窗口</span>
                                    <Switch onCheckedChange={setShowOverview} />
                                    {
                                        !stoped && <Button className='ml-4 text-primary border-primary' variant="outline" onClick={handleStopClick}>
                                            终止任务
                                        </Button>
                                    }
                                </div>
                            </div>
                        </div> :
                            <div className='linsight-card w-full relative'>
                                <div className='flex items-center text-sm'>
                                    <Check size={16} className='bg-emerald-500 p-0.5 rounded-full text-white mr-2' />
                                    <span>任务已完成，评价任务帮助下次做得更好。</span>
                                </div>
                                <FeedbackComponent
                                    onFeedback={feedback}
                                />
                            </div>
                        }
                    </div>
                </motion.div>
            )}
        </AnimatePresence>
    );
};

interface FeedbackComponentProps {
    onFeedback: (rating: number, comment: string, restart: boolean, cancel?: boolean) => void;
}

const FeedbackComponent = ({ onFeedback }: FeedbackComponentProps) => {
    const [rating, setRating] = useState<number>(0);
    const [check, setCheck] = useState<boolean>(false)

    const [comment, setComment] = useState<string>('');
    const [showFeedbackForm, setShowFeedbackForm] = useState<boolean>(false);

    const handleStarClick = (selectedRating: number) => {
        setRating(selectedRating);

        // 如果评分≥3星，直接调用满意方法
        if (selectedRating > 3) {
            onFeedback(selectedRating, '', false);
            setShowFeedbackForm(false);
        } else {
            setShowFeedbackForm(true);
        }
    };

    const handleSubmitFeedback = () => {
        onFeedback(rating, comment, check);
    };

    const handleCancel = () => {
        onFeedback(rating, comment, check, true);
    }

    return (
        <div className="relative">
            {/* 星级评分 */}
            <div className='flex gap-2 mt-4'>
                {[1, 2, 3, 4, 5].map((star) => (
                    <div onClick={() => handleStarClick(star)}>
                        <StarIcon
                            key={star}
                            className={`cursor-pointer ${star <= rating ? 'text-yellow-400' : 'text-gray-400'}`}

                        />
                    </div>
                ))}
            </div>

            {/* 反馈表单（评分<3星时显示） */}
            {showFeedbackForm && rating < 4 && (
                <div className="mt-4 space-y-4">
                    <Textarea
                        placeholder="请告诉我们如何改进，您的反馈将用于下次任务优化"
                        value={comment}
                        className='resize-y'
                        onChange={(e) => setComment(e.target.value)}
                    />
                    <div className="flex justify-between items-center">
                        <div className="flex items-center">
                            <Checkbox value={check} onCheckedChange={setCheck} />
                            <label htmlFor="contact-me" className="text-sm pl-2">基于反馈重新运行</label>
                        </div>
                        <div className="flex gap-2">
                            <Button
                                variant="outline"
                                onClick={handleCancel}
                            >
                                取消
                            </Button>
                            <Button
                                className=""
                                disabled={comment === ''}
                                onClick={handleSubmitFeedback}
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
