import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function readSource(path: string): string {
    return readFileSync(resolve(process.cwd(), path), "utf8");
}

describe("stream retry wiring", () => {
    test("both SSE clients expose structured retry and error callbacks", () => {
        for (const path of [
            "src/hooks/useStreamChatSSE.ts",
            "src/hooks/useAiChatSSE.ts",
        ]) {
            const source = readSource(path);
            expect(source).toMatch(/addEventListener\("retry"/);
            expect(source).toMatch(/parseStreamRetryEvent/);
            expect(source).toMatch(/formatStreamChatError/);
        }
    });

    test("all chat hooks update the failed response in place", () => {
        for (const path of [
            "src/hooks/useAiChat.ts",
            "src/hooks/useFileChat.ts",
            "src/hooks/useFolderChat.ts",
            "src/hooks/useChannelChat.ts",
        ]) {
            const source = readSource(path);
            expect(source).toMatch(/onRetry/);
            expect(source).toMatch(/failedResponse/);
            expect(source).toMatch(/requestPayload/);
            expect(source).toMatch(/failedResponse\?\.messageId \|\| v4\(\)/);
        }
    });

    test("workstation retry reuses the server question row", () => {
        const source = readSource("src/hooks/useAiChat.ts");
        expect(source).toMatch(/serverMessageId/);
        expect(source).toMatch(/overrideParentMessageId/);
    });

    test("assistant error bubble preserves line breaks and exposes retry", () => {
        const source = readSource("src/components/Chat/AiMessageBubble.tsx");
        expect(source).toMatch(/whitespace-pre-line/);
        expect(source).toMatch(/message\.retrying/);
        expect(source).toMatch(/onClick=\{onRegenerate\}/);
    });
});
