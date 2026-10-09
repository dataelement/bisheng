import { createPortalFilePageHistory, portalFileQueryKey, type PortalFilePageQuery } from "./portalFilePageHistory";

const query: PortalFilePageQuery = { spaceId: "1", mode: "browse", pageSize: 20 };
const payload = (id: string, hasMore = true) => ({
    data: [{ id, updatedAt: "2026-10-09" }], hasMore, nextCursor: hasMore ? `after-${id}` : null,
});
const deferred = <T,>() => {
    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};

it("访问新页、恢复旧页和过期旧页只使用其入口游标", async () => {
    let now = 1000;
    const history = createPortalFilePageHistory<{ id: string; updatedAt: string }>({ now: () => now });
    const load = jest.fn(async (_query, page: number, cursor: string | null) => {
        expect(cursor).toBe(page === 1 ? null : "after-one");
        return payload(page === 1 ? "one" : "two", page === 1);
    });
    await history.load(query, load);
    await history.load(query, load, 2);
    expect(history.getSnapshot()).toMatchObject({ page: 2, maxVisitedPage: 2, data: [{ id: "two" }], hasMore: false });
    await history.load(query, load, 1);
    expect(load).toHaveBeenCalledTimes(2);
    now += 31_000;
    await history.load(query, load, 2);
    expect(load).toHaveBeenCalledTimes(3);
    expect(history.getSnapshot().page).toBe(2);
});

it("失败不推进页码，未访问远页不能跳过查询，重试复用下一页游标", async () => {
    const history = createPortalFilePageHistory<{ id: string; updatedAt: string }>();
    const load = jest.fn().mockResolvedValueOnce(payload("one")).mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValueOnce(payload("two", false));
    await history.load(query, load);
    expect(await history.load(query, load, 5)).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
    await expect(history.load(query, load, 2)).rejects.toThrow("offline");
    expect(history.getSnapshot()).toMatchObject({ page: 1, maxVisitedPage: 1, data: [{ id: "one" }], loading: false });
    await history.load(query, load, 2);
    expect(load.mock.calls[2][2]).toBe("after-one");
});

it("不同查询恢复各自位置，迟到响应和失效后的响应不能写回", async () => {
    const history = createPortalFilePageHistory<{ id: string; updatedAt: string }>();
    const delayed = deferred<ReturnType<typeof payload>>();
    const oldLoad = history.load(query, () => delayed.promise);
    const folder = { ...query, parentId: "10" };
    await history.load(folder, async () => payload("folder", false));
    delayed.resolve(payload("old"));
    expect(await oldLoad).toBeNull();
    expect(history.getSnapshot().query?.parentId).toBe("10");
    const pending = deferred<ReturnType<typeof payload>>();
    const invalidated = history.load(query, () => pending.promise);
    history.invalidate("1");
    pending.resolve(payload("invalidated"));
    expect(await invalidated).toBeNull();
    expect(history.getSnapshot().data).toEqual([]);
});

it("缓存淘汰行时保留页游标，结构变化、权限拒绝与无效游标恢复不同", async () => {
    const history = createPortalFilePageHistory<{ id: string; updatedAt: string }>({ maxRowPages: 1 });
    const load = jest.fn(async (_query, page: number) => payload(String(page), page < 2));
    await history.load(query, load);
    await history.load(query, load, 2);
    await history.load(query, load, 1);
    expect(load).toHaveBeenCalledTimes(3);
    const changed = jest.fn().mockResolvedValueOnce(payload("changed"));
    await history.load(query, changed, 1, true);
    expect(history.getSnapshot()).toMatchObject({ page: 1, maxVisitedPage: 1 });
    const denied = Object.assign(new Error("denied"), { statusCode: 18040 });
    await expect(history.load(query, async () => { throw denied; }, 1, true)).rejects.toBe(denied);
    expect(history.getSnapshot().data).toEqual([]);
    await history.load(query, load);
    await history.load(query, load, 2);
    const invalidCursor = jest.fn().mockRejectedValueOnce({ statusCode: 18070 }).mockResolvedValueOnce(payload("reset"));
    await history.load(query, invalidCursor, 2, true);
    expect(invalidCursor.mock.calls.map(call => call[1])).toEqual([2, 1]);
    expect(history.getSnapshot()).toMatchObject({ page: 1, maxVisitedPage: 1, resetReason: "cursor" });
});

it("搜索按 page 翻页，patch 不延长 TTL，查询归一化且上下文有界", async () => {
    let now = 0;
    const history = createPortalFilePageHistory<{ id: string; updatedAt: string }>({ now: () => now, maxViews: 1 });
    const search = { ...query, mode: "search" as const, keyword: " 查找 ", tagIds: [2, 1] };
    expect(portalFileQueryKey(search)).toBe(portalFileQueryKey({ ...search, keyword: "查找", tagIds: [1, 2] }));
    const load = jest.fn(async (_q, page: number) => ({ ...payload(`s${page}`, page < 2), total: 21 }));
    await history.load(search, load);
    await history.load(search, load, 2);
    history.patch("1", row => ({ ...row, updatedAt: "patched" }));
    expect(history.getSnapshot().data[0].updatedAt).toBe("patched");
    now = 31_000;
    await history.load(search, load, 2);
    expect(load).toHaveBeenCalledTimes(3);
    await history.load(query, async () => payload("root"));
    await history.load(search, load);
    expect(load.mock.calls[3][1]).toBe(1);
});
