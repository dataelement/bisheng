import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useActivate } from 'react-activation';
import { checkSopQueueStatus, getCaseDetail, getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import { useGetLinsightToolList, useGetOrgToolList, useGetPersonalToolList } from '~/hooks/queries/data-provider';
import { useLinsightManager, useLinsightSubmit } from '~/hooks/useLinsightManager';
import { formatTime } from '~/utils';
import { TaskModeChatInput } from '~/components/Linsight/Input/TaskModeChatInput';
import Landing from '~/components/Chat/Landing';
import { ExecutionFlow } from '~/components/Linsight/Execution/ExecutionFlow';
import { useArtifactsPanel } from '~/components/Linsight/Artifacts/useArtifactsPanel';
import { LoadingIcon } from '../ui/icon/Loading';
import { Header } from './Header';
import { SopStatus } from '~/store/linsight';

export default function index({ id = '', vid = '', shareToken = '' }) {
    // 获取url参数
    const { conversationId: cid, sopId: sid } = useParams();
    const conversationId = cid || id;
    const [isSharePage] = useState(!!vid);
    // 兼容历史链接 case开头
    const sopId = conversationId ? (conversationId.match(/case(\d+)/)?.[1] || '') : sid; // Compatible with historical cases 

    const { loading, versionId, setVersionId, switchVersion, versions, setVersions, checkQueueStatus } = useLinsightData({ conversationId, sopId, vid, shareToken });
    const [isLoading, error] = useLinsightSubmit(versionId, setVersionId, setVersions)
    const { getLinsight } = useLinsightManager()
    const artifactsPanel = useArtifactsPanel();

    return (
        <div className='relative h-full bg-white'>
            {
                loading && <div className='absolute z-10 size-full flex justify-center items-center bg-white/50'>
                    <LoadingIcon />
                </div>
            }
            <Header
                isLoading={isLoading}
                chatId={conversationId}
                setVersionId={switchVersion}
                versionId={versionId}
                isSharePage={isSharePage || sid} // when case sharebutton is hide
                versions={versions}
                onOpenWorkspace={artifactsPanel.openWorkspace}
            />

            {versionId === 'new' && !sopId ? (
                /* F035 Track H: fresh-task landing — unified with the daily
                   landing. Same slogan (Landing) + the daily AiChatInput in
                   task mode (extra "添加技能" entry), no blue gradient. */
                <div className='w-full h-[calc(100vh-68px)] overflow-y-auto'>
                    <div className='flex flex-col min-h-full pt-[20vh] pb-12'>
                        <div className='shrink-0'>
                            <Landing isNew />
                        </div>
                        <div className='w-full max-w-[800px] mx-auto px-3 touch-mobile:max-w-full shrink-0 py-3'>
                            <TaskModeChatInput conversationId={conversationId || 'new'} />
                        </div>
                    </div>
                </div>
            ) : (
                /* F035 Track H (P3): new conversational execution view — replaced
                   the legacy SOPEditor/TaskFlow split panes (removed in P5). */
                <div className='w-full h-[calc(100vh-68px)]'>
                    <ExecutionFlow
                        versionId={versionId}
                        conversationId={conversationId}
                        isSharePage={!!(isSharePage || sopId)}
                        artifactsPanel={artifactsPanel}
                    />
                </div>
            )}
        </div>
    );
}

// "Make same style" (做同款) removed per product decision (F035): the SOP-based
// injection it relied on no longer exists in the de-SOP pipeline.


export const useLinsightData = ({ vid, sopId, conversationId, shareToken }
    : { conversationId: string | undefined, sopId?: string, vid?: string, shareToken?: string }) => {
    // 获取工具列表
    const { data: linsightTools } = useGetLinsightToolList();
    const { data: PersonalTool } = useGetPersonalToolList();
    const { data: orgTools } = useGetOrgToolList({ page: 1 });

    const [loading, setLoading] = useState(false);

    // 状态管理
    const [versions, setVersions] = useState<{ id: string, name: string }[]>([]);
    const [versionId, setVersionId] = useState('new')
    const { getLinsight, updateLinsight, switchAndUpdateLinsight } = useLinsightManager();
    // 检查排队情况
    const checkQueueStatus = useQueueStatus(versionId, updateLinsight)

    const loadSessionVersionsAndTasks = async (_conversationId: string, versionId?: string) => {
        setLoading(true);
        try {
            // 1. 获取会话版本列表
            const data = await getLinsightSessionVersionList(_conversationId, shareToken);
            if (!versionId) {
                const formattedVersions = data.map((item) => ({
                    id: item.id,
                    name: formatTime(item.version, true)
                }));
                setVersions(formattedVersions);
            }

            // 2. 默认选中第一个版本，并加载其任务
            const _versionId = vid || versionId;
            const firstVersion = _versionId ? data.find(el => el.id === (_versionId)) : data[0];
            if (firstVersion) {
                const taskRes = await getLinsightTaskList(firstVersion.id, firstVersion, shareToken);
                setVersionId(vid || firstVersion.id);
                console.log('firstVersion :>> ', firstVersion, taskRes);
                switchAndUpdateLinsight(firstVersion.id, { ...firstVersion, tasks: taskRes });
            }
            setLoading(false);
        } catch (error) {
            setLoading(false);
            console.error('Failed to load session versions or tasks:', error);
        }
    };

    // KeepAlive restore: when navigating back to /linsight/new, reset stale state
    // so useLinsightSubmit watches submissionState('new') instead of the old versionId.
    useActivate(() => {
        const path = window.location.pathname;
        if (path.endsWith('/linsight/new') || path.endsWith('/linsight')) {
            if (versionId !== 'new') {
                setVersionId('new');
                setVersions([]);
            }
        }
    });

    // 加载会话版本和任务
    useEffect(() => {
        // if (!conversationId || conversationId === 'new' || !(linsightTools && PersonalTool && orgTools)) {
        if (!conversationId || conversationId === 'new' || !(linsightTools && orgTools)) {
            return;
        }

        loadSessionVersionsAndTasks(conversationId);
    }, [conversationId, linsightTools, PersonalTool, orgTools]);

    // Get details using sop ID
    useEffect(() => {
        if (sopId) {
            setLoading(true);
            getCaseDetail(sopId).then(res => {
                const { version_info, execute_tasks } = res.data
                setVersions([])
                setVersionId(version_info.id);
                switchAndUpdateLinsight(version_info.id, { ...version_info, tasks: execute_tasks });
                setLoading(false);
            })
        }
    }, [sopId])

    const switchVersion = async (versionId: string) => {
        const linsight = getLinsight(versionId)
        if (linsight) return setVersionId(versionId);
        // 缓存无信息从接口读取
        loadSessionVersionsAndTasks(conversationId!, versionId);
    }

    return {
        loading,
        linsightTools,
        PersonalTool,
        orgTools,
        versions,
        versionId,
        setVersionId,
        switchVersion,
        setVersions,
        checkQueueStatus
    };
};


const useQueueStatus = (vid, updateLinsight) => {
    const timerRef = useRef<any>(null)

    const checkQueueStatus = async (vid: string) => {
        const res = await checkSopQueueStatus(vid);
        const count = res.data.index
        const params = { queueCount: count }
        if (count > 0) {
            params.status = SopStatus.Running
        }
        updateLinsight(vid, params);
        if (count > 0) {
            timerRef.current = setTimeout(() => {
                checkQueueStatus(vid)
            }, 60000)
        } else {
            clearTimeout(timerRef.current)
        }
    }

    useEffect(() => {
        if (vid === 'new') return;
        checkQueueStatus(vid)

        return () => {
            clearTimeout(timerRef.current)
        }
    }, [vid])

    return () => checkQueueStatus(vid)
}