import { AnimatePresence, motion } from 'framer-motion';
import { PencilLineIcon } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { useLinsightManager, useLinsightSessionManager } from '~/hooks/useLinsightManager';
import { Button, Textarea } from '../ui';
import Markdown from './Markdown';
import { saveSop, startLinsight } from '~/api/linsight';


export const enum SopStatus {
    /* 未开始 */
    NotStarted = 'not_started',
    /* SOP生成中 */
    SopGenerating = 'sopGenerating',
    /* SOP生成完成 */
    SopGenerated = 'sopGenerated',
    /* 开始执行 */
    Running = 'running',
    /* 执行完成 */
    completed = 'completed',
    /* 反馈完成 */
    FeedbackCompleted = 'feedbackCompleted',
    /* stop */
    Stoped = 'stoped'
}

const slideDownAnimation = {
    initial: { y: 100, opacity: 0 },
    animate: { y: 0, opacity: 1 },
    exit: { y: 0, opacity: 1 },
    transition: { duration: 0.3, ease: "easeInOut" }
};

// 重新规划
const SOPEditorArea = ({ setOpenAreaText, onsubmit }) => {
    const [value, setValue] = useState('');

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault(); // 阻止默认换行行为
            if (value.trim() !== '') {
                submit()
            }
        }
    };

    const submit = () => {
        onsubmit(value);
        setValue('');
        setOpenAreaText(false);
    }

    return <div className='linsight-card w-10/12 mx-auto relative'>
        <Textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder='请在此提出 SOP 重新规划方向的建议'
            className='border-none ![box-shadow:initial]' />
        <div className='flex justify-end gap-2'>
            <Button variant="outline" className="px-6" onClick={() => setOpenAreaText(false)}>
                取消
            </Button>
            <Button disabled={value === ''} className="px-6" onClick={submit}>确认重新规划</Button>
        </div>
    </div>
}

export const SOPEditor = ({ versionId, setIsLoading }) => {
    const [openAreaText, setOpenAreaText] = useState(false)
    const { getLinsight, updateLinsight } = useLinsightManager()
    const markdownRef = useRef(null)

    const linsight = useMemo(() => {
        const linsight = getLinsight(versionId)
        return linsight || { sop: '', question: '', tools: [], status: '' }
    }, [getLinsight, versionId])

    // start
    const handleRun = () => {
        const sop = markdownRef.current.getValue()

        saveSop({
            sop_content: sop,
            linsight_session_version_id: versionId
        }).then(res => {
            if (res.status_code === 200) {
                startLinsight(versionId).then(res => {
                    if (res.status_code === 200) {
                        updateLinsight(versionId, { sop, status: SopStatus.Running })
                    }
                })
            }
        }).catch(err => {
            console.error('err :>> ', err);
        })
    }


    const { setLinsightSubmission } = useLinsightSessionManager(versionId)
    const handleReExcute = (prompt) => {
        setLinsightSubmission(versionId, {
            isNew: false,
            files: [],
            question: linsight.question,
            feedback: prompt,
            tools: [],
            model: 'gpt-4',
            enableWebSearch: false,
            useKnowledgeBase: true
        });
    }

    const showSopEdit = [SopStatus.Running, SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(linsight.status)


    return (
        <motion.div
            className={`${showSopEdit ? 'w-[30%]' : 'w-[70%]'} flex flex-col h-full relative rounded-2xl border border-[#E8E9ED] bg-white`}
            initial={{ width: showSopEdit ? '30%' : '30%' }}
            animate={{ width: showSopEdit ? '30%' : '70%' }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
        >
            <div className='flex items-center gap-2 border-b border-b-[#E8E9ED] bg-[#FDFEFF] p-2 px-4 text-[13px] text-[#737780] rounded-t-2xl'>
                <PencilLineIcon size={14} />
                SOP编辑器
            </div>

            <div className='p-8 linsight-markdown flex-1 pb-40 min-h-0'>
                <Markdown ref={markdownRef} value={linsight.sop} files={linsight.files} tools={linsight.tools} edit={showSopEdit} />
            </div>

            {linsight.status === SopStatus.SopGenerated && (
                <AnimatePresence>
                    <motion.div
                        className='absolute bottom-6 w-full'
                        {...slideDownAnimation}
                    >
                        {!openAreaText ? (
                            <div className='linsight-card w-10/12 mx-auto relative'>
                                {/* <span className='text-lg'>SOP</span> */}
                                <p className='mt-3 text-sm flex gap-2'>
                                    <div className="size-5 rounded-full bg-[radial-gradient(circle_at_center,_white_0%,_white_10%,_#143BFF_80%,_#143BFF_100%)] shadow-xl"></div>
                                    确认是否可以按照 SOP 执⾏任务
                                </p>
                                <div className='absolute right-4 bottom-4 flex gap-2'>
                                    <Button variant="outline" className="px-3" onClick={() => {
                                        const sop = markdownRef.current.getValue()
                                        sop?.trim() === '' ? handleReExcute('') : setOpenAreaText(true)
                                    }}>
                                        重新生成 SOP
                                    </Button>
                                    <Button className="px-6" onClick={handleRun}>
                                        开始执行
                                    </Button>
                                </div>
                            </div>
                        ) : (
                            <SOPEditorArea setOpenAreaText={setOpenAreaText} onsubmit={handleReExcute} />
                        )}
                    </motion.div>
                </AnimatePresence>
            )}
        </motion.div>
    );
};

