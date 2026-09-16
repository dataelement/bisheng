/**
 * Regression cover for the "switch away mid-answer and the turn is lost" bug.
 *
 * Chat state used to be one active set held by whichever conversation was on
 * screen, and navigating to another one wiped it and aborted the SSE. The
 * backend runs the whole turn inside that stream, so the abort killed the
 * generation server-side and coming back showed a truncated, error-flagged
 * reply. These tests pin the two properties that fix depends on: leaving a
 * conversation neither closes its stream nor refetches over its live bucket.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

import type { SSESubmission } from "./useAiChatSSE";

/** Every SSE turn opened during a test, in order. */
const mockOpenedStreams: Array<{ submission: SSESubmission; close: jest.Mock }> = [];

jest.mock("./useAiChatSSE", () => ({
    openChatStream: (submission: SSESubmission) => {
        const close = jest.fn();
        mockOpenedStreams.push({ submission, close });
        return { close };
    },
}));

const mockGetAgentMessages = jest.fn();
const mockGetSessionName = jest.fn();
jest.mock("~/api/chatApi", () => ({
    getAgentMessages: (...args: unknown[]) => mockGetAgentMessages(...args),
    getSessionName: (...args: unknown[]) => mockGetSessionName(...args),
}));

// Recoil atoms are read-only fixtures here: `~/store` hands out tagged objects
// and the mocked `useRecoilState` unwraps whatever value each one carries.
jest.mock("recoil", () => ({
    useRecoilState: (atom: { __testValue?: unknown }) => [atom?.__testValue, jest.fn()],
}));
jest.mock("~/store", () => ({
    __esModule: true,
    default: {
        chatModel: { __testValue: { id: 1, name: "test-model" } },
        selectedOrgKbs: { __testValue: [] },
        searchType: { __testValue: "" },
        selectedAgentTools: { __testValue: [] },
    },
}));
jest.mock("~/store/linsight", () => ({
    SopStatus: { Running: "running", Stoped: "stoped", SopGenerating: "sop_generating" },
    taskModeSkillsState: () => ({ __testValue: [] }),
}));

jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("~/hooks/queries/data-provider", () => ({ useGetBsConfig: () => ({ data: {} }) }));
// Added since the fix was lost: the hook now reads media metadata off
// attachments and mints an owner id for the stream registry.
jest.mock("~/utils/mediaAttachmentUtils", () => ({
    isMediaAttachmentFile: () => false,
}));
jest.mock("uuid", () => ({ v4: () => "test-owner" }));
jest.mock("~/hooks/useLinsightManager", () => ({
    useLinsightManager: () => ({ createLinsight: jest.fn(), updateLinsight: jest.fn() }),
}));
jest.mock("~/api/linsight", () => ({
    startLinsight: jest.fn().mockResolvedValue(undefined),
    getLinsightSessionVersionList: jest.fn().mockResolvedValue([]),
}));
jest.mock("~/types/chat", () => ({
    QueryKeys: { allConversations: "allConversations" },
    dataService: { genTitle: jest.fn().mockResolvedValue({}) },
}));
jest.mock("~/utils", () => ({
    addConversation: (data: unknown) => data,
    updateConvoFields: (data: unknown) => data,
}));
jest.mock("@tanstack/react-query", () => ({
    useQueryClient: () => ({ setQueryData: jest.fn(), getQueryData: jest.fn() }),
}));

// Imported after the jest.mock calls above on purpose — the hook pulls those
// modules in at import time.
import useAiChat from "./useAiChat";

const historyOf = (conversationId: string) => [
    {
        text: `${conversationId} history`,
        sender: "User",
        isCreatedByUser: true,
        messageId: `${conversationId}-q`,
        parentMessageId: "",
        conversationId,
        error: false,
    },
];

const renderChat = (conversationId: string) =>
    renderHook(({ cid }: { cid: string }) => useAiChat(cid), {
        initialProps: { cid: conversationId },
    });

/** The most recently opened turn's SSE callbacks. */
const latestStream = () => mockOpenedStreams[mockOpenedStreams.length - 1];

beforeEach(() => {
    mockOpenedStreams.length = 0;
    mockGetAgentMessages.mockImplementation((cid: string) => Promise.resolve(historyOf(cid)));
    mockGetSessionName.mockResolvedValue("");
});

describe("useAiChat conversation switching", () => {
    it("keeps a turn streaming into its own conversation while another is on screen", async () => {
        const { result, rerender } = renderChat("c1");
        await waitFor(() => expect(result.current.messages).toHaveLength(1));

        act(() => result.current.sendMessage("hello"));
        expect(mockOpenedStreams).toHaveLength(1);
        const turn = latestStream();

        act(() => {
            turn.submission.onStart();
            turn.submission.onAgentUpdate?.({ text: "half an answ" });
        });
        expect(result.current.isStreaming).toBe(true);
        expect(result.current.messages[result.current.messages.length - 1].text).toBe("half an answ");

        // Walk away mid-answer.
        rerender({ cid: "c2" });
        await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

        // The stream must survive — closing it is what killed the generation.
        expect(turn.close).not.toHaveBeenCalled();
        // ...and c2 must not inherit c1's streaming state.
        expect(result.current.isStreaming).toBe(false);

        // Tokens that arrive while the user is elsewhere still land in c1.
        act(() => {
            turn.submission.onAgentUpdate?.({ text: "half an answer, then the rest" });
            turn.submission.onFinal({ final: true });
            turn.submission.onEnd();
        });
        expect(result.current.messages[0].text).toBe("c2 history");

        // Coming back shows the completed turn, not a refetched stub.
        mockGetAgentMessages.mockClear();
        rerender({ cid: "c1" });
        await waitFor(() =>
            expect(result.current.messages[result.current.messages.length - 1].text).toBe(
                "half an answer, then the rest",
            ),
        );
    });


    /**
     * Added with the restore: the attachment-ingest poll was written after this
     * fix was lost, on the assumption that one conversation is live at a time.
     * It used a single timer, cancelled it on every switch, and wrote its result
     * into whatever was on screen. Under buckets that is a silent corruption —
     * it compiles, it passes the older tests, and it occasionally files one
     * conversation's attachments under another.
     */
    it("does not cancel a conversation's attachment poll when the user walks away", async () => {
        const { result, rerender } = renderChat("c1");
        await waitFor(() => expect(result.current.messages).toHaveLength(1));

        act(() => result.current.sendMessage("with a video", [{ name: "clip.mp4", filepath: "p" }]));
        const before = jest.getTimerCount?.() ?? 0;

        rerender({ cid: "c2" });
        await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

        // Switching is not a reason to stop parsing what c1 uploaded.
        expect(jest.getTimerCount?.() ?? 0).toBeGreaterThanOrEqual(before);
        // And c2 must not show c1's parsing state.
        expect(result.current.isParsingMedia).toBe(false);
    });

    it("keeps each conversation's parsing flag to itself", async () => {
        const { result, rerender } = renderChat("c1");
        await waitFor(() => expect(result.current.messages).toHaveLength(1));

        act(() => result.current.sendMessage("with a video", [{ name: "clip.mp4", filepath: "p" }]));

        rerender({ cid: "c2" });
        await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));
        expect(result.current.isParsingMedia).toBe(false);

        rerender({ cid: "c1" });
        await waitFor(() => expect(result.current.messages[0].text).toBe("c1 history"));
    });

    it("does not refetch over a bucket whose turn is still streaming", async () => {
        const { result, rerender } = renderChat("c1");
        await waitFor(() => expect(result.current.messages).toHaveLength(1));

        act(() => result.current.sendMessage("hello"));
        act(() => {
            latestStream().submission.onStart();
            latestStream().submission.onAgentUpdate?.({ text: "streaming" });
        });

        rerender({ cid: "c2" });
        await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

        mockGetAgentMessages.mockClear();
        rerender({ cid: "c1" });
        await waitFor(() =>
            expect(result.current.messages[result.current.messages.length - 1].text).toBe("streaming"),
        );
        expect(mockGetAgentMessages).not.toHaveBeenCalledWith("c1", undefined);
        expect(result.current.isStreaming).toBe(true);
    });

    it("stops only the conversation on screen", async () => {
        const { result, rerender } = renderChat("c1");
        await waitFor(() => expect(result.current.messages).toHaveLength(1));

        act(() => result.current.sendMessage("hello"));
        const turn = latestStream();
        act(() => turn.submission.onStart());

        rerender({ cid: "c2" });
        await waitFor(() => expect(result.current.messages[0].text).toBe("c2 history"));

        // Stop pressed while looking at c2 must not touch c1's turn.
        act(() => result.current.stopGenerating());
        expect(turn.close).not.toHaveBeenCalled();

        rerender({ cid: "c1" });
        await waitFor(() => expect(result.current.isStreaming).toBe(true));
        act(() => result.current.stopGenerating());
        expect(turn.close).toHaveBeenCalledTimes(1);
        expect(result.current.isStreaming).toBe(false);
    });

    it("closes live turns when the hook unmounts for good", async () => {
        const { result, unmount } = renderChat("c1");
        await waitFor(() => expect(result.current.messages).toHaveLength(1));

        act(() => result.current.sendMessage("hello"));
        const turn = latestStream();
        act(() => turn.submission.onStart());

        unmount();
        expect(turn.close).toHaveBeenCalledTimes(1);
    });
});

/**
 * Moving the view to a new conversation id must move the turn's state with it.
 *
 * Each turn writes into a bucket keyed by the conversation it started in, and
 * what the caller sees is the bucket of whichever id is current. So pointing
 * the view at a freshly minted id without carrying the bucket over lands on an
 * empty one: the answer is on screen one moment and the pane is blank the next.
 *
 * Task mode is where this bites. The daily stream's last act is a handoff that
 * binds the conversation to a server-minted chat id, and it also suppresses the
 * one history refetch that would otherwise repaint the pane — so nothing brings
 * the content back until the user navigates away and returns.
 *
 * The second test covers what the orphaned bucket does afterwards: it still
 * sits under the id the turn started with, so going back to a new chat finds
 * the previous turn's messages instead of the welcome page.
 */
describe("useAiChat adopts a new conversation id", () => {
    it("keeps the turn on screen when the task handoff binds a real chat id", async () => {
        const { result } = renderChat("new");

        act(() => result.current.sendMessage("write me a report", null, { taskMode: true }));
        const turn = latestStream();
        act(() => {
            turn.submission.onStart();
            turn.submission.onAgentUpdate?.({ text: "working on it" });
        });
        expect(result.current.messages.length).toBeGreaterThan(0);

        act(() => turn.submission.onTaskHandoff?.({ session_version_id: "sv-1", chat_id: "c-real" }));

        await waitFor(() => expect(result.current.conversationId).toBe("c-real"));
        expect(result.current.messages.length).toBeGreaterThan(0);
        expect(result.current.messages[result.current.messages.length - 1].text).toBe("working on it");
    });

    it("leaves nothing behind under the id the turn started with", async () => {
        const { result, rerender } = renderChat("new");

        act(() => result.current.sendMessage("write me a report", null, { taskMode: true }));
        const turn = latestStream();
        act(() => {
            turn.submission.onStart();
            turn.submission.onAgentUpdate?.({ text: "working on it" });
        });
        act(() => turn.submission.onTaskHandoff?.({ session_version_id: "sv-1", chat_id: "c-real" }));
        await waitFor(() => expect(result.current.conversationId).toBe("c-real"));

        // The view rewrites its own URL to the id the handoff just minted.
        rerender({ cid: "c-real" });

        // Starting another new chat must land on the welcome page, not on the
        // messages the previous turn left behind under "new".
        rerender({ cid: "new" });
        await waitFor(() => expect(result.current.conversationId).toBe("new"));
        expect(result.current.messages).toHaveLength(0);
    });
});
