interface DirectoryFilePagerProps {
    currentPage: number;
    hasMore: boolean;
    loading: boolean;
    onPageChange: (page: number) => void;
}

/**
 * 当前目录的上一页/下一页.
 * 颜色和字号由外层与「当前页共 N 个文件」共用. 只有一页时不渲染.
 */
export function DirectoryFilePager({ currentPage, hasMore, loading, onPageChange }: DirectoryFilePagerProps) {
    if (currentPage <= 1 && !hasMore) return null;
    return (
        <nav aria-label="文件列表分页" className="flex items-center gap-3 text-sm text-[#86909c]" data-testid="portal-directory-pager">
            <button
                type="button"
                className="bg-transparent p-0 text-sm text-[#86909c] disabled:opacity-40"
                disabled={loading || currentPage <= 1}
                onClick={() => onPageChange(currentPage - 1)}
            >
                上一页
            </button>
            <span>第 {currentPage} 页</span>
            <button
                type="button"
                className="bg-transparent p-0 text-sm text-[#86909c] disabled:opacity-40"
                disabled={loading || !hasMore}
                onClick={() => onPageChange(currentPage + 1)}
            >
                下一页
            </button>
        </nav>
    );
}
