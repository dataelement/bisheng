import { Outlined } from 'bisheng-icons';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { useCallback, useEffect, useRef, useState, type UIEvent } from 'react';
import { Trans } from 'react-i18next';
import { Link } from 'react-router-dom';
import { MODULE_HOME_BODY, MODULE_HOME_COLUMN, MODULE_HOME_FRAME, MODULE_HOME_INTRO, ModuleHomeHeader } from '~/components/ModuleHome';
import { AgentCard } from './components/AgentCard';
import { AppEmptyState } from './components/AppEmptyState';
import { AppSearchBar } from './components/AppSearchBar';
import { EmptyStateIllustration } from '~/components/illustrations';
import { useAppCenter } from './hooks/useAppCenter';
import { useLocalize, usePrefersMobileLayout, useWorkbenchMenuNames } from '~/hooks';
import { cn } from '~/utils';

export default function AppCenter() {
    const localize = useLocalize();
    // 页面标题跟随后台配置的菜单显示名称
    const menuNames = useWorkbenchMenuNames();
    const {
        apps,
        loading,
        loadingMore,
        loadError,
        loadMoreError,
        hasMore,
        searchQuery,
        setSearchQuery,
        fetchApps,
        loadMore,
        togglePin,
        continueChat,
        shareApp,
    } = useAppCenter();

    // Mobile layout (≤767px) is when MainLayout shows its own centered top-bar
    // title, so the page must drop its inline big title to avoid a duplicate.
    const isMobileLayout = usePrefersMobileLayout();
    const appLastOriginKey = 'app-last-origin';
    const mainRef = useRef<HTMLElement | null>(null);
    const appGridRef = useRef<HTMLDivElement | null>(null);
    const loadMoreSentinelRef = useRef<HTMLDivElement | null>(null);
    const loadMoreLockRef = useRef(false);
    const [isMainScrolling, setIsMainScrolling] = useState(false);
    const mainScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const triggerLoadMore = useCallback(() => {
        if (loadMoreLockRef.current || loading || loadingMore || loadMoreError || !hasMore) return;
        loadMoreLockRef.current = true;
        loadMore();
    }, [hasMore, loadMore, loadMoreError, loading, loadingMore]);

    const handleMainScroll = (event: UIEvent<HTMLElement>) => {
        setIsMainScrolling(true);
        if (mainScrollTimerRef.current) clearTimeout(mainScrollTimerRef.current);
        mainScrollTimerRef.current = setTimeout(() => {
            setIsMainScrolling(false);
            mainScrollTimerRef.current = null;
        }, 600);

        const node = event.currentTarget;
        if (node.scrollTop + node.clientHeight >= node.scrollHeight - 240) {
            triggerLoadMore();
        }
    };

    useEffect(() => {
        return () => {
            if (mainScrollTimerRef.current) clearTimeout(mainScrollTimerRef.current);
        };
    }, []);

    useEffect(() => {
        if (!loadingMore) loadMoreLockRef.current = false;
    }, [loadingMore]);

    const [appGridCols, setAppGridCols] = useState(() => {
        if (typeof window === 'undefined') return 3;
        const width = window.innerWidth;
        const mobile = window.matchMedia('(max-width: 767px)').matches;
        if (mobile) {
            return width < 480 ? 1 : 2;
        }
        if (width < 480) return 1;
        if (width < 600) return 2;
        return 3;
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
            return 3;
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
    }, [apps.length, isMobileLayout]);

    useEffect(() => {
        const root = mainRef.current;
        const target = loadMoreSentinelRef.current;
        if (!root || !target) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting) triggerLoadMore();
            },
            { root, rootMargin: '240px 0px', threshold: 0 },
        );
        observer.observe(target);
        return () => observer.disconnect();
    }, [apps.length, triggerLoadMore]);

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

    return (
        <div
            className={cn(
                MODULE_HOME_FRAME,
                'relative flex-1',
                // Align with the mobile shell's navigation and preserve its content spacing.
                isMobileLayout && 'px-4 pb-5 pt-3 [--module-home-compact-padding:12px_16px_20px]',
            )}
        >
            {!isMobileLayout && (
                <ModuleHomeHeader title={menuNames.apps}>
                    <div className="w-auto min-w-[120px] shrink-0">
                        <AppSearchBar query={searchQuery} onSearch={setSearchQuery} forceExpanded />
                    </div>
                </ModuleHomeHeader>
            )}
            <p className={cn(
                MODULE_HOME_COLUMN,
                'flex min-w-0 shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-text-2',
                isMobileLayout ? 'text-body-sm' : [MODULE_HOME_INTRO, 'my-4 text-body'],
            )}>
                <span>{localize('com_app.recent_apps_hint')}</span>
                <span>
                    <Trans
                        i18nKey="com_app.explore_plaza"
                        components={{
                            cta: <Link to="/apps/explore" className="inline-flex items-center gap-0.5 font-normal text-blue-500 hover:text-blue-600" />,
                            arrow: <Outlined.ArrowRight aria-hidden className="size-3.5 shrink-0" />,
                        }}
                    />
                </span>
            </p>
            {isMobileLayout && (
                <div className={cn(MODULE_HOME_COLUMN, 'mt-3 mb-4 shrink-0 min-w-0')}>
                    <AppSearchBar query={searchQuery} onSearch={setSearchQuery} forceExpanded />
                </div>
            )}

            {/* 内容区域：flex-1 内滚动，PC 窄屏与移动端一致用 scroll-on-scroll。
                滚动区占满整宽（滚动条贴最右），内容居中约束在 1000px */}
            <main
                ref={mainRef}
                className={cn(MODULE_HOME_BODY, 'relative flex min-h-0 w-full flex-1 flex-col items-center overflow-x-hidden overflow-y-auto scroll-on-scroll')}
                onScroll={handleMainScroll}
                data-scrolling={isMainScrolling ? 'true' : 'false'}
            >
                <div className={cn(MODULE_HOME_COLUMN, 'flex flex-1 flex-col items-start gap-[14px]')}>
                    {loading ? (
                        <div className="flex w-full flex-1 flex-col items-center justify-center gap-3 text-text-3">
                            <LoadingIcon className="size-20 text-primary" />
                            <span className="text-sm">{localize('com_list_loading')}</span>
                        </div>
                    ) : loadError ? (
                        <div className="flex w-full flex-1 items-center justify-center text-text-3">
                            <p className="text-[14px] font-normal">{localize('com_list_load_failed')}</p>
                        </div>
                    ) : apps.length === 0 ? (
                        // Empty state: fill the region and place content via flex spacers at a
                        // region-relative height (not viewport vh): ~40% on mobile, ~45% on PC.
                        <div className="w-full flex-1 flex flex-col items-center">
                            <div className="flex-[8] md:flex-[9]" aria-hidden />
                            {searchQuery ? (
                                <>
                                    <EmptyStateIllustration className="size-[120px] mb-4" />
                                    <p className="text-[14px] font-normal text-text-3">{localize('com_list_no_results')}</p>
                                </>
                            ) : (
                                <AppEmptyState />
                            )}
                            <div className="flex-[12] md:flex-[11]" aria-hidden />
                        </div>
                    ) : (
                        <>
                            <div
                                ref={appGridRef}
                                className="grid w-full relative items-start gap-4"
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
                            <div ref={loadMoreSentinelRef} className="flex h-12 w-full items-center justify-center text-[12px] text-text-4">
                                {loadingMore
                                    ? localize('com_list_loading_more')
                                    : loadMoreError
                                        ? localize('com_list_load_failed')
                                        : !hasMore
                                            ? localize('com_list_all_loaded')
                                            : ''}
                            </div>
                        </>
                    )}
                </div>
            </main>
        </div>
    );
}
