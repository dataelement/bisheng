import { render, screen, within } from "@testing-library/react";
import type { ChatMessage } from "~/api/chatApi";
import AiMessageBubble from "./AiMessageBubble";

jest.mock("~/hooks", () => ({
    useAuthContext: () => ({
        user: {
            username: "测试用户",
            avatar: "",
        },
    }),
}));

jest.mock("~/hooks/queries/data-provider", () => ({
    useGetBsConfig: () => ({
        data: {
            assistantIcon: {},
        },
    }),
}));

jest.mock("~/components/Chat/Messages/Content/Markdown", () => ({
    __esModule: true,
    default: ({ content }: { content: string }) => <span>{content}</span>,
}));

jest.mock("~/components/Chat/Messages/Content/CitationReferencesDrawer", () => ({
    __esModule: true,
    default: ({ actionButtons }: { actionButtons?: React.ReactNode }) => (
        <div data-testid="citation-actions">{actionButtons}</div>
    ),
}));

jest.mock("~/components/Voice/TextToSpeechButton", () => ({
    TextToSpeechButton: () => <button type="button">朗读</button>,
}));

jest.mock("~/components/Artifacts/Thinking", () => ({
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock("~/components/Chat/Messages/DeepThinkingGroup", () => ({
    __esModule: true,
    default: () => <div data-testid="deep-thinking" />,
}));

jest.mock("~/components/Chat/Messages/ToolCallDisplay", () => ({
    __esModule: true,
    default: () => <div data-testid="tool-call" />,
}));

jest.mock("~/components/Chat/Messages/Content/SearchWebUrls", () => ({
    __esModule: true,
    default: () => <div data-testid="search-web-urls" />,
}));

function makeMessage(overrides: Partial<ChatMessage>): ChatMessage {
    return {
        messageId: "message-1",
        parentMessageId: "parent-1",
        conversationId: "conversation-1",
        sender: "assistant",
        text: "",
        isCreatedByUser: false,
        ...overrides,
    };
}

describe("AiMessageBubble portal drawer layout", () => {
    test("shows an AI avatar before assistant answers in the portal drawer", () => {
        render(
            <AiMessageBubble
                {...({
                    message: makeMessage({
                        messageId: "assistant-1",
                        sender: "assistant",
                        text: "你好，我是首钢知库智能助手",
                        isCreatedByUser: false,
                    }),
                    portalDrawerLayout: true,
                } as any)}
            />,
        );

        const row = screen.getByTestId("portal-ai-assistant-message");
        expect(within(row).getByLabelText("AI头像")).toBeInTheDocument();
        expect(within(row).getByTestId("portal-ai-assistant-bubble")).toHaveTextContent(
            "你好，我是首钢知库智能助手",
        );
    });

    test("shows a user avatar after user questions in the portal drawer", () => {
        render(
            <AiMessageBubble
                {...({
                    message: makeMessage({
                        messageId: "user-1",
                        sender: "user",
                        text: "振动纹通常如何排查？",
                        isCreatedByUser: true,
                    }),
                    portalDrawerLayout: true,
                } as any)}
            />,
        );

        const row = screen.getByTestId("portal-ai-user-message");
        expect(within(row).getByTestId("portal-ai-user-bubble")).toHaveTextContent(
            "振动纹通常如何排查？",
        );
        expect(within(row).getByLabelText("用户头像")).toBeInTheDocument();
    });
});
