import { beforeEach, describe, expect, it } from "vitest";
import { useKnowledgeStore } from "./useKnowledgeStore";

describe("useKnowledgeStore tree state", () => {
    beforeEach(() => {
        useKnowledgeStore.setState({
            currentParentId: null,
            selectedFileId: null,
            breadcrumbPath: [],
        });
    });

    it("setCurrentParent updates id and breadcrumb", () => {
        useKnowledgeStore.getState().setCurrentParent(42, [{ id: 1, name: "a" }, { id: 42, name: "b" }]);
        const s = useKnowledgeStore.getState();
        expect(s.currentParentId).toBe(42);
        expect(s.breadcrumbPath).toEqual([{ id: 1, name: "a" }, { id: 42, name: "b" }]);
        expect(s.selectedFileId).toBe(null);
    });

    it("setSelectedFile updates only selectedFileId", () => {
        useKnowledgeStore.getState().setCurrentParent(5, [{ id: 5, name: "x" }]);
        useKnowledgeStore.getState().setSelectedFile(99);
        expect(useKnowledgeStore.getState().selectedFileId).toBe(99);
        expect(useKnowledgeStore.getState().currentParentId).toBe(5);
    });

    it("setCurrentParent clears selectedFileId", () => {
        useKnowledgeStore.setState({ selectedFileId: 99 });
        useKnowledgeStore.getState().setCurrentParent(7, []);
        expect(useKnowledgeStore.getState().selectedFileId).toBe(null);
    });
});
