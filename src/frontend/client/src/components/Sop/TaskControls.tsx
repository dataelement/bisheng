import { AnimatePresence, motion } from 'framer-motion';
import { CheckIcon, MousePointerClick } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useLocalize } from '~/hooks';
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
    const localize = useLocalize();
    const { sopId } = useParams();

    const isRunning = status === SopStatus.Running;
    const isCompleted = [SopStatus.completed, SopStatus.Stoped].includes(status);
    const userRequestedStop = status === SopStatus.Stoped && !feedbackProvided;
    const showTask = isRunning || isCompleted || userRequestedStop;

    const currentStep = useMemo(() => (
        current ? tasks.findIndex(t => t.id === current.id) + 1 : 1
    ), [current, tasks]);

    const handleStopClick = () => {
        onStop()
    }

    const feedback = (rating: number, comment: string, restart: boolean, cancel?: boolean) => {
        onFeedback(rating, comment, restart, cancel)
    }

    if (sopId) return <SameSopControls sopId={sopId} />;
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
                                <h1 className='font-bold mb-3'>{localize('com_sop_task_planning')}</h1>
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
                                                {localize('com_sop_task_stage')} {currentStep}/{tasks.length}
                                            </span>
                                        )}
                                        <span className="pl-4 text-sm">{current?.name || ''}</span>
                                    </div>

                                    <div className='flex gap-2 items-center'>
                                        <span className='whitespace-nowrap text-sm text-gray-600'>{localize('com_sop_show_overview')}</span>
                                        <Switch onCheckedChange={setShowOverview} />
                                        {
                                            !userRequestedStop && !userRequestedStop && <Button
                                                className='ml-4 text-primary border-primary'
                                                variant="outline"
                                                onClick={handleStopClick}
                                            >
                                                {localize('com_sop_stop_task')}
                                            </Button>
                                        }
                                    </div>
                                </div>
                            </div>
                        )}
                        {isCompleted && !feedbackProvided && (
                            <FeedbackComponent stop={userRequestedStop} onFeedback={feedback} />
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
    const localize = useLocalize();

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

    const handleRestart = useCallback((restart: boolean) => {
        if (!comment.trim()) return

        setLoading(true)
        onFeedback(rating, comment, restart)

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
                <span className="text-sm font-medium text-gray-700">{localize('com_sop_task')}{stop ? localize('com_sop_terminated') : localize('com_sop_completed')}</span>

                {/* Star Rating */}
                <div className="flex items-center gap-1 ml-auto">
                    <span className="text-xs text-gray-500 mr-2 pt-0.5">{localize('com_sop_rate_task')}</span>
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
                        placeholder={localize('com_agent_unsatisfied_feedback')}
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        className="resize-none min-h-[40px] bg-transparenttext-sm border-none shadow-none focus:ring-0 focus:outline-none"
                        rows={2}
                    />
                </div>
                <Button
                    variant={"outline"}
                    onClick={() => handleRestart(false)}
                    disabled={!comment.trim() || loading}
                    className="px-6 self-end"
                >
                    {localize('com_sop_feedback_only')}
                </Button>
                <Button
                    onClick={() => handleRestart(true)}
                    disabled={!comment.trim() || loading}
                    className="px-6 self-end"
                >
                    {loading ? localize('com_sop_running') : localize('com_sop_rerun')}
                </Button>
            </div>
        </div>
    )
}



const SameSopControls = ({ sopId }: { sopId: string }) => {
    const localize = useLocalize();

    return <div className="px-4 pb-6">
        <div className="flex gap-3 p-4 px-6 justify-between items-center bg-white rounded-3xl border border-gray-100 relative">
            <div className="flex items-center gap-2">
                <div className="w-5 h-5 bg-[#05B353] rounded-full p-1" >
                    <CheckIcon size={14} className='text-white' />
                </div>
                <span className="text-sm font-medium text-gray-700">{localize('com_sop_task')}{localize('com_sop_terminated')}</span>
            </div>
            <Button className="px-6" onClick={() => window.open(`${__APP_ENV__.BASE_URL}/c/new?sopid=${sopId}`)}>
                <MousePointerClick className="w-3.5 h-3.5" />
                {localize('com_make_samestyle')}
            </Button>
        </div>
    </div>
}