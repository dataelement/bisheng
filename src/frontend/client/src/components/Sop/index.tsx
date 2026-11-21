// @ts-strict-ignore
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useActivate } from 'react-activation';
import { getCaseDetail, getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import { useGetLinsightToolList, useGetOrgToolList, useGetPersonalToolList } from '~/hooks/queries/data-provider';
import { useLinsightManager } from '~/hooks/useLinsightManager';
import { useOpenDeepResearchChat } from '~/components/Nav/NewChat';
import { formatTime } from '~/utils';
import { ExecutionFlow } from '~/components/Linsight/Execution/ExecutionFlow';
import { useArtifactsPanel } from '~/components/Linsight/Artifacts/useArtifactsPanel';
import { LoadingIcon } from '../ui/icon/Loading';
import { Header } from './Header';

export default function SopPage({ id = '', vid = '', shareToken = '' }) {
    // 获取url参数
    const { conversationId: cid, sopId: sid } = useParams();
    const conversationId = cid || id;
    const [isSharePage] = useState(!!vid);
    // 兼容历史链接 case开头
    const sopId = conversationId ? (conversationId.match(/case(\d+)/)?.[1] || '') : sid; // Compatible with historical cases 

    const { loading, versionId, switchVersion, versions } = useLinsightData({ conversationId, sopId, vid, shareToken });
    const artifactsPanel = useArtifactsPanel(versionId);
    // F004 (decision 11): this page only shows stored tasks. A new task starts
    // on the conversation page with deep research turned on.
    const isLanding = !sopId && !vid && (!conversationId || conversationId === 'new');
    const openDeepResearchChat = useOpenDeepResearchChat();
    useEffect(() => {
        if (isLanding) openDeepResearchChat();
        // eslint-disable-next-line react-hooks/exhaustive-deps -- run on entering the landing only
    }, [isLanding]);
    useActivate(() => {
        if (isLanding) openDeepResearchChat();
    });
    if (isLanding) return null;

    return (
        <div className='relative h-full bg-white'>
            {
                loading && <div className='absolute z-10 size-full flex justify-center items-center bg-white/50'>
                    <LoadingIcon className="size-20" />
                </div>
            }
            <Header
                chatId={conversationId}
                setVersionId={switchVersion}
                versionId={versionId}
                isSharePage={isSharePage || sid} // when case sharebutton is hide
                versions={versions}
                onOpenWorkspace={artifactsPanel.openWorkspace}
            />

            <div className='w-full h-[calc(100vh-68px)]'>
                <ExecutionFlow
                    versionId={versionId}
                    isSharePage={!!(isSharePage || sopId)}
                    artifactsPanel={artifactsPanel}
                />
            </div>
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
    const { getLinsight, switchAndUpdateLinsight } = useLinsightManager();
    // Queue-status polling now lives inside ExecutionFlow via
    // useLinsightQueuePolling (shared with the F035 daily-chat TaskTurnPanel),
    // so the page-level hook is no longer needed here.

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
    };
};