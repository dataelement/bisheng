import { Loader2, LayoutGrid } from 'lucide-react';
import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { AgentCard } from './components/AgentCard';
import { AppEmptyState } from './components/AppEmptyState';
import { AppSearchBar } from './components/AppSearchBar';
import { useAppCenter } from './hooks/useAppCenter';

export default function AppCenter() {
    const {
        apps,
        loading,
        searchQuery,
        setSearchQuery,
        fetchApps,
        togglePin,
        isPinned,
        continueChat,
        shareApp,
    } = useAppCenter();

    // Initial fetch
    useEffect(() => {
        fetchApps();
    }, [fetchApps]);

    return (
        <div className="bg-white min-h-screen flex flex-col items-center px-[12px] py-[20px] relative w-full">
            {/* 顶部页眉 */}
            <header className="flex items-center justify-between leading-8 max-w-[1000px] w-full shrink-0 relative max-[576px]:flex-col max-[576px]:items-start gap-2">
                <h1 className="font-['PingFang_SC'] font-semibold leading-[32px] text-[#335cff] text-[24px]">
                    应用中心
                </h1>
                <div className="max-[576px]:w-full max-[576px]:pt-1">
                    <AppSearchBar query={searchQuery} onSearch={setSearchQuery} />
                </div>
            </header>

            {/* 副标题与探索更多 */}
            <div className="flex items-center gap-[24px] max-w-[1000px] w-full shrink-0 relative mt-4 mb-4 max-[576px]:flex-col max-[576px]:items-start max-[576px]:gap-2">
                <p className="font-['PingFang_SC'] text-[#666] text-[14px] leading-[22px] max-[576px]:line-clamp-1 max-[576px]:overflow-hidden max-[576px]:text-[13px]">
                    最近使用过的应用都在这里～
                </p>
                <Link
                    to="/apps/explore"
                    className="backdrop-blur-[4px] flex items-center justify-center gap-[6px] px-[10px] py-[6px] rounded-[8px] hover:bg-gray-50 transition-colors max-[576px]:w-full"
                >
                    <LayoutGrid size={16} className="text-[#335cff]" />
                    <span className="font-['PingFang_SC'] text-[#212121] text-[12px] leading-[20px] max-[576px]:text-[13px]">
                        探索更多应用
                    </span>
                </Link>
            </div>

            {/* 内容区域 */}
            <main className="flex flex-col items-start gap-[14px] max-w-[1000px] w-full shrink-0 relative">
                {loading ? (
                    <div className="flex w-full items-center justify-center py-20">
                        <Loader2 className="animate-spin text-[#335cff] size-8" />
                    </div>
                ) : apps.length === 0 ? (
                    <div className="w-full flex items-center justify-center py-10">
                        <AppEmptyState query={searchQuery} />
                    </div>
                ) : (
                    <div className="grid grid-cols-1 max-[576px]:grid-cols-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-x-3 gap-y-3.5 w-full relative">
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