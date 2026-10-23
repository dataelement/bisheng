import { describe, expect, it } from "vitest";

import {
    KnowledgeModelIds,
    normalizeKnowledgeModelIds,
} from "@/pages/ModelPage/manage/tabs/knowledgeModelValidation";

const configuredModelIds: KnowledgeModelIds = {
    embedding_model_id: 101,
    source_model_id: 999,
    extract_title_model_id: 999,
    qa_similar_model_id: 202,
    asr_model_id: null,
};

const visibleModelOptions = {
    embeddings: [{ children: [{ value: 101 }] }],
    llmOptions: [{ children: [{ value: 202 }] }],
    asrModels: [],
};

describe("normalizeKnowledgeModelIds", () => {
    it("clears unavailable model references while preserving visible selections", () => {
        expect(normalizeKnowledgeModelIds(configuredModelIds, visibleModelOptions)).toEqual({
            modelIds: {
                embedding_model_id: 101,
                source_model_id: null,
                extract_title_model_id: null,
                qa_similar_model_id: 202,
                asr_model_id: null,
            },
            unavailableFields: ["source_model_id", "extract_title_model_id"],
        });
    });

    it("matches numeric model ids returned as strings by a selector", () => {
        expect(
            normalizeKnowledgeModelIds(
                {
                    ...configuredModelIds,
                    embedding_model_id: "101",
                    source_model_id: null,
                    extract_title_model_id: 202,
                },
                visibleModelOptions,
            ),
        ).toEqual({
            modelIds: {
                embedding_model_id: "101",
                source_model_id: null,
                extract_title_model_id: 202,
                qa_similar_model_id: 202,
                asr_model_id: null,
            },
            unavailableFields: [],
        });
    });
});
