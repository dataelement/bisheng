import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { checkSopQueueStatus, getCaseDetail, getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import { useGetLinsightToolList, useGetOrgToolList, useGetPersonalToolList } from '~/data-provider';
import { useGenerateSop, useLinsightManager } from '~/hooks/useLinsightManager';
import { formatTime } from '~/utils';
import { LoadingIcon } from '../ui/icon/Loading';
import { LoadingBox } from './components/SopLoading';
import { Header } from './Header';
import { SOPEditor, SopStatus } from './SOPEditor';
import { TaskFlow } from './TaskFlow';

export default function index() {
    // 获取url参数
    const { conversationId, sopId: sid } = useParams();
    const sopId = conversationId ? conversationId.replace('case', '') : sid; // Compatible with historical cases 

    const { loading, versionId, setVersionId, switchVersion, versions, setVersions, checkQueueStatus } = useLinsightData(conversationId, sopId);
    const [isLoading, error] = useGenerateSop(versionId, setVersionId, setVersions)

    return (
        <div className='relative h-full bg-gradient-to-b from-[#F4F8FF] to-white'>
            {
                loading && <div className='absolute z-10 size-full flex justify-center items-center bg-white/50'>
                    <LoadingIcon />
                </div>
            }
            <Header isLoading={isLoading} setVersionId={switchVersion} versionId={versionId} versions={versions} />

            {isLoading ? <LoadingBox /> : <div className='w-full h-[calc(100vh-68px)] p-2 pt-0'>
                <div className='h-full flex gap-2'>
                    <SOPEditor
                        sopError={error}
                        versionId={versionId}
                        onRun={checkQueueStatus}
                    />

                    <TaskFlow versionId={versionId} setVersions={setVersions} setVersionId={setVersionId} />
                </div>
            </div>}
        </div>
    );
}


export const useLinsightData = (conversationId: string | undefined, sopId?: string) => {
    // 获取工具列表
    const { data: linsightTools } = useGetLinsightToolList();
    const { data: PersonalTool } = useGetPersonalToolList();
    const { data: orgTools } = useGetOrgToolList();

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
            const data = await getLinsightSessionVersionList(_conversationId);
            if (!versionId) {
                const formattedVersions = data.map((item) => ({
                    id: item.id,
                    name: formatTime(item.version, true)
                }));
                setVersions(formattedVersions);
            }

            // 2. 默认选中第一个版本，并加载其任务
            const firstVersion = versionId ? data.find(el => el.id === versionId) : data[0];
            if (firstVersion) {
                const taskRes = await getLinsightTaskList(firstVersion.id, firstVersion);
                setVersionId(firstVersion.id);
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
        if (!conversationId || conversationId === 'new' || !(linsightTools && PersonalTool && orgTools)) {
            return;
        }

        loadSessionVersionsAndTasks(conversationId);
    }, [conversationId, linsightTools, PersonalTool, orgTools]);

    // Get details using sop ID
    useEffect(() => {
        if (sopId) {
            getCaseDetail(sopId).then(res => {
                const { version_info, execute_tasks } = res.data
                setVersions([])
                setVersionId(version_info.id);
                switchAndUpdateLinsight(version_info.id, { ...version_info, tasks: execute_tasks });
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