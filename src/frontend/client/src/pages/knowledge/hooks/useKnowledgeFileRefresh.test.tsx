import { act, renderHook } from "@testing-library/react";
import { dispatchKnowledgeSpaceFilesRefresh, KNOWLEDGE_SPACE_FILES_REFRESH_EVENT } from "../knowledgeFileRefresh";
import { useKnowledgeFileRefresh } from "./useKnowledgeFileRefresh";

describe("知识库刷新通知", () => {
    afterEach(() => jest.useRealTimers());

    test("按空间过滤，全局审批通知刷新当前视图，使用最新回调", async () => {
        const oldRefresh = jest.fn();
        const refresh = jest.fn();
        const { rerender, unmount } = renderHook(({ callback }) => useKnowledgeFileRefresh("10", callback), {
            initialProps: { callback: oldRefresh },
        });
        rerender({ callback: refresh });
        await act(async () => { dispatchKnowledgeSpaceFilesRefresh(20); });
        expect(refresh).not.toHaveBeenCalled();
        await act(async () => { dispatchKnowledgeSpaceFilesRefresh(10); });
        await act(async () => { dispatchKnowledgeSpaceFilesRefresh(); });
        expect(refresh).toHaveBeenCalledTimes(2);
        expect(oldRefresh).not.toHaveBeenCalled();
        unmount();
        await act(async () => { dispatchKnowledgeSpaceFilesRefresh(10); });
        expect(refresh).toHaveBeenCalledTimes(2);
    });

    test("审批期间同步，结束后停止轮询，重新聚焦可更新", async () => {
        jest.useFakeTimers();
        const refresh = jest.fn();
        const { rerender } = renderHook(({ pending }) => useKnowledgeFileRefresh("10", refresh, pending), {
            initialProps: { pending: true },
        });
        await act(async () => { jest.advanceTimersByTime(5000); });
        expect(refresh).toHaveBeenCalledTimes(1);
        rerender({ pending: false });
        await act(async () => { jest.advanceTimersByTime(10000); });
        expect(refresh).toHaveBeenCalledTimes(1);
        await act(async () => { window.dispatchEvent(new Event("focus")); });
        expect(refresh).toHaveBeenCalledTimes(2);
    });

    test("刷新进行中收到新变更，完成后再同步一次，失败后可重试", async () => {
        let finish!: () => void;
        const refresh = jest.fn().mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
        renderHook(() => useKnowledgeFileRefresh("10", refresh));
        await act(async () => {
            dispatchKnowledgeSpaceFilesRefresh(10);
            dispatchKnowledgeSpaceFilesRefresh(10);
        });
        expect(refresh).toHaveBeenCalledTimes(1);
        await act(async () => { finish(); });
        expect(refresh).toHaveBeenCalledTimes(2);
        refresh.mockRejectedValueOnce(new Error("offline"));
        await act(async () => { dispatchKnowledgeSpaceFilesRefresh(10); });
        await act(async () => { dispatchKnowledgeSpaceFilesRefresh(10); });
        expect(refresh).toHaveBeenCalledTimes(4);
    });

    test("独立弹窗通知可达，发送方不会重复刷新，卸载释放通道", async () => {
        const channels: FakeChannel[] = [];
        class FakeChannel {
            name: string;
            onmessage?: (event: { data: unknown }) => void;
            closed = false;
            constructor(name: string) { this.name = name; channels.push(this); }
            postMessage(data: unknown) {
                channels.filter((channel) => channel !== this && !channel.closed && channel.name === this.name)
                    .forEach((channel) => channel.onmessage?.({ data }));
            }
            close() { this.closed = true; }
        }
        const previous = globalThis.BroadcastChannel;
        globalThis.BroadcastChannel = FakeChannel as any;
        try {
            const refresh = jest.fn();
            const { unmount } = renderHook(() => useKnowledgeFileRefresh("10", refresh));
            await act(async () => { dispatchKnowledgeSpaceFilesRefresh(10); });
            expect(refresh).toHaveBeenCalledTimes(1);
            const remote = new FakeChannel(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT);
            await act(async () => { remote.postMessage({ senderId: "approval-dialog", spaceId: 10 }); });
            expect(refresh).toHaveBeenCalledTimes(2);
            unmount();
            expect(channels[0].closed).toBe(true);
            remote.close();
        } finally {
            globalThis.BroadcastChannel = previous;
        }
    });
});
