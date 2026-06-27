import { useCallback, useEffect, useState } from "react";
import {
    listPortalFavoritesApi,
    removePortalFavoriteApi,
    type KnowledgeSpace,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { toFavoriteRow, type FavoriteRowVM } from "../favoriteView";

interface PortalFavoritesPanelProps {
    space: KnowledgeSpace;
    /**
     * 打开有效收藏对应的源文件。第三个参数 fileName 为可选，
     * 仅用于让宿主在切换源空间后构造更友好的预览标题/类型。
     */
    onOpenSource: (sourceSpaceId: string, sourceFileId: string, fileName?: string) => void;
}

const FAVORITES_PAGE_SIZE = 50;

/**
 * "我的收藏"只读面板。
 *
 * 自给自足地加载收藏列表，渲染只读视图：仅支持查看（打开有效源文件）与取消收藏，
 * 不渲染任何上传/新建/删除/移动/标签/问答等写操作入口。失效项置灰且不可打开。
 */
export default function PortalFavoritesPanel({ space, onOpenSource }: PortalFavoritesPanelProps) {
    const { showToast } = useToastContext();
    const [rows, setRows] = useState<FavoriteRowVM[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(false);
    const [removingKey, setRemovingKey] = useState<string | null>(null);

    const loadFavorites = useCallback(async () => {
        setLoading(true);
        setError(false);
        try {
            const res = await listPortalFavoritesApi({ page: 1, pageSize: FAVORITES_PAGE_SIZE });
            setRows(res.data.map(toFavoriteRow));
        } catch {
            setError(true);
            setRows([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void loadFavorites();
        // space.id 变化时重新加载（理论上收藏库唯一，保留以防多实例切换）
    }, [loadFavorites, space.id]);

    const handleOpen = useCallback((row: FavoriteRowVM) => {
        if (!row.openable) return;
        onOpenSource(row.sourceSpaceId, row.sourceFileId, row.title);
    }, [onOpenSource]);

    const handleRemove = useCallback(async (row: FavoriteRowVM) => {
        if (removingKey) return;
        setRemovingKey(row.key);
        try {
            await removePortalFavoriteApi({
                sourceSpaceId: row.sourceSpaceId,
                sourceFileId: row.sourceFileId,
            });
            setRows((prev) => prev.filter((item) => item.key !== row.key));
            showToast({ message: "已取消收藏", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "取消收藏失败，请稍后重试", severity: NotificationSeverity.ERROR });
        } finally {
            setRemovingKey(null);
        }
    }, [removingKey, showToast]);

    return (
        <main
            data-testid="portal-favorites-panel"
            className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white"
        >
            <div className="flex flex-shrink-0 flex-col gap-1 border-b border-[#e5e6eb] px-6 py-4">
                <h2 className="text-base font-medium text-text-primary">我的收藏</h2>
                <p className="text-xs text-text-secondary">
                    收藏内容为只读视图，仅可查看源文件或取消收藏。
                </p>
            </div>

            <div className="min-h-0 flex-1 overflow-auto px-6 py-4">
                {loading ? (
                    <div className="py-16 text-center text-sm text-text-secondary" data-testid="favorites-loading">
                        正在加载收藏...
                    </div>
                ) : error ? (
                    <div className="py-16 text-center text-sm text-text-secondary" data-testid="favorites-error">
                        <div>加载收藏失败。</div>
                        <button
                            type="button"
                            className="mt-2 text-primary hover:underline"
                            onClick={() => void loadFavorites()}
                        >
                            重新加载
                        </button>
                    </div>
                ) : rows.length === 0 ? (
                    <div className="py-16 text-center text-sm text-text-secondary" data-testid="favorites-empty">
                        暂无收藏文件。
                    </div>
                ) : (
                    <ul className="flex flex-col gap-1">
                        {rows.map((row) => (
                            <li
                                key={row.key}
                                data-testid="favorite-row"
                                data-invalid={row.invalid ? "true" : "false"}
                                className="flex items-center justify-between gap-3 rounded-md border border-[#e5e6eb] px-4 py-3"
                            >
                                <button
                                    type="button"
                                    disabled={!row.openable}
                                    onClick={() => handleOpen(row)}
                                    title={row.invalid ? "源文件已失效，无法打开" : row.title}
                                    className={
                                        row.openable
                                            ? "min-w-0 flex-1 truncate text-left text-sm text-text-primary hover:text-primary"
                                            : "min-w-0 flex-1 cursor-not-allowed truncate text-left text-sm text-text-secondary opacity-60"
                                    }
                                >
                                    <span className="truncate">{row.title}</span>
                                    {row.invalid ? (
                                        <span
                                            data-testid="favorite-invalid-tag"
                                            className="ml-2 inline-block rounded bg-[#f2f3f5] px-1.5 py-0.5 align-middle text-xs text-text-secondary"
                                        >
                                            已失效
                                        </span>
                                    ) : null}
                                </button>
                                <button
                                    type="button"
                                    data-testid="favorite-remove"
                                    disabled={removingKey === row.key}
                                    onClick={() => void handleRemove(row)}
                                    className="flex-shrink-0 text-sm text-text-secondary hover:text-red-500 disabled:opacity-50"
                                >
                                    取消收藏
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </main>
    );
}
