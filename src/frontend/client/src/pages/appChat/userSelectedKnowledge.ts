export const USER_SELECTED_KNOWLEDGE_RAG_NODE = "user_selected_knowledge_rag";
export const USER_SELECTED_KNOWLEDGE_RETRIEVER_NODE = "user_selected_knowledge_retriever";
export const RUNTIME_KNOWLEDGE_SELECTION_FIELD = "__runtime_knowledge_selection";
export const MAX_RUNTIME_KNOWLEDGE_FILES = 20;

export type RuntimeKnowledgeSourceType = "knowledge" | "space";
export type RuntimeKnowledgeMode = "source" | "items";
export type RuntimeKnowledgeRefType = "file" | "folder";

export interface RuntimeKnowledgeSource {
    source_type: RuntimeKnowledgeSourceType;
    source_id: number;
    source_name: string;
}

export interface RuntimeKnowledgeItem extends RuntimeKnowledgeSource {
    ref_type: RuntimeKnowledgeRefType;
    id: number;
    name: string;
}

export interface RuntimeKnowledgeSelection {
    mode: RuntimeKnowledgeMode;
    whole_source: RuntimeKnowledgeSource | null;
    items: RuntimeKnowledgeItem[];
    effective_file_count: number | null;
}

export interface RuntimeKnowledgePickerVisibility {
    requiresRuntimeKnowledge: boolean;
    inputDisabled: boolean;
    hasInputForm?: boolean;
    readOnly?: boolean;
}

const USER_SELECTED_KNOWLEDGE_NODE_TYPES = [
    USER_SELECTED_KNOWLEDGE_RAG_NODE,
    USER_SELECTED_KNOWLEDGE_RETRIEVER_NODE,
];

export function getFlowNodes(flowOrNodes: any): any[] {
    if (Array.isArray(flowOrNodes)) return flowOrNodes;
    if (Array.isArray(flowOrNodes?.nodes)) return flowOrNodes.nodes;
    if (Array.isArray(flowOrNodes?.data?.nodes)) return flowOrNodes.data.nodes;
    return [];
}

export function hasUserSelectedKnowledgeNode(flowOrNodes: any): boolean {
    return getFlowNodes(flowOrNodes).some((node) => {
        const type = node?.data?.type ?? node?.type;
        return USER_SELECTED_KNOWLEDGE_NODE_TYPES.includes(type);
    });
}

export function shouldRenderRuntimeKnowledgePicker({
    requiresRuntimeKnowledge,
    inputDisabled,
    hasInputForm = false,
    readOnly = false,
}: RuntimeKnowledgePickerVisibility): boolean {
    if (!requiresRuntimeKnowledge || readOnly) return false;
    return !inputDisabled || hasInputForm;
}

export function isRuntimeKnowledgePickerDisabled({
    inputDisabled,
    hasInputForm = false,
    readOnly = false,
}: Pick<RuntimeKnowledgePickerVisibility, "inputDisabled" | "hasInputForm" | "readOnly">): boolean {
    return readOnly || (inputDisabled && !hasInputForm);
}

export function validateRuntimeKnowledgeSelection(selection?: RuntimeKnowledgeSelection | null): string {
    if (!selection) return "请选择知识库或知识空间。";
    if (selection.mode === "source") {
        if (!selection.whole_source?.source_id || !selection.whole_source.source_type) return "请选择知识库或知识空间。";
        if (selection.items?.length) return "完整知识来源不能与文件或文件夹范围同时选择。";
        return "";
    }
    if (selection.mode !== "items" || !selection.items?.length) return "请选择知识库或知识空间。";
    if (new Set(selection.items.map((item) => item.source_type)).size > 1) {
        return "文件或文件夹范围不能同时选择知识库和知识空间。";
    }
    if ((selection.effective_file_count ?? 0) > MAX_RUNTIME_KNOWLEDGE_FILES) {
        return `一次最多可选择${MAX_RUNTIME_KNOWLEDGE_FILES}个文件。`;
    }
    return "";
}
