export type PortalFilePageQuery = {
    spaceId: string;
    parentId?: string;
    mode: "browse" | "search";
    pageSize: number;
    keyword?: string;
    tagIds?: number[];
    status?: number[];
    orderField?: string;
    orderSort?: string;
};

export type PortalFilePageResult<T> = {
    data: T[];
    hasMore: boolean;
    nextCursor: string | null;
    total?: number;
    canReorderFolders?: boolean;
};

type PageRecord<T> = Omit<PortalFilePageResult<T>, "data"> & {
    data?: T[];
    cursor: string | null;
    fetchedAt: number;
    signature: string;
};

type ViewHistory<T> = { query: PortalFilePageQuery; page: number; pages: Map<number, PageRecord<T>> };
export type PortalFilePageSnapshot<T> = PortalFilePageResult<T> & {
    query?: PortalFilePageQuery;
    key: string;
    page: number;
    maxVisitedPage: number;
    loading: boolean;
    error?: unknown;
    resetReason?: "cursor" | "changed";
};
export type PortalFilePageLoader<T> = (
    query: PortalFilePageQuery, page: number, cursor: string | null,
) => Promise<PortalFilePageResult<T>>;
export const PORTAL_FILE_PAGE_TTL = 30_000;

export function portalFileQueryKey(query: PortalFilePageQuery): string {
    return JSON.stringify([
        query.spaceId, query.parentId || "", query.mode, query.pageSize,
        (query.keyword || "").trim(), [...new Set(query.tagIds || [])].sort((a, b) => a - b),
        [...new Set(query.status || [])].sort((a, b) => a - b),
        query.orderField || "file_type", query.orderSort || "asc",
    ]);
}

const emptySnapshot = <T,>(): PortalFilePageSnapshot<T> => ({
    key: "", data: [], page: 1, maxVisitedPage: 0, hasMore: false, nextCursor: null, loading: false,
});
const errorCode = (error: unknown) => {
    const value = error as { statusCode?: number; status_code?: number; response?: { status?: number; data?: { status_code?: number } } };
    return Number(value?.statusCode ?? value?.status_code ?? value?.response?.data?.status_code ?? value?.response?.status);
};

export function createPortalFilePageHistory<T extends { id: string; updatedAt?: string }>(options: {
    now?: () => number; maxViews?: number; maxRowPages?: number;
} = {}) {
    const now = options.now || Date.now;
    const maxViews = options.maxViews ?? 20;
    const maxRowPages = options.maxRowPages ?? 10;
    const views = new Map<string, ViewHistory<T>>();
    const listeners = new Set<() => void>();
    let serial = 0;
    let snapshot = emptySnapshot<T>();
    const publish = (next: PortalFilePageSnapshot<T>) => {
        snapshot = next;
        listeners.forEach(listener => listener());
    };
    const isFresh = (record?: PageRecord<T>) => Boolean(record?.data && now() - record.fetchedAt < PORTAL_FILE_PAGE_TTL);
    const describe = (key: string, view: ViewHistory<T>, page: number, record: PageRecord<T>): PortalFilePageSnapshot<T> => ({
        ...record, data: record.data || [], query: view.query, key, page,
        maxVisitedPage: Math.max(...view.pages.keys()), loading: false,
    });
    const signature = (result: PortalFilePageResult<T>) => JSON.stringify([
        result.data.map(row => row.id), result.nextCursor, result.hasMore, result.total,
    ]);
    const invalidate = (spaceId?: string) => {
        serial += 1;
        for (const [key, view] of views) {
            if (!spaceId || view.query.spaceId === spaceId) views.delete(key);
        }
        if (!spaceId || snapshot.query?.spaceId === spaceId) publish(emptySnapshot<T>());
    };
    const load = async (
        query: PortalFilePageQuery, loader: PortalFilePageLoader<T>, requestedPage?: number, force = false,
    ): Promise<PortalFilePageSnapshot<T> | null> => {
        const key = portalFileQueryKey(query);
        let view = views.get(key);
        if (!view) view = { query, page: 1, pages: new Map() };
        const page = requestedPage ?? view.page;
        const record = view.pages.get(page);
        const maxVisited = view.pages.size ? Math.max(...view.pages.keys()) : 0;
        const previous = view.pages.get(page - 1);
        if (!Number.isInteger(page) || page < 1 || (!record && page !== maxVisited + 1)
            || (!record && page > 1 && (!previous?.hasMore || (query.mode === "browse" && !previous.nextCursor)))) return null;
        const requestSerial = ++serial;
        const prior = snapshot;
        if (!force && isFresh(record)) {
            views.delete(key);
            views.set(key, view);
            view.page = page;
            const next = describe(key, view, page, record!);
            publish(next);
            return next;
        }
        const priorRecord = prior.key === key ? view.pages.get(prior.page) : undefined;
        publish({
            ...(prior.key === key ? prior : emptySnapshot<T>()), query, key, loading: true, error: undefined,
            data: isFresh(priorRecord) ? prior.data : [], resetReason: undefined,
        });
        const cursor = record?.cursor ?? previous?.nextCursor ?? null;
        try {
            const result = await loader(query, page, cursor);
            if (serial !== requestSerial) return null;
            if (record && record.signature !== signature(result)) {
                views.delete(key);
                if (page !== 1) {
                    const restored = await load(query, loader, 1, true);
                    if (restored) publish({ ...restored, resetReason: "changed" });
                    return restored ? snapshot : null;
                }
                view = { query, page: 1, pages: new Map() };
            }
            const saved: PageRecord<T> = { ...result, cursor: page === 1 ? null : cursor, fetchedAt: now(), signature: signature(result) };
            // 页访问顺序只影响行数据淘汰，入口游标仍随上下文保留。
            view.pages.delete(page);
            view.pages.set(page, saved);
            view.page = page;
            const rowPages = [...view.pages.values()].filter(item => item.data !== undefined);
            rowPages.slice(0, Math.max(0, rowPages.length - maxRowPages)).forEach(item => { item.data = undefined; });
            views.delete(key);
            views.set(key, view);
            while (views.size > maxViews) views.delete(views.keys().next().value!);
            const next = describe(key, view, page, saved);
            publish(next);
            return next;
        } catch (error) {
            if (serial !== requestSerial) return null;
            const code = errorCode(error);
            if ([18070, 10991].includes(code) && (page !== 1 || cursor)) {
                views.delete(key);
                const restored = await load(query, loader, 1, true);
                if (restored) publish({ ...restored, resetReason: "cursor" });
                return restored ? snapshot : null;
            }
            if ([401, 403, 18040, 18000].includes(code)) {
                invalidate(query.spaceId);
                publish({ ...emptySnapshot<T>(), query, key, error });
            } else {
                publish({
                    ...(prior.key === key ? prior : emptySnapshot<T>()), query, key,
                    data: isFresh(priorRecord) ? prior.data : [], loading: false, error,
                });
            }
            throw error;
        }
    };
    return {
        load, invalidate,
        getSnapshot: () => snapshot,
        subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
        cancel: () => { serial += 1; },
        restorePage: (query: PortalFilePageQuery) => views.get(portalFileQueryKey(query))?.page ?? 1,
        expire: (spaceId: string, keepCurrent = false) => {
            for (const view of views.values()) {
                if (view.query.spaceId === spaceId) for (const [page, record] of view.pages) {
                    if (!keepCurrent || portalFileQueryKey(view.query) !== snapshot.key || page !== snapshot.page) record.fetchedAt = -Infinity;
                }
            }
        },
        patch: (spaceId: string, updater: (row: T) => T, queryKey?: string) => {
            for (const view of views.values()) {
                if (view.query.spaceId === spaceId && (!queryKey || portalFileQueryKey(view.query) === queryKey)) for (const record of view.pages.values()) {
                    if (record.data) record.data = record.data.map(updater);
                }
            }
            if (snapshot.query?.spaceId === spaceId && (!queryKey || snapshot.key === queryKey)) {
                const record = views.get(snapshot.key)?.pages.get(snapshot.page);
                publish({ ...snapshot, data: record?.data || snapshot.data.map(updater) });
            }
        },
        updateCurrent: (updater: (rows: T[]) => T[]) => {
            const record = views.get(snapshot.key)?.pages.get(snapshot.page);
            if (!record) return;
            const data = updater(snapshot.data);
            record.data = data;
            publish({ ...snapshot, data });
        },
    };
}
