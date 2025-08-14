import { useEffect, useState } from 'react';

const SegmentSelector = ({ onChange }) => {
    const [activeTab, setActiveTab] = useState('base');

    useEffect(() => {
        onChange(activeTab === 'lingsi')
    }, [activeTab, onChange])

    return (
        <div className="w-full">
            {/* 选项卡容器 */}
            <div className="p-1 rounded-full border flex">
                <button
                    className={`flex-1 py-1.5 px-8 rounded-full text-sm break-keep transition-all ${activeTab === 'base'
                        ? 'bg-blue-50 shadow-sm'
                        : '0'
                        }`}
                    onClick={() => {
                        setActiveTab('base');
                        window.isLinsight = false
                    }}
                >
                    日常模式
                </button>
                <button
                    className={`flex-1 py-1.5 px-8 rounded-full text-sm break-keep transition-all ${activeTab === 'lingsi'
                        ? 'bg-blue-50 shadow-sm'
                        : ''
                        }`}
                    onClick={() => {
                        setActiveTab('lingsi');
                        window.isLinsight = true
                    }}
                >
                    <div className='flex items-center justify-center relative'>
                        {activeTab === 'lingsi' && <img src={__APP_ENV__.BASE_URL + "/assets/lingsi.svg"} className='size-4 block' alt="" />}
                        <span className={activeTab === 'lingsi' ? 'lingsi-text ml-2' : ''}>灵思Linsight</span>
                    </div>
                </button>
            </div>
        </div >
    );
};

export default SegmentSelector;