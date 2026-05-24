import { submitShougangKnowledgeSpaceCreateApprovalApi } from "~/api/approval";
import { SpaceLevel, VisibilityType } from "~/api/knowledge";
import { submitKnowledgeSpaceCreateWithApproval } from "./createKnowledgeSpaceApproval";

jest.mock("~/api/approval", () => ({
    submitShougangKnowledgeSpaceCreateApprovalApi: jest.fn(),
}));

describe("submitKnowledgeSpaceCreateWithApproval", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.mocked(submitShougangKnowledgeSpaceCreateApprovalApi).mockResolvedValue({
            decision: "pending",
            created: false,
            instance_id: 101,
            task_ids: [201],
        });
    });

    it("submits normal knowledge create form through Shougang approval API", async () => {
        await submitKnowledgeSpaceCreateWithApproval({
            name: "团队资料库",
            description: "资料说明",
            joinPolicy: "review",
            publishToSquare: "yes",
            spaceLevel: SpaceLevel.TEAM,
            userGroupId: 7,
            departmentId: undefined,
            autoTagEnabled: true,
            autoTagLibraryId: 9,
            autoTagCustomTags: ["技术"],
            reason: "申请创建团队知识库",
        });

        expect(submitShougangKnowledgeSpaceCreateApprovalApi).toHaveBeenCalledWith({
            name: "团队资料库",
            description: "资料说明",
            auth_type: VisibilityType.APPROVAL,
            is_released: true,
            space_level: SpaceLevel.TEAM,
            department_id: undefined,
            user_group_id: 7,
            auto_tag_enabled: true,
            auto_tag_library_id: 9,
            auto_tag_custom_tags: ["技术"],
            reason: "申请创建团队知识库",
        });
    });
});
