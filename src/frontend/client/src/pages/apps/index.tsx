import { Loader2, LayoutGrid } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AgentCard } from './components/AgentCard';
import { AppEmptyState } from './components/AppEmptyState';
import { AppSearchBar } from './components/AppSearchBar';
import { useAppCenter } from './hooks/useAppCenter';
import { useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import { ChannelBlocksArrowsIcon } from '~/components/icons/channels';

const RECENT_APPS_HINT = '最近使用过的应用都在这里～';

export default function AppCenter() {
    const {
        apps,
        loading,
        searchQuery,
        setSearchQuery,
        fetchApps,
        togglePin,
        continueChat,
        shareApp,
    } = useAppCenter();

    const isH5Layout = useMediaQuery('(max-width: 576px)');
    const isMobileLayout = usePrefersMobileLayout();
    const appGridRef = useRef<HTMLDivElement | null>(null);
    const [appGridCols, setAppGridCols] = useState(() => {
        if (typeof window === 'undefined') return 4;
        const width = window.innerWidth;
        const mobile = window.matchMedia('(max-width: 767px)').matches;
        if (mobile) {
            return width < 480 ? 1 : 2;
        }
        if (width < 480) return 1;
        if (width < 600) return 2;
        if (width < 768) return 3;
        return 4;
    });

    useEffect(() => {
        // Prevent first-render flash: when entering on mobile, clamp columns
        // from viewport width before ResizeObserver reports container width.
        if (typeof window !== 'undefined' && isMobileLayout) {
            const width = window.innerWidth;
            setAppGridCols(width < 480 ? 1 : 2);
        }

        const el = appGridRef.current;
        if (!el || typeof ResizeObserver === 'undefined') return;

        const resolveCols = (width: number) => {
            if (width < 480) return 1;
            if (width < 600) return 2;
            if (width < 768) return 3;
            return 4;
        };

        const update = () => {
            const width = el.clientWidth;
            if (isMobileLayout) {
                setAppGridCols(width < 480 ? 1 : 2);
                return;
            }
            setAppGridCols(resolveCols(width));
        };

        update();

        const observer = new ResizeObserver(update);
        observer.observe(el);
        return () => observer.disconnect();
    }, [isMobileLayout]);

    // Initial fetch
    useEffect(() => {
        fetchApps();
    }, [fetchApps]);

    const exploreLink = (
        <Link
            to="/apps/explore"
            className="backdrop-blur-[4px] flex shrink-0 items-center justify-center gap-[6px] px-[10px] py-[6px] rounded-[8px] hover:bg-gray-50 transition-colors"
        >
            <ChannelBlocksArrowsIcon className="size-4 text-[#335cff]" />
            <span className="font-['PingFang_SC'] text-[#212121] text-[12px] leading-[20px] whitespace-nowrap">
                探索更多应用
            </span>
        </Link>
    );

    return (
        <div className="bg-white min-h-screen flex flex-col items-center px-[12px] py-[20px] relative w-full">
            {isH5Layout ? (
                <>
                    {/* H5：一行 — 应用中心 | 最近使用文案（可省略）| 探索；下一行搜索占满宽 */}
                    <header className="flex w-full max-w-[1000px] shrink-0 items-center gap-2 min-w-0">
                        <h1 className="font-['PingFang_SC'] font-semibold leading-[28px] text-[#335cff] text-[20px] shrink-0">
                            应用中心
                        </h1>
                        <p
                            className="font-['PingFang_SC'] text-[#666] text-[13px] leading-[20px] min-w-0 flex-1 truncate"
                            title={RECENT_APPS_HINT}
                        >
                            {RECENT_APPS_HINT}
                        </p>
                        {exploreLink}
                    </header>
                    <div className="mt-3 mb-4 w-full max-w-[1000px] shrink-0 min-w-0">
                        <AppSearchBar query={searchQuery} onSearch={setSearchQuery} forceExpanded />
                    </div>
                </>
            ) : (
                <>
                    <header className="flex items-center leading-8 max-w-[1000px] w-full shrink-0 relative">
                        <h1 className="font-['PingFang_SC'] font-semibold leading-[32px] text-[#335cff] text-[24px]">
                            应用中心
                        </h1>
                    </header>

                    <div className="flex max-w-[1000px] w-full min-w-0 shrink-0 items-center gap-4 sm:gap-6 mt-4 mb-4">
                        <div className="flex min-w-0 flex-1 items-center justify-start overflow-hidden">
                            <div className="flex w-max max-w-full min-w-0 items-center gap-[24px]">
                                <p
                                    className="font-['PingFang_SC'] text-[#666] text-[14px] leading-[22px] min-w-0 shrink truncate"
                                    title={RECENT_APPS_HINT}
                                >
                                    {RECENT_APPS_HINT}
                                </p>
                                {exploreLink}
                            </div>
                        </div>
                        <div className="shrink-0 min-w-[120px] w-auto">
                            <AppSearchBar query={searchQuery} onSearch={setSearchQuery} forceExpanded />
                        </div>
                    </div>
                </>
            )}

            {/* 内容区域 */}
            <main className="flex flex-col items-start gap-[14px] max-w-[1000px] w-full shrink-0 relative">
                {loading ? (
                    <div className="flex w-full items-center justify-center py-20">
                        <Loader2 className="animate-spin text-[#335cff] size-8" />
                    </div>
                ) : apps.length === 0 ? (
                    <div className="w-full flex items-center justify-center py-10">
                        <AppEmptyState />
                    </div>
                ) : (
                    <div
                        ref={appGridRef}
                        className="grid w-full relative gap-x-3 gap-y-3.5"
                        style={{ gridTemplateColumns: `repeat(${appGridCols}, minmax(0, 1fr))` }}
                    >
                        {apps.map((agent) => (
                            <AgentCard
                                key={agent.id}
                                agent={agent}
                                isPinned={!!agent.is_pinned}
                                onTogglePin={togglePin}
                                onStartChat={continueChat}
                                onShare={shareApp}
                            />
                        ))}
                    </div>
                )}
            </main>
        </div>
    );
}