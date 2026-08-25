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
