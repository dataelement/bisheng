import { beforeEach, describe, expect, it, vi } from "vitest";
import { listKnowledgeChildren } from "../index";

// Mock the axios wrapper used by index.ts
vi.mock("@/controllers/request", () => ({
    default: { get: vi.fn() },
}));

// Import the mock AFTER the module mock is registered so we get the mocked instance
import axiosMock from "@/controllers/request";

describe("listKnowledgeChildren", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("calls /api/v1/knowledge_space/<id>/children with correct params", async () => {
        (axiosMock.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], total: 0 });
        await listKnowledgeChildren({
            knowledge_id: 7,
            parent_id: 12,
            file_type: 0,
            page: 2,
            page_size: 50,
            keyword: "abc",
        });
        expect(axiosMock.get).toHaveBeenCalledWith(
            "/api/v1/knowledge_space/7/children",
            {
                params: {
                    parent_id: 12,
                    file_type: 0,
                    page: 2,
                    page_size: 50,
                    keyword: "abc",
                },
            }
        );
    });

    it("sends parent_id='' when null", async () => {
        (axiosMock.get as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], total: 0 });
        await listKnowledgeChildren({ knowledge_id: 1, parent_id: null });
        expect(axiosMock.get).toHaveBeenCalledWith(
            "/api/v1/knowledge_space/1/children",
            {
                params: {
                    parent_id: "",
                    file_type: undefined,
                    page: 1,
                    page_size: 200,
                    keyword: undefined,
                },
            }
        );
    });
});
