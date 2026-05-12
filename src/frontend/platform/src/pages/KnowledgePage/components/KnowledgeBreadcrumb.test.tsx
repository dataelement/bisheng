import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KnowledgeBreadcrumb } from "./KnowledgeBreadcrumb";

describe("KnowledgeBreadcrumb", () => {
    it("renders space root + path segments", () => {
        render(
            <KnowledgeBreadcrumb
                spaceName="技术空间"
                path={[{ id: 1, name: "项目A" }, { id: 2, name: "文档" }]}
                onNavigate={() => {}}
            />
        );
        expect(screen.getByText("技术空间")).toBeInTheDocument();
        expect(screen.getByText("项目A")).toBeInTheDocument();
        expect(screen.getByText("文档")).toBeInTheDocument();
    });

    it("clicking a segment fires onNavigate with that segment id", () => {
        const onNav = vi.fn();
        render(
            <KnowledgeBreadcrumb
                spaceName="X"
                path={[{ id: 11, name: "A" }, { id: 22, name: "B" }]}
                onNavigate={onNav}
            />
        );
        fireEvent.click(screen.getByText("A"));
        expect(onNav).toHaveBeenCalledWith(11, 0);
    });

    it("clicking space root fires onNavigate(null, -1)", () => {
        const onNav = vi.fn();
        render(
            <KnowledgeBreadcrumb
                spaceName="X"
                path={[{ id: 11, name: "A" }]}
                onNavigate={onNav}
            />
        );
        fireEvent.click(screen.getByText("X"));
        expect(onNav).toHaveBeenCalledWith(null, -1);
    });
});
