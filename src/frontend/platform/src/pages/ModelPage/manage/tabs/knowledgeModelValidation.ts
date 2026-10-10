export type ModelId = number | string | null | undefined;

export interface ModelOption {
    value: ModelId;
}

export interface ModelOptionGroup {
    children?: ModelOption[];
}

export interface KnowledgeModelIds {
    embedding_model_id: ModelId;
    source_model_id: ModelId;
    extract_title_model_id: ModelId;
    qa_similar_model_id: ModelId;
    asr_model_id: ModelId;
}

export type KnowledgeModelIdField = keyof KnowledgeModelIds;

interface KnowledgeModelOptionGroups {
    llmOptions: ModelOptionGroup[];
    embeddings: ModelOptionGroup[];
    asrModels: ModelOptionGroup[];
}

function normalizeVisibleModelId(
    value: ModelId,
    options: ModelOptionGroup[],
): { value: ModelId; unavailable: boolean } {
    if (value === null || value === undefined || value === "") {
        return { value: null, unavailable: false };
    }

    const visible = options.some((group) =>
        group.children?.some((model) => String(model.value) === String(value)),
    );
    return visible
        ? { value, unavailable: false }
        : { value: null, unavailable: true };
}

export function normalizeKnowledgeModelIds(
    config: KnowledgeModelIds,
    options: KnowledgeModelOptionGroups,
): {
    modelIds: KnowledgeModelIds;
    unavailableFields: KnowledgeModelIdField[];
} {
    const optionGroupsByField: Record<KnowledgeModelIdField, ModelOptionGroup[]> = {
        embedding_model_id: options.embeddings,
        source_model_id: options.llmOptions,
        extract_title_model_id: options.llmOptions,
        qa_similar_model_id: options.llmOptions,
        asr_model_id: options.asrModels,
    };
    const modelIds = {} as KnowledgeModelIds;
    const unavailableFields: KnowledgeModelIdField[] = [];

    (Object.keys(optionGroupsByField) as KnowledgeModelIdField[]).forEach((field) => {
        const normalized = normalizeVisibleModelId(config[field], optionGroupsByField[field]);
        modelIds[field] = normalized.value;
        if (normalized.unavailable) unavailableFields.push(field);
    });

    return { modelIds, unavailableFields };
}
