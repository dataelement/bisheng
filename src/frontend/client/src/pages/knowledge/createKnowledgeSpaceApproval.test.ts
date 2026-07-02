import { submitShougangKnowledgeSpaceCreateApprovalApi } from "~/api/approval";
import { createSpaceApi, SpaceLevel, VisibilityType } from "~/api/knowledge";
import {
    buildAutoTagLibraryPayload,
    submitKnowledgeSpaceCreate,
    submitKnowledgeSpaceCreateWithApproval,
} from "./createKnowledgeSpaceApproval";

jest.mock("~/api/approval", () => ({
    submitShougangKnowledgeSpaceCreateApprovalApi: jest.fn(),
}));

jest.mock("~/api/knowledge", () => {
    const actual = jest.requireActual("~/api/knowledge");
    return {
        ...actual,
        createSpaceApi: jest.fn(),
    };
});

describe("submitKnowledgeSpaceCreateWithApproval", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.mocked(submitShougangKnowledgeSpaceCreateApprovalApi).mockResolvedValue({
            decision: "pending",
            created: false,
            instance_id: 101,
            task_ids: [201],
        });
        jest.mocked(createSpaceApi).mockResolvedValue({
            id: "personal-1",
            name: "个人资料库",
            spaceLevel: SpaceLevel.PERSONAL,
        } as any);
    });

    it("submits normal knowledge create form through Shougang approval API", async () => {
        await submitKnowledgeSpaceCreateWithApproval({
            name: "团队资料库",
            description: "资料说明",
            joinPolicy: "review",
            publishToSquare: "yes",
            spaceLevel: SpaceLevel.TEAM,
            departmentId: undefined,
            autoTagEnabled: true,
            autoTagLibraryIds: [9],
            reason: "申请创建团队知识库",
        } as any);

        const payload = jest.mocked(submitShougangKnowledgeSpaceCreateApprovalApi).mock.calls[0][0];
        expect(payload).toEqual({
            name: "团队资料库",
            description: "资料说明",
            auth_type: VisibilityType.APPROVAL,
            is_released: true,
            space_level: SpaceLevel.TEAM,
            department_id: undefined,
            auto_tag_enabled: true,
            auto_tag_library_id: 9,
            auto_tag_library_ids: [9],
            reason: "申请创建团队知识库",
        });
        expect(payload).not.toHaveProperty("user_group_id");
        expect(payload).not.toHaveProperty("business_domain_codes");
    });

    it("creates personal knowledge space directly without approval", async () => {
        const result = await submitKnowledgeSpaceCreate({
            name: "个人资料库",
            description: "个人说明",
            joinPolicy: "review",
            publishToSquare: "no",
            spaceLevel: SpaceLevel.PERSONAL,
            departmentId: undefined,
            autoTagEnabled: true,
            autoTagLibraryIds: [3],
        } as any);

        expect(createSpaceApi).toHaveBeenCalledWith({
            name: "个人资料库",
            description: "个人说明",
            auth_type: VisibilityType.PRIVATE,
            is_released: false,
            space_level: SpaceLevel.PERSONAL,
            auto_tag_enabled: true,
            auto_tag_library_id: 3,
            auto_tag_library_ids: [3],
        });
        expect(submitShougangKnowledgeSpaceCreateApprovalApi).not.toHaveBeenCalled();
        expect(result).toEqual(expect.objectContaining({
            created: true,
            space: expect.objectContaining({ id: "personal-1" }),
        }));
    });

    it("buildAutoTagLibraryPayload syncExplicitly clears bindings on edit save", () => {
        expect(buildAutoTagLibraryPayload([], { syncExplicitly: true })).toEqual({
            auto_tag_library_ids: [],
            auto_tag_library_id: null,
        });
    });
});
