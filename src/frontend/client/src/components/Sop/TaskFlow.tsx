import { motion } from 'framer-motion';
import cloneDeep from 'lodash/cloneDeep';
import { useEffect, useMemo, useRef } from 'react';
import { submitLinsightFeedback } from '~/api/linsight';
import { useGetBsConfig } from '~/data-provider';
import { useLinsightManager, useLinsightSessionManager } from '~/hooks/useLinsightManager';
import { useLinsightWebSocket } from '~/hooks/Websocket';
import { useToastContext } from '~/Providers';
import { useLocalize } from '~/hooks';
import { SopStatus } from './SOPEditor';
import { TaskControls } from './TaskControls';
import { TaskFlowContent } from './TaskFlowContent';
import { formatTime } from '~/utils';
import { useAutoScroll } from '~/hooks/useAutoScroll';

export const TaskFlow = ({ versionId, setVersions, setVersionId }) => {
    const { data: bsConfig } = useGetBsConfig();
    const { createLinsight, getLinsight, updateLinsight } = useLinsightManager()
    const { showToast } = useToastContext();
    const { stop, sendInput } = useLinsightWebSocket(versionId)
    const localize = useLocalize()

    const linsight = useMemo(() => {
        const linsight = getLinsight(versionId)
        return linsight || { sop: '', tools: [], tasks: [], status: '', queueCount: 0 }
    }, [getLinsight, versionId])

    const showTask = [SopStatus.Running, SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(linsight.status)

    const currentTask = useMemo(() => {
        const runningTask = linsight.tasks.find(task => task.status !== 'success')

        if (runningTask) {
            return runningTask; // 返回第一个未完成的任务
        }

        //  如果没有未完成子任务的任务，则返回最后一个任务
        return linsight.tasks[linsight.tasks.length - 1];
    }, [linsight.tasks]);

    const { setLinsightSubmission } = useLinsightSessionManager(versionId)
    // 提交反馈
    const handleFeedback = (rating, comment, check, cancel) => {
        submitLinsightFeedback(versionId, {
            feedback: comment,
            score: rating,
            is_reexecute: check,
            cancel_feedback: cancel
        }).then(res => {
            if (res.status_code !== 200) {
                return
            }

            const newVersionId = res.data.id
            updateLinsight(versionId, { status: SopStatus.FeedbackCompleted })
            !cancel && showToast({ status: 'success', message: localize('com_sop_submit_success') })
            if (res.data === true) return

            // 克隆当前版本
            const cloneLinsight = cloneDeep(linsight)
            createLinsight(newVersionId, {
                ...cloneLinsight,
                id: newVersionId,
                version: res.data.version,
                tasks: [],
                summary: '',
                file_list: [],
                status: SopStatus.NotStarted
            })

            setVersions((prve) => [{
                id: newVersionId,
                name: formatTime(res.data.version, true)
            }, ...prve])
            setVersionId(newVersionId)
            // 切换版本
            check && !cancel && setLinsightSubmission(newVersionId, {
                prevVersionId: versionId,
                isNew: false,
                files: [],
                question: linsight.question,
                feedback: comment,
                tools: [],
                model: 'gpt-4',
                enableWebSearch: false,
                useKnowledgeBase: true
            });
        })
    }

    // 自动滚动到底部
    const flowScrollRef = useRef(null)
    useEffect(() => {
        if ([SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(linsight.status) && flowScrollRef.current) {
            flowScrollRef.current.scrollTop = flowScrollRef.current.scrollHeight;
        }
    }, [linsight.status, versionId])

    useAutoScroll(flowScrollRef, linsight.tasks)

    return (
        <motion.div
            className={`${showTask ? 'w-[70%]' : 'flex-1'} relative flex flex-col h-full rounded-2xl border border-[#E8E9ED] bg-white overflow-hidden`}
            initial={{ width: showTask ? 'flex-1' : 'flex-1' }}
            animate={{ width: showTask ? '70%' : 'flex-1' }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
        >
            <div className='flex items-center gap-2 border-b border-b-[#E8E9ED] bg-[#FDFEFF] p-2 px-4 text-[13px] text-[#737780]'>
                {localize('com_sop_task_flow')}
            </div>

            <div ref={flowScrollRef} className='relative flex-1 pb-80 min-h-0 scroll-hover'>
                {!showTask && (
                    <div className='flex flex-col h-full justify-center text-center bg-gradient-to-b from-[#F4F8FF] to-white'>
                        <div className='size-10 mx-auto'>
                            <img
                                className='size-full grayscale opacity-20'
                                src={__APP_ENV__.BASE_URL + bsConfig?.sidebarIcon.image}
                                alt="Loading"
                            />
                        </div>
                        <p className='text-sm text-gray-400 mt-7'>{localize('com_sop_waiting_message')}</p>
                    </div>
                )}
                {
                    showTask && <TaskFlowContent
                        key={versionId}
                        linsight={linsight}
                        sendInput={sendInput}
                    />
                }
            </div>

            <TaskControls
                key={versionId}
                current={currentTask}
                tasks={linsight.tasks}
                status={linsight.status}
                queueCount={linsight.queueCount}
                feedbackProvided={!!linsight.execute_feedback}
                onStop={stop}
                onFeedback={handleFeedback}
            />
        </motion.div>
    );
};