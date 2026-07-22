import { act, render } from "@testing-library/react";
import { readFileSync } from "fs";
import path from "path";
import { RecoilRoot } from "recoil";

import store from "~/store";
import KnowledgePreviewWatermark, {
    KnowledgePreviewWatermarkProvider,
    buildKnowledgePreviewWatermarkLines,
    calculateKnowledgePreviewWatermarkGrid,
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

let resizeCallback: ResizeObserverCallback | null = null;
const originalResizeObserver = globalThis.ResizeObserver;

class ResizeObserverMock {
    constructor(callback: ResizeObserverCallback) {
        resizeCallback = callback;
    }

    observe() {}

    unobserve() {}

    disconnect() {}
}

function renderWatermark(user = currentUser) {
    return render(
        <RecoilRoot initializeState={({ set }) => set(store.user, user)}>
            <KnowledgePreviewWatermarkProvider>
                <div className="relative">
                    <KnowledgePreviewWatermark />
                </div>
            </KnowledgePreviewWatermarkProvider>
        </RecoilRoot>,
    );
}

describe("KnowledgePreviewWatermark", () => {
    beforeEach(() => {
        jest.useFakeTimers();
        jest.setSystemTime(new Date("2026-07-21T04:05:06.000Z"));
        resizeCallback = null;
        globalThis.ResizeObserver = ResizeObserverMock;
    });

    afterEach(() => {
        jest.useRealTimers();
        globalThis.ResizeObserver = originalResizeObserver;
    });

    test("uses the current Bisheng user and keeps the mount-time Beijing clock", () => {
        expect(formatKnowledgePreviewWatermarkTime(new Date())).toBe("2026-07-21");
        expect(buildKnowledgePreviewWatermarkLines(currentUser, new Date())).toEqual([
            "设备管理部-张三--SG001-2026-07-21",
            "首钢股份内部资料，严禁外传，违者必究",
        ]);

        const { container, rerender } = renderWatermark();
        expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
        expect(container.textContent).toContain("设备管理部-张三--SG001-2026-07-21");
        expect(container.textContent).toContain("2026-07-21");
        expect(container.textContent).toContain("首钢股份内部资料，严禁外传，违者必究");
        expect(container.textContent).not.toContain("首钢集团内部资料");

        jest.setSystemTime(new Date("2026-07-21T04:10:06.000Z"));
        rerender(
            <RecoilRoot initializeState={({ set }) => set(store.user, currentUser)}>
                <KnowledgePreviewWatermarkProvider>
                    <div className="relative">
                        <KnowledgePreviewWatermark />
                    </div>
                </KnowledgePreviewWatermarkProvider>
            </RecoilRoot>,
        );
        expect(container.textContent).toContain("2026-07-21");
        expect(container.textContent).not.toContain("12:10:06");
    });

    test("falls back to username/account and clips overlays to document surfaces", () => {
        expect(buildKnowledgePreviewWatermarkLines(
            { ...currentUser, name: "", username: "lisi", departmentName: "", externalId: "" },
            new Date(),
        )[0]).toBe("lisi--lisi-2026-07-21");

        const compactGrid = calculateKnowledgePreviewWatermarkGrid(800, 640);
        const tallGrid = calculateKnowledgePreviewWatermarkGrid(800, 2400);
        expect(compactGrid).toEqual({ columns: 5, rows: 5, tileCount: 25 });
        expect(tallGrid.tileCount).toBeGreaterThan(compactGrid.tileCount);

        const { container } = renderWatermark();
        const overlay = container.querySelector('[aria-hidden="true"]');
        expect(overlay?.children).toHaveLength(4);
        act(() => {
            resizeCallback?.(
                [{ contentRect: { width: 800, height: 640 } } as ResizeObserverEntry],
                {} as ResizeObserver,
            );
        });
        expect(overlay?.children).toHaveLength(25);
        act(() => {
            resizeCallback?.(
                [{ contentRect: { width: 800, height: 2400 } } as ResizeObserverEntry],
                {} as ResizeObserver,
            );
        });
        expect(overlay?.children).toHaveLength(tallGrid.tileCount);

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
        expect(styleSource).toMatch(/rgba\(115,\s*115,\s*115,\s*0\.16\)/);
        expect(styleSource).toMatch(/transform:\s*rotate\(-35deg\)/);
        expect(styleSource).toMatch(/grid-auto-rows:\s*160px/);
        expect(styleSource).toMatch(/padding:\s*48px\s+0\s+0\s+27px/);
        expect(styleSource).toMatch(/240px/);
        expect(styleSource).not.toMatch(/align-content:\s*space-around/);
        expect(filePreviewSource).toContain("<KnowledgePreviewWatermarkProvider>");
        expect(filePreviewSource).not.toContain("<KnowledgePreviewWatermark />");
        expect(richPreviewSource).toContain("<KnowledgePreviewWatermarkProvider>");
        expect(userDataSource).toContain("department_name");
        expect(userDataSource).toContain("external_id");
        expect(userDataSource).toContain('"departmentName"');
        expect(userDataSource).toContain('"externalId"');
        expect(readFileSync(
            path.resolve(process.cwd(), "src/pages/knowledge/FilePreview/KnowledgePreviewWatermark.tsx"),
            "utf8",
        )).toContain("ResizeObserver");
        expect(viewerSources).toContain("data-preview-watermark-surface");
        expect(viewerSources).toContain("<KnowledgePreviewWatermark />");
        expect(viewerSources).toMatch(/relative[^"\n]*overflow-hidden|overflow-hidden[^"\n]*relative/);
    });
});
