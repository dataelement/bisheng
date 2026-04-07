import { useLocalize } from '~/hooks';

const SegmentSelector = ({ lingsi, onChange, bsConfig }) => {
    const localize = useLocalize();

    return (
        <div className="w-full">
            <div className="p-1 rounded-full border border-[#e5e6eb] bg-white/80 flex shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
                <button
                    type="button"
                    className={`flex-1 py-2 max-[575px]:py-2 px-3 max-[575px]:px-3 md:px-8 rounded-full text-sm max-[575px]:text-[13px] break-keep transition-all font-medium ${!lingsi
                        ? 'bg-[#E6EDFC] text-[#165DFF] shadow-sm'
                        : 'text-[#1d2129] bg-transparent'
                        }`}
                    onClick={() => onChange(false)}
                >
                    {bsConfig.tabDisplayName ? bsConfig.tabDisplayName : localize('com_segment_daily_mode')}
                </button>
                <button
                    type="button"
                    className={`flex-1 py-2 max-[575px]:py-2 px-3 max-[575px]:px-3 md:px-8 rounded-full text-sm max-[575px]:text-[13px] break-keep transition-all font-medium ${lingsi
                        ? 'bg-[#E6EDFC] text-[#165DFF] shadow-sm'
                        : 'text-[#1d2129] bg-transparent'
                        }`}
                    onClick={() => onChange(true)}
                >
                    <div className="flex items-center justify-center gap-1 relative">
                        {lingsi && <img src={__APP_ENV__.BASE_URL + "/assets/lingsi.svg"} className="size-4 block shrink-0" alt="" />}
                        <span className={lingsi ? 'lingsi-text' : ''}>
                            {bsConfig.linsightConfig.tab_display_name ? bsConfig.linsightConfig.tab_display_name : localize('com_segment_linsight')}
                        </span>
                    </div>
                </button>
            </div>
        </div>
    );
};

export default SegmentSelector;