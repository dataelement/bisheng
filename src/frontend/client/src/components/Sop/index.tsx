import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Header } from './Header';
import { SOPEditor } from './SOPEditor';
import { TaskFlow } from './TaskFlow';
import { useGenerateSop } from '~/hooks/useLinsightManager';

export default function index(params) {
    const location = useLocation();
    const [sesstionId, setSesstionId] = useState('new')
    console.log('location.pathname', location.pathname);

    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        const timer = setTimeout(() => setIsLoading(false), 2000);
        return () => clearTimeout(timer);
    }, []);

    useGenerateSop('new')
    //

    return (
        <div className='h-full bg-gradient-to-b from-[#F4F8FF] to-white'>
            <Header isLoading={isLoading} sesstionId={sesstionId} />

            {isLoading ? <LoadingBox /> : <div className='w-full h-[calc(100vh-68px)] p-2 pt-0'>
                <div className='h-full flex gap-2'>
                    <SOPEditor
                        sesstionId={sesstionId}
                        setIsLoading={setIsLoading}
                    />

                    <TaskFlow sesstionId={sesstionId} />
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