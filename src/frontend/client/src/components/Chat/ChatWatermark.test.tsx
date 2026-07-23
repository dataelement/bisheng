import { readFileSync } from "fs";
import path from "path";

function readSource(relativePath: string): string {
    return readFileSync(path.resolve(process.cwd(), relativePath), "utf8");
}

const watermarkSource = readSource(
    "src/pages/knowledge/FilePreview/KnowledgePreviewWatermark.tsx",
);
const watermarkStyles = readSource(
    "src/pages/knowledge/FilePreview/KnowledgePreviewWatermark.module.css",
);
const aiChatMessagesSource = readSource("src/components/Chat/AiChatMessages.tsx");
const mainChatSource = readSource("src/components/Chat/ChatView.tsx");
const appChatSource = readSource("src/pages/appChat/ChatView.tsx");
const knowledgePanelSource = readSource(
    "src/pages/knowledge/SpaceDetail/AiChat/KnowledgeAiPanel.tsx",
);
const assistantPanelSource = readSource(
    "src/pages/Subscription/AiChat/AiAssistantPanel.tsx",
);
const shareViewSource = readSource("src/components/Share/ShareView.tsx");

describe("authenticated chat watermark wiring", () => {
    test("provides a default-off reusable surface and one opacity source", () => {
        expect(watermarkSource).toMatch(/export function CurrentUserWatermarkSurface/);
        expect(watermarkSource).toMatch(/enabled\s*=\s*false/);
        expect(watermarkSource).toContain("data-chat-watermark-surface");
        expect(watermarkSource).toContain("fillOpacity={layout.opacity}");
        expect(watermarkStyles).not.toMatch(/fill-opacity/);
        expect(watermarkStyles).toMatch(/pointer-events:\s*none/);
    });

    test("AiChatMessages covers empty, loading and message bodies but remains opt-in", () => {
        expect(aiChatMessagesSource).toMatch(/watermarkEnabled\?:\s*boolean/);
        expect(aiChatMessagesSource).toMatch(/watermarkEnabled\s*=\s*false/);
        expect(
            aiChatMessagesSource.match(/<CurrentUserWatermarkSurface/g)?.length ?? 0,
        ).toBeGreaterThanOrEqual(3);

        const headerStart = aiChatMessagesSource.indexOf("<HeaderTitle");
        const messageWatermarkStart = aiChatMessagesSource.indexOf(
            "<CurrentUserWatermarkSurface",
            headerStart,
        );
        expect(headerStart).toBeGreaterThanOrEqual(0);
        expect(messageWatermarkStart).toBeGreaterThan(headerStart);
    });

    test("main and app chat enable only authenticated non-share conversation surfaces", () => {
        expect(mainChatSource).toContain(
            "const watermarkEnabled = Boolean(user && !shareToken)",
        );
        expect(mainChatSource).toContain("watermarkEnabled={watermarkEnabled}");
        expect(mainChatSource).toMatch(
            /<CurrentUserWatermarkSurface[\s\S]*enabled=\{watermarkEnabled\}/,
        );
        expect(appChatSource).toMatch(
            /const watermarkEnabled = Boolean\(user && !isGuestMode && !readOnly\)/,
        );
        expect(
            appChatSource.match(/<CurrentUserWatermarkSurface/g)?.length ?? 0,
        ).toBeGreaterThanOrEqual(2);
    });

    test("knowledge and assistant panels opt in while share view stays unchanged", () => {
        expect(knowledgePanelSource).toContain("watermarkEnabled");
        expect(knowledgePanelSource).toContain("<CurrentUserWatermarkSurface");
        expect(assistantPanelSource).toContain("watermarkEnabled");
        expect(shareViewSource).not.toContain("watermarkEnabled");
        expect(shareViewSource).not.toContain("CurrentUserWatermarkSurface");
    });
});
