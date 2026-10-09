import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { KnowledgeFile } from "~/api/knowledge";
import { createPortalFilePageHistory } from "./portalFilePageHistory";

export function usePortalFilePageHistory(identity: string) {
    const history = useMemo(() => createPortalFilePageHistory<KnowledgeFile>(), [identity]);
    const snapshot = useSyncExternalStore(history.subscribe, history.getSnapshot, history.getSnapshot);
    useEffect(() => () => history.invalidate(), [history]);
    return { history, snapshot };
}

export async function loadPortalFilePage(query: import("./portalFilePageHistory").PortalFilePageQuery, page: number, cursor: string | null) {
    const { getSpaceChildrenApi, searchSpaceChildrenApi } = await import("~/api/knowledge");
    const params = {
        space_id: query.spaceId, parent_id: query.parentId, page_size: query.pageSize, strictErrors: true,
        order_field: query.orderField, order_sort: query.orderSort, file_status: query.status,
    };
    if (query.mode === "search") {
        const result = await searchSpaceChildrenApi({ ...params, page, keyword: query.keyword, tag_ids: query.tagIds });
        return { data: result.data, total: result.total, hasMore: page * query.pageSize < result.total, nextCursor: null };
    }
    const result = await getSpaceChildrenApi({ ...params, cursor });
    return { data: result.data, hasMore: result.has_more, nextCursor: result.next_cursor, canReorderFolders: result.can_reorder_folders };
}
