import { extractKnowledgeActionErrorMessage } from "./errorUtils";

describe("extractKnowledgeActionErrorMessage", () => {
    it("prefers backend status_message from response data", () => {
        expect(extractKnowledgeActionErrorMessage({
            message: "删除知识库失败",
            status_message: "Permission denied",
            response: {
                data: {
                    status_message: "科室知识库禁止删除，请先在后台解除部门绑定",
                },
            },
        })).toBe("科室知识库禁止删除，请先在后台解除部门绑定");
    });

    it("falls back to Error.message", () => {
        expect(extractKnowledgeActionErrorMessage(new Error("request failed"))).toBe("request failed");
    });
});
