import { motion } from 'framer-motion';
import { useGetBsConfig } from '~/data-provider';
import { TaskControls } from './TaskControls';
import { TaskFlowContent } from './TaskFlowContent';
import { useMemo } from 'react';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { useLinsightWebSocket } from '~/hooks/Websocket';


export const TaskFlow = ({ sesstionId }) => {
    const { data: bsConfig } = useGetBsConfig();
    const { getLinsight } = useLinsightManager()

    const {stop, sendInput} = useLinsightWebSocket(sesstionId)

    const { sop, tools, tasks, isExecuting } = useMemo(() => {
        const linsight = getLinsight(sesstionId)
        if (linsight) {
            const { sop, sop_map, tasks, status } = linsight
            return { sop, sop_map, tasks, isExecuting: status === 'running' }
        } else {
            return { sop: '', tools: [], tasks: [], isExecuting: false }
        }
    }, [getLinsight, sesstionId])

    return (
        <motion.div
            className={`${isExecuting ? 'w-[70%]' : 'flex-1'} relative flex flex-col h-full rounded-2xl border border-[#E8E9ED] bg-white overflow-hidden`}
            initial={{ width: isExecuting ? 'flex-1' : 'flex-1' }}
            animate={{ width: isExecuting ? '70%' : 'flex-1' }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
        >
            <div className='flex items-center gap-2 border-b border-b-[#E8E9ED] bg-[#FDFEFF] p-2 px-4 text-[13px] text-[#737780]'>
                任务流
            </div>

            <div className='relative flex-1 pb-40 min-h-0 overflow-auto'>
                {!isExecuting ? (
                    <div className='flex flex-col h-full justify-center text-center bg-gradient-to-b from-[#F4F8FF] to-white'>
                        <div className='size-10 mx-auto'>
                            <img
                                className='size-full grayscale opacity-20'
                                src={__APP_ENV__.BASE_URL + bsConfig?.sidebarIcon.image}
                                alt="Loading"
                            />
                        </div>
                        <p className='text-sm text-gray-400 mt-7'>确认SOP规划后，任务开始运行</p>
                    </div>
                ) : (
                    <TaskFlowContent tasks={tasks} wsMethod={sendInput} />
                )}
            </div>

            <TaskControls tasks={tasks} isExecuting={isExecuting} stop={stop} />
        </motion.div>
    );
};