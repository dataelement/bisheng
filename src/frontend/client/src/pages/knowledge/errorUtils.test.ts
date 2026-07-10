import { extractKnowledgeActionErrorMessage } from "./errorUtils";

describe("extractKnowledgeActionErrorMessage", () => {
    it("prefers backend status_message from response data", () => {
        expect(extractKnowledgeActionErrorMessage({
            message: "删除知识库失败",
            status_message: "Permission denied",
            response: {
                data: {
                    status_message: "无法迁移：创建者无主部门，或所属部门（含上级）未绑定科室知识库",
                },
            },
        })).toBe("无法迁移：创建者无主部门，或所属部门（含上级）未绑定科室知识库");
    });

    it("falls back to Error.message", () => {
        expect(extractKnowledgeActionErrorMessage(new Error("request failed"))).toBe("request failed");
    });
});
