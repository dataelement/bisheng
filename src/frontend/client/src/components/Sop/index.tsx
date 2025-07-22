import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import { useGetLinsightToolList, useGetOrgToolList, useGetPersonalToolList } from '~/data-provider';
import { useGenerateSop, useLinsightManager } from '~/hooks/useLinsightManager';
import { Header } from './Header';
import { SOPEditor } from './SOPEditor';
import { TaskFlow } from './TaskFlow';

export default function index(params) {
    // 获取url参数
    const { conversationId } = useParams();

    const { versionId, setVersionId, switchVersion, versions, setVersions } = useLinsightData(conversationId);
    const [isLoading, error] = useGenerateSop(versionId, setVersionId, setVersions)

    return (
        <div className='h-full bg-gradient-to-b from-[#F4F8FF] to-white'>
            <Header isLoading={isLoading} setVersionId={switchVersion} versionId={versionId} versions={versions} />

            {isLoading ? <LoadingBox /> : <div className='w-full h-[calc(100vh-68px)] p-2 pt-0'>
                <div className='h-full flex gap-2'>
                    <SOPEditor
                        sopError={error}
                        versionId={versionId}
                    />

                    <TaskFlow versionId={versionId} setVersions={setVersions} setVersionId={setVersionId} />
                </div>
            </div>}
        </div>
    );
}

// LoadingBox组件
const LoadingBox = () => {
    return (
        <div className='h-full bg-white border border-[#E8E9ED] rounded-xl flex flex-col justify-center text-center'>
            <div className="lingsi-border-box mx-auto">
                <div className='w-[194px] h-[102px] bg-no-repeat mx-auto rounded-md bg-white'
                    style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/linsi-load.png)` }}></div>
            </div>
            <h1 className='text-2xl mt-10'>为您提供详细 SOP，以确保任务精准</h1>
            <p className='mt-5'>灵思正在为您规划 SOP...</p>
        </div>
    );
};


export const useLinsightData = (conversationId: string | undefined) => {
    // 获取工具列表
    const { data: linsightTools } = useGetLinsightToolList();
    const { data: PersonalTool } = useGetPersonalToolList();
    const { data: orgTools } = useGetOrgToolList();

    // 状态管理
    const [versions, setVersions] = useState<{ id: string, name: string }[]>([]);
    const [versionId, setVersionId] = useState('new')
    const { getLinsight, switchAndUpdateLinsight } = useLinsightManager();

    const loadSessionVersionsAndTasks = async (_conversationId: string, versionId?: string) => {
        try {
            // 1. 获取会话版本列表
            const data = await getLinsightSessionVersionList(_conversationId);
            if (!versionId) {
                const formattedVersions = data.map((item) => ({
                    id: item.id,
                    name: item.version.replace('T', ' ').replaceAll('-', '/').slice(0, -3)
                }));
                setVersions(formattedVersions);
            }

            // 2. 默认选中第一个版本，并加载其任务
            const firstVersion = versionId ? data.find(el => el.id === versionId) : data[0];
            if (firstVersion) {
                setVersionId(firstVersion.id);
                const taskRes = await getLinsightTaskList(firstVersion.id, firstVersion);
                switchAndUpdateLinsight(firstVersion.id, { ...firstVersion, tasks: taskRes });
            }
        } catch (error) {
            console.error('Failed to load session versions or tasks:', error);
        }
    };

    // 加载会话版本和任务
    useEffect(() => {
        if (!conversationId || conversationId === 'new' || !(linsightTools && PersonalTool && orgTools)) {
            return;
        }

        loadSessionVersionsAndTasks(conversationId);
    }, [conversationId, linsightTools, PersonalTool, orgTools, switchAndUpdateLinsight]);


    const switchVersion = async (versionId: string) => {
        const linsight = getLinsight(versionId)
        if (linsight) return setVersionId(versionId);
        // 缓存无信息从接口读取
        loadSessionVersionsAndTasks(conversationId!, versionId);
    }

    return {
        linsightTools,
        PersonalTool,
        orgTools,
        versions,
        versionId,
        setVersionId,
        switchVersion,
        setVersions
    };
};

