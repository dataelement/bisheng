import { useEffect, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { Header } from './Header';
import { SOPEditor } from './SOPEditor';
import { TaskFlow } from './TaskFlow';
import { useGenerateSop } from '~/hooks/useLinsightManager';
import { getLinsightSessionVersionList } from '~/api/linsight';

export default function index(params) {
    // 获取url参数
    const { conversationId } = useParams();
    console.log('conversationId :>> ', conversationId);
    const location = useLocation();
    const [versions, setVersions] = useState<{id: string, name: string}[]>([]);
    const [versionId, setVersionId] = useState('new')

    const [setIsLoading] = useState(true);

    const isLoading = useGenerateSop(versionId, setVersionId, setVersions)
    //

    useEffect(() => {
        getLinsightSessionVersionList("f5dd6fb689dc4b259746eaebd7496269").then(res => {
            console.log('res xx :>> ', res);

            // getLinsightTaskList(versionId)
        })
    }, [conversationId])

    return (
        <div className='h-full bg-gradient-to-b from-[#F4F8FF] to-white'>
            <Header isLoading={isLoading} sesstionId={versionId} versionId={versionId} versions={versions} />

            {isLoading ? <LoadingBox /> : <div className='w-full h-[calc(100vh-68px)] p-2 pt-0'>
                <div className='h-full flex gap-2'>
                    <SOPEditor
                        versionId={versionId}
                        setIsLoading={setIsLoading}
                    />

                    <TaskFlow versionId={versionId} setVersions={setVersions} setVersionId={setVersionId}/>
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
                <div className='w-[194px] h-[102px] bg-no-repeat mx-auto rounded-md'
                    style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/linsi-load.png)` }}></div>
            </div>
            <h1 className='text-2xl mt-10'>为您提供详细 SOP，以确保任务精准</h1>
            <p className='mt-5'>灵思正在为您规划 SOP...</p>
        </div>
    );
};