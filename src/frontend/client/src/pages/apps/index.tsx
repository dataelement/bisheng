import { LayoutGrid } from 'lucide-react';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AgentCard } from './components/AgentCard';
import { AppEmptyState } from './components/AppEmptyState';
import { AppSearchBar } from './components/AppSearchBar';
import { useAppCenter } from './hooks/useAppCenter';
import { useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import { ChannelBlocksArrowsIcon } from '~/components/icons/channels';
import { cn } from '~/utils';

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
    const appLastOriginKey = 'app-last-origin';
    const appGridRef = useRef<HTMLDivElement | null>(null);
    const [isMainScrolling, setIsMainScrolling] = useState(false);
    const mainScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const handleMainScroll = () => {
        setIsMainScrolling(true);
        if (mainScrollTimerRef.current) clearTimeout(mainScrollTimerRef.current);
        mainScrollTimerRef.current = setTimeout(() => {
            setIsMainScrolling(false);
            mainScrollTimerRef.current = null;
        }, 600);
    };

    useEffect(() => {
        return () => {
            if (mainScrollTimerRef.current) clearTimeout(mainScrollTimerRef.current);
        };
    }, []);
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

    // Entering app center should reset app-return origin to center.
    // This avoids stale "home-recommended" state on another machine/session
    // causing app-chat back action to jump to /c/new unexpectedly.
    useEffect(() => {
        try {
            sessionStorage.setItem(appLastOriginKey, 'center');
        } catch {
            // ignore storage failures
        }
    }, []);

    const exploreLink = (
        <Link
            to="/apps/explore"
            className="backdrop-blur-[4px] flex shrink-0 items-center justify-center gap-[6px] rounded-[8px] px-[10px] py-[6px] transition-colors fine-pointer:hover:bg-gray-50"
        >
            <ChannelBlocksArrowsIcon className="size-4 text-[#335cff]" />
            <span className="font-['PingFang_SC'] text-[#212121] text-[12px] leading-[20px] whitespace-nowrap">
                探索更多应用
            </span>
        </Link>
    );

    return (
        <div
            className={cn(
                // 填满 MainLayout 白卡片；正文区单独滚动 + scroll-on-scroll（含 PC 窄屏）
                'bg-white flex h-full min-h-0 flex-1 w-full flex-col items-center relative overflow-hidden',
                // 与首页 MobileNav（px-4）水平对齐；顶栏由 MainLayout 提供，正文略留底距
                isH5Layout ? 'px-4 pb-5 pt-3' : 'px-[12px] py-[20px]',
            )}
        >
            {isH5Layout ? (
                <>
                    {/* H5：标题已上移到顶栏（MainLayout）。此行只保留 最近使用文案（可省略）| 探索；下一行搜索占满宽 */}
                    <header className="flex w-full max-w-[1000px] shrink-0 items-center gap-2 min-w-0">
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
                    <header className="relative flex w-full max-w-[1000px] shrink-0 items-center leading-8">
                        <h1 className="font-['PingFang_SC'] font-semibold leading-[32px] text-[#335cff] text-[24px]">
                            应用中心
                        </h1>
                    </header>

                    <div className="mt-4 mb-4 flex w-full max-w-[1000px] min-w-0 shrink-0 items-center gap-4 sm:gap-6">
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

            {/* 内容区域：flex-1 内滚动，PC 窄屏与移动端一致用 scroll-on-scroll */}
            <main
                className="relative flex min-h-0 w-full max-w-[1000px] flex-1 flex-col items-start gap-[14px] overflow-x-hidden overflow-y-auto scroll-on-scroll"
                onScroll={handleMainScroll}
                data-scrolling={isMainScrolling ? 'true' : 'false'}
            >
                {loading ? (
                    <div className="flex w-full flex-1 items-center justify-center">
                        <LoadingIcon className="size-20 text-primary" />
                    </div>
                ) : apps.length === 0 ? (
                    <div className="w-full flex-1 flex items-center justify-center">
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