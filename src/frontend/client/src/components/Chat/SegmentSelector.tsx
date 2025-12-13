import { useLocalize } from '~/hooks';

const SegmentSelector = ({ lingsi, onChange }) => {
    const localize = useLocalize();

    return (
        <div className="w-full">
            {/* 选项卡容器 */}
            <div className="p-1 rounded-full border flex">
                <button
                    className={`flex-1 py-1.5 px-8 rounded-full text-sm break-keep transition-all ${!lingsi
                        ? 'bg-blue-50 shadow-sm'
                        : '0'
                        }`}
                    onClick={() => onChange(false)}
                >
                    {localize('com_segment_daily_mode')}
                </button>
                <button
                    className={`flex-1 py-1.5 px-8 rounded-full text-sm break-keep transition-all ${lingsi
                        ? 'bg-blue-50 shadow-sm'
                        : ''
                        }`}
                    onClick={() => onChange(true)}
                >
                    <div className='flex items-center justify-center relative'>
                        {lingsi && <img src={__APP_ENV__.BASE_URL + "/assets/lingsi.svg"} className='size-4 block' alt="" />}
                        <span className={lingsi ? 'lingsi-text ml-2' : ''}>{localize('com_segment_linsight')}</span>
                    </div>
                </button>
            </div>
        </div >
    );
};

export default SegmentSelector;