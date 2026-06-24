import {
    hasUserSelectedKnowledgeNode,
    isRuntimeKnowledgePickerDisabled,
    RUNTIME_KNOWLEDGE_SELECTION_FIELD,
    shouldRenderRuntimeKnowledgePicker,
    validateRuntimeKnowledgeSelection,
} from "./userSelectedKnowledge";

describe("appChat user-selected knowledge helpers", () => {
    it("detects published workflows that contain user-selected knowledge nodes", () => {
        expect(
            hasUserSelectedKnowledgeNode({
                data: {
                    nodes: [
                        { data: { type: "input" } },
                        { data: { type: "user_selected_knowledge_retriever" } },
                    ],
                },
            }),
        ).toBe(true);

        expect(
            hasUserSelectedKnowledgeNode({
                nodes: [
                    { data: { type: "rag" } },
                    { data: { type: "knowledge_retriever" } },
                ],
            }),
        ).toBe(false);
    });

    it("validates source requirement, mutually exclusive modes, and file limit", () => {
        expect(validateRuntimeKnowledgeSelection(null)).toBe("请选择知识库或知识空间。");
        expect(
            validateRuntimeKnowledgeSelection({
                mode: "source",
                whole_source: { source_type: "knowledge", source_id: 1, source_name: "kb" },
                items: [],
                effective_file_count: null,
            }),
        ).toBe("");
        expect(
            validateRuntimeKnowledgeSelection({
                mode: "source",
                whole_source: { source_type: "knowledge", source_id: 1, source_name: "kb" },
                items: [{ source_type: "space", source_id: 2, source_name: "space", ref_type: "file", id: 3, name: "doc" }],
                effective_file_count: 1,
            }),
        ).toBe("完整知识来源不能与文件或文件夹范围同时选择。");
        expect(
            validateRuntimeKnowledgeSelection({
                mode: "items",
                whole_source: null,
                items: [
                    { source_type: "knowledge", source_id: 1, source_name: "kb", ref_type: "file", id: 2, name: "doc" },
                    { source_type: "space", source_id: 3, source_name: "space", ref_type: "file", id: 4, name: "space-doc" },
                ],
                effective_file_count: 2,
            }),
        ).toBe("文件或文件夹范围不能同时选择知识库和知识空间。");
        expect(
            validateRuntimeKnowledgeSelection({
                mode: "items",
                whole_source: null,
                items: [{ source_type: "space", source_id: 1, source_name: "space", ref_type: "folder", id: 2, name: "folder" }],
                effective_file_count: 21,
            }),
        ).toBe("一次最多可选择20个文件。");
    });

    it("uses the reserved input data field expected by backend", () => {
        expect(RUNTIME_KNOWLEDGE_SELECTION_FIELD).toBe("__runtime_knowledge_selection");
    });

    it("shows the runtime picker for dialog and form input states", () => {
        expect(
            shouldRenderRuntimeKnowledgePicker({
                requiresRuntimeKnowledge: true,
                inputDisabled: false,
            }),
        ).toBe(true);
        expect(
            shouldRenderRuntimeKnowledgePicker({
                requiresRuntimeKnowledge: true,
                inputDisabled: true,
                hasInputForm: true,
            }),
        ).toBe(true);
        expect(
            shouldRenderRuntimeKnowledgePicker({
                requiresRuntimeKnowledge: true,
                inputDisabled: true,
                hasInputForm: false,
            }),
        ).toBe(false);
        expect(
            shouldRenderRuntimeKnowledgePicker({
                requiresRuntimeKnowledge: true,
                inputDisabled: false,
                readOnly: true,
            }),
        ).toBe(false);
        expect(
            isRuntimeKnowledgePickerDisabled({
                inputDisabled: true,
                hasInputForm: true,
            }),
        ).toBe(false);
        expect(
            isRuntimeKnowledgePickerDisabled({
                inputDisabled: true,
                hasInputForm: false,
            }),
        ).toBe(true);
    });
});
