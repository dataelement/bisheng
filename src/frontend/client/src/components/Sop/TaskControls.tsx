import { AnimatePresence, motion } from 'framer-motion';
import { CheckIcon } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { Button, Switch, Textarea } from '../ui';
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
    queueCount: number;
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
    queueCount,
    status,
    feedbackProvided
}: TaskControlsProps) => {
    const [showOverview, setShowOverview] = useState(false);

    const isRunning = status === SopStatus.Running;
    const isCompleted = [SopStatus.completed, SopStatus.Stoped].includes(status);
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

    if (queueCount) return null

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

                        {(isRunning) && (
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
                        {isCompleted && !feedbackProvided && (
                            <FeedbackComponent stop={stoped} onFeedback={feedback} />
                        )}
                    </div>
                </motion.div>
            )}
        </AnimatePresence>
    );
};


interface FeedbackComponentProps {
    stop: boolean
    onFeedback: (rating: number, comment: string, shouldRestart: boolean, cancelled?: boolean) => void
}

export default function FeedbackComponent({ stop, onFeedback }: FeedbackComponentProps) {
    const [rating, setRating] = useState(0)
    const [hoveredRating, setHoveredRating] = useState(0)
    const [comment, setComment] = useState("")
    const [loading, setLoading] = useState(false)

    const handleStarClick = useCallback((star: number) => {
        setRating(star)
        // Record rating to backend here
        // You can call your API to save the rating to SOP execution record
    }, [])

    const handleStarHover = useCallback((star: number) => {
        setHoveredRating(star)
    }, [])

    const handleStarLeave = useCallback(() => {
        setHoveredRating(0)
    }, [])

    const handleRestart = useCallback(() => {
        if (!comment.trim()) return

        setLoading(true)
        onFeedback(rating, comment, true)

        // Simulate API call
        setTimeout(() => {
            setLoading(false)
        }, 2000)
    }, [rating, comment, onFeedback])

    const getStarColor = (starIndex: number) => {
        const activeRating = hoveredRating || rating
        return starIndex <= activeRating ? "text-yellow-400" : "text-gray-300"
    }

    return (
        <div className="bg-gray-50 rounded-3xl border border-gray-100">
            {/* Task Completed Header */}
            <div className="flex items-center gap-2 p-4">
                {stop ?
                    <div className="w-5 h-5 bg-primary rounded-full text-white font-bold flex items-center justify-center">i</div>
                    : <div className="w-5 h-5 bg-[#05B353] rounded-full p-1" >
                        <CheckIcon size={14} className='text-white' />
                    </div>
                }
                <span className="text-sm font-medium text-gray-700">任务已{stop ? '终止' : '完成'}</span>

                {/* Star Rating */}
                <div className="flex items-center gap-1 ml-auto">
                    <span className="text-xs text-gray-500 mr-2 pt-0.5">评价任务帮助灵思下次做得更好：</span>
                    <div className="flex gap-1">
                        {[1, 2, 3, 4, 5].map((star) => (
                            <div
                                key={star}
                                onClick={() => handleStarClick(star)}
                                onMouseEnter={() => handleStarHover(star)}
                                onMouseLeave={handleStarLeave}
                            >
                                <StarIcon
                                    className={`size-4 cursor-pointer ${getStarColor(star)}`}
                                />
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Feedback Input and Restart Button */}
            <div className="flex gap-3 bg-white rounded-3xl border border-gray-100 relative -bottom-1 p-4">
                <div className="flex-1">
                    <Textarea
                        placeholder="对结果不满意？您还可以输入意见重新发起任务。"
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        className="resize-none min-h-[40px] text-sm border-none shadow-none focus:ring-0 focus:outline-none"
                        rows={1}
                    />
                </div>
                <Button
                    onClick={handleRestart}
                    disabled={!comment.trim() || loading}
                    className="px-6  self-end"
                >
                    {loading ? "运行中..." : "重新运行"}
                </Button>
            </div>
        </div>
    )
}
