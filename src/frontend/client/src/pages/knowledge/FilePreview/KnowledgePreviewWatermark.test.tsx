import { render } from "@testing-library/react";
import { readFileSync } from "fs";
import path from "path";
import { RecoilRoot } from "recoil";

import store from "~/store";
import KnowledgePreviewWatermark, {
    buildKnowledgePreviewWatermarkLines,
    formatKnowledgePreviewWatermarkTime,
} from "./KnowledgePreviewWatermark";

const currentUser = {
    id: "7",
    username: "zhangsan",
    email: "zhangsan@example.com",
    name: "张三",
    avatar: "",
    role: "member",
    provider: "local",
    createdAt: "",
    updatedAt: "",
};

function renderWatermark(user = currentUser) {
    return render(
        <RecoilRoot initializeState={({ set }) => set(store.user, user)}>
            <div className="relative">
                <KnowledgePreviewWatermark />
            </div>
        </RecoilRoot>,
    );
}

describe("KnowledgePreviewWatermark", () => {
    beforeEach(() => {
        jest.useFakeTimers();
        jest.setSystemTime(new Date("2026-07-21T04:05:06.000Z"));
    });

    afterEach(() => {
        jest.useRealTimers();
    });

    test("uses the current Bisheng user and keeps the mount-time Beijing clock", () => {
        expect(formatKnowledgePreviewWatermarkTime(new Date())).toBe("2026-07-21 12:05:06");
        expect(buildKnowledgePreviewWatermarkLines(currentUser, new Date())).toEqual([
            "姓名：张三",
            "工号/账号：zhangsan",
            "北京时间：2026-07-21 12:05:06",
            "首钢集团内部资料",
        ]);

        const { container, rerender } = renderWatermark();
        expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
        expect(container.textContent).toContain("北京时间：2026-07-21 12:05:06");

        jest.setSystemTime(new Date("2026-07-21T04:10:06.000Z"));
        rerender(
            <RecoilRoot initializeState={({ set }) => set(store.user, currentUser)}>
                <div className="relative">
                    <KnowledgePreviewWatermark />
                </div>
            </RecoilRoot>,
        );
        expect(container.textContent).toContain("北京时间：2026-07-21 12:05:06");
        expect(container.textContent).not.toContain("北京时间：2026-07-21 12:10:06");
    });

    test("falls back to username and remains visual-only in both knowledge preview bases", () => {
        expect(buildKnowledgePreviewWatermarkLines(
            { ...currentUser, name: "", username: "lisi" },
            new Date(),
        )[0]).toBe("姓名：lisi");

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

        expect(styleSource).toMatch(/pointer-events:\s*none/);
        expect(styleSource).toMatch(/user-select:\s*none/);
        expect(styleSource).toMatch(/transform:\s*rotate\(-\d+deg\)/);
        expect(filePreviewSource).toContain("<KnowledgePreviewWatermark />");
        expect(richPreviewSource).toContain("<KnowledgePreviewWatermark />");
    });
});
