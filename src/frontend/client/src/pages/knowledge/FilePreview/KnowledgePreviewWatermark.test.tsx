import { act, render, type ReactElement } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "fs";
import path from "path";
import { RecoilRoot } from "recoil";

import store from "~/store";
import KnowledgePreviewWatermark, {
    CurrentUserWatermarkSurface,
    KnowledgePreviewWatermarkProvider,
    buildKnowledgePreviewWatermarkLines,
    calculateKnowledgePreviewWatermarkLayout,
    calculateKnowledgePreviewWatermarkPositions,
    formatKnowledgePreviewWatermarkTime,
} from "./KnowledgePreviewWatermark";

const currentUser = {
    id: "7",
    username: "zhangsan",
    email: "zhangsan@example.com",
    name: "张三",
    avatar: "",
    role: "member",
    departmentName: "设备管理部",
    externalId: "SG001",
    provider: "local",
    createdAt: "",
    updatedAt: "",
};

let emitResize: (width: number, height: number) => void = () => {};

function createQueryClient() {
    return new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });
}

function renderWithProviders(ui: ReactElement, user?: typeof currentUser | null) {
    const queryClient = createQueryClient();
    return render(
        <QueryClientProvider client={queryClient}>
            <RecoilRoot initializeState={user ? ({ set }) => set(store.user, user) : undefined}>
                {ui}
            </RecoilRoot>
        </QueryClientProvider>,
    );
}

function renderWatermark(user = currentUser) {
    return renderWithProviders(
        <KnowledgePreviewWatermarkProvider>
            <div className="relative">
                <KnowledgePreviewWatermark />
            </div>
        </KnowledgePreviewWatermarkProvider>,
        user,
    );
}

describe("KnowledgePreviewWatermark", () => {
    beforeEach(() => {
        jest.useFakeTimers();
        jest.setSystemTime(new Date("2026-07-21T04:05:06.000Z"));
        global.fetch = jest.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                data: { horizontal_text: "首钢股份内部资料，严禁外传，违者必究" },
            }),
        }) as jest.Mock;
        class MockResizeObserver {
            constructor(private readonly callback: ResizeObserverCallback) {
                emitResize = (width, height) => {
                    this.callback(
                        [{ contentRect: { width, height } } as ResizeObserverEntry],
                        this as unknown as ResizeObserver,
                    );
                };
            }

            observe() {
                emitResize(800, 640);
            }

            disconnect() {}

            unobserve() {}
        }
        Object.defineProperty(globalThis, "ResizeObserver", {
            configurable: true,
            writable: true,
            value: MockResizeObserver,
        });
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    test("uses the current Bisheng user and keeps the mount-time Beijing clock", async () => {
        expect(formatKnowledgePreviewWatermarkTime(new Date())).toBe("2026/07/21");
        expect(buildKnowledgePreviewWatermarkLines(currentUser, new Date())).toEqual([
            "设备管理部-张三-SG001-2026/07/21",
            "首钢股份内部资料，严禁外传，违者必究",
        ]);
        expect(buildKnowledgePreviewWatermarkLines(currentUser, new Date(), "自定义水印文案")).toEqual([
            "设备管理部-张三-SG001-2026/07/21",
            "自定义水印文案",
        ]);

        const { container, rerender } = renderWatermark();
        await act(async () => {
            await Promise.resolve();
        });
        expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
        expect(container.textContent).toContain("设备管理部-张三-SG001-2026/07/21");
        expect(container.textContent).toContain("2026/07/21");
        expect(container.textContent).toContain("首钢股份内部资料，严禁外传，违者必究");
        expect(container.textContent).not.toContain("首钢集团内部资料");

        jest.setSystemTime(new Date("2026-07-21T04:10:06.000Z"));
        rerender(
            <QueryClientProvider client={createQueryClient()}>
                <RecoilRoot initializeState={({ set }) => set(store.user, currentUser)}>
                    <KnowledgePreviewWatermarkProvider>
                        <div className="relative">
                            <KnowledgePreviewWatermark />
                        </div>
                    </KnowledgePreviewWatermarkProvider>
                </RecoilRoot>
            </QueryClientProvider>,
        );
        expect(container.textContent).toContain("2026/07/21");
        expect(container.textContent).not.toContain("12:10:06");
    });

    test("keeps the reusable chat surface off by default and renders it for a current user", async () => {
        const disabled = renderWithProviders(
            <CurrentUserWatermarkSurface>
                <span>问答正文</span>
            </CurrentUserWatermarkSurface>,
        );
        expect(disabled.container).toHaveTextContent("问答正文");
        expect(disabled.container.querySelector("[data-chat-watermark-surface]")).toBeNull();
        disabled.unmount();

        const anonymous = renderWithProviders(
            <CurrentUserWatermarkSurface enabled>
                <span>访客正文</span>
            </CurrentUserWatermarkSurface>,
            null,
        );
        expect(anonymous.container).toHaveTextContent("访客正文");
        expect(anonymous.container.querySelector("[data-chat-watermark-surface]")).toBeNull();
        anonymous.unmount();

        const enabled = renderWithProviders(
            <CurrentUserWatermarkSurface enabled>
                <span>问答正文</span>
            </CurrentUserWatermarkSurface>,
        );
        await act(async () => {
            await Promise.resolve();
        });
        expect(enabled.container.querySelector("[data-chat-watermark-surface]")).toBeInTheDocument();
        expect(enabled.container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
        expect(enabled.container.textContent).toContain("设备管理部-张三-SG001-2026/07/21");
    });

    test("falls back to username/account and clips overlays to document surfaces", () => {
        expect(buildKnowledgePreviewWatermarkLines(
            { ...currentUser, name: "", username: "lisi", departmentName: "", externalId: "" },
            new Date(),
        )[0]).toBe("lisi-lisi-2026/07/21");

        const compactLayout = calculateKnowledgePreviewWatermarkLayout([100, 90]);
        const normalLayout = calculateKnowledgePreviewWatermarkLayout([240, 220]);
        const longLayout = calculateKnowledgePreviewWatermarkLayout([760, 320]);
        expect(compactLayout.cellWidth).toBe(240);
        expect(compactLayout.cellHeight).toBe(180);
        expect(normalLayout.rotation).toBe(-35);
        expect(normalLayout.fontSize).toBe(16);
        expect(normalLayout.opacity).toBe(0.31);
        expect(normalLayout.cellWidth).toBeGreaterThan(compactLayout.cellWidth);
        expect(normalLayout.cellHeight).toBeGreaterThan(compactLayout.cellHeight);
        expect(longLayout.cellWidth).toBeGreaterThan(normalLayout.cellWidth);
        expect(longLayout.cellHeight).toBeGreaterThan(normalLayout.cellHeight);
        expect(longLayout.cellWidth).toBeGreaterThanOrEqual(Math.ceil(longLayout.rotatedWidth + 48));
        expect(longLayout.cellHeight).toBeGreaterThanOrEqual(Math.ceil(longLayout.rotatedHeight + 36));

        const positions = calculateKnowledgePreviewWatermarkPositions(800, 640, compactLayout);
        expect(positions).toHaveLength(14);
        expect(positions[0]).toMatchObject({
            rowIndex: 0,
            columnIndex: 0,
            x: compactLayout.anchorX,
            y: compactLayout.anchorY,
        });
        expect(positions[4]).toMatchObject({
            rowIndex: 1,
            columnIndex: 0,
            x: compactLayout.anchorX + compactLayout.cellWidth / 2,
            y: compactLayout.anchorY + compactLayout.cellHeight,
        });
        expect(
            calculateKnowledgePreviewWatermarkPositions(800, 1000, compactLayout).length,
        ).toBeGreaterThan(positions.length);

        const { container } = renderWatermark();
        await act(async () => {
            await Promise.resolve();
        });
        const overlay = container.querySelector('[aria-hidden="true"]');
        expect(overlay?.querySelectorAll("svg")).toHaveLength(1);
        expect(overlay?.querySelectorAll("pattern")).toHaveLength(0);
        expect(overlay?.querySelectorAll("rect")).toHaveLength(0);
        const groups = Array.from(overlay?.querySelectorAll("g") ?? []);
        expect(groups.length).toBeGreaterThan(0);
        expect(overlay?.querySelectorAll("text")).toHaveLength(groups.length * 2);
        expect(groups.every((group) => group.querySelectorAll("text").length === 2)).toBe(true);
        act(() => emitResize(800, 1000));
        expect(overlay?.querySelectorAll("g").length).toBeGreaterThan(groups.length);

        const styleSource = readFileSync(
            path.resolve(process.cwd(), "src/pages/knowledge/FilePreview/KnowledgePreviewWatermark.module.css"),
            "utf8",
        );
        const filePreviewSource = readFileSync(
            path.resolve(process.cwd(), "src/pages/knowledge/FilePreview/index.tsx"),
            "utf8",
        );
        const richPreviewSource = readFileSync(
            path.resolve(process.cwd(), "src/pages/knowledge/FilePreview/RichKnowledgePreview.tsx"),
            "utf8",
        );
        const userDataSource = readFileSync(
            path.resolve(process.cwd(), "src/api/chat/data-service.ts"),
            "utf8",
        );
        const viewerSources = [
            "PdfViewer.tsx",
            "DocxViewer.tsx",
            "MarkdownViewer.tsx",
            "HtmlViewer.tsx",
            "TextViewer.tsx",
            "ImageViewer.tsx",
            "XlsxViewer.tsx",
        ].map((fileName) => readFileSync(
            path.resolve(process.cwd(), `src/pages/knowledge/FilePreview/viewers/${fileName}`),
            "utf8",
        )).join("\n");

        expect(styleSource).toMatch(/pointer-events:\s*none/);
        expect(styleSource).toMatch(/user-select:\s*none/);
        expect(styleSource).toMatch(/font-family:[^;]*(WenQuanYi Zen Hei|Microsoft YaHei)/);
        expect(styleSource).toMatch(/font-size:\s*16px/);
        expect(styleSource).toMatch(/fill:\s*#737373/);
        expect(styleSource).not.toMatch(/fill-opacity/);
        expect(styleSource).not.toMatch(/grid-auto-rows/);
        expect(styleSource).not.toMatch(/240px/);
        expect(styleSource).not.toMatch(/align-content:\s*space-around/);
        expect(filePreviewSource).toContain("<KnowledgePreviewWatermarkProvider>");
        expect(filePreviewSource).not.toContain("<KnowledgePreviewWatermark />");
        expect(richPreviewSource).toContain("<KnowledgePreviewWatermarkProvider>");
        expect(userDataSource).toContain("department_name");
        expect(userDataSource).toContain("external_id");
        expect(userDataSource).toContain('"departmentName"');
        expect(userDataSource).toContain('"externalId"');
        const watermarkSource = readFileSync(
            path.resolve(process.cwd(), "src/pages/knowledge/FilePreview/KnowledgePreviewWatermark.tsx"),
            "utf8",
        );
        expect(watermarkSource).not.toContain("<pattern");
        expect(watermarkSource).toContain("ResizeObserver");
        expect(watermarkSource).toContain("positions.map");
        expect(watermarkSource).toContain("fillOpacity={layout.opacity}");
        expect(viewerSources).toContain("data-preview-watermark-surface");
        expect(viewerSources).toContain("<KnowledgePreviewWatermark />");
        expect(viewerSources).toMatch(/relative[^"\n]*overflow-hidden|overflow-hidden[^"\n]*relative/);
    });
});
