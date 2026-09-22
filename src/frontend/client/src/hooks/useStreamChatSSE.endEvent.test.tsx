/**
 * The closing event of a stream carries more than the text: the real persisted
 * message id, and — on the round that named the conversation — the generated
 * title. Both have to reach the caller, which is the only chance it gets to
 * update state that is otherwise loaded once on mount.
 */
import { renderHook } from "@testing-library/react";

type SseListener = (event: MessageEvent) => void;

const listeners: Record<string, SseListener> = {};

jest.mock("sse.js", () => ({
    SSE: jest.fn().mockImplementation(() => ({
        addEventListener: (name: string, handler: SseListener) => {
            listeners[name] = handler;
        },
        close: jest.fn(),
        stream: jest.fn(),
    })),
}));

import useStreamChatSSE from "./useStreamChatSSE";

function emit(data: Record<string, unknown>) {
    listeners.message({ data: JSON.stringify(data) } as MessageEvent);
}

function renderStream(onFinal: jest.Mock) {
    renderHook(() =>
        useStreamChatSSE({
            sseUrl: "http://localhost/sse",
            payload: {},
            onStart: jest.fn(),
            onMessage: jest.fn(),
            onFinal,
            onError: jest.fn(),
            onEnd: jest.fn(),
        })
    );
}

describe("stream closing event", () => {
    afterEach(() => {
        for (const key of Object.keys(listeners)) delete listeners[key];
    });

    it("hands the caller the generated conversation title", () => {
        const onFinal = jest.fn();
        renderStream(onFinal);

        emit({ type: "stream", message: { content: "hello" } });
        emit({
            type: "end",
            message: { content: "hello", message_id: 42, session_name: "Weather Tomorrow" },
        });

        expect(onFinal).toHaveBeenCalledWith("hello", 42, "Weather Tomorrow");
    });

    it("leaves the title undefined on rounds that did not name the conversation", () => {
        const onFinal = jest.fn();
        renderStream(onFinal);

        emit({ type: "stream", message: { content: "hello" } });
        emit({ type: "end", message: { content: "hello", message_id: 42 } });

        expect(onFinal).toHaveBeenCalledWith("hello", 42, undefined);
    });
});
