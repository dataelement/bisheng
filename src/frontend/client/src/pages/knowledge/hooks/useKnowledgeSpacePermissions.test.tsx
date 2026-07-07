import { render, waitFor } from "@testing-library/react";
import { checkPermission } from "~/api/permission";
import { useAuthContext } from "~/hooks";
import {
    useKnowledgeSpaceActionPermissions,
    type KnowledgeSpaceActionPermission,
} from "./useKnowledgeSpacePermissions";

jest.mock("~/api/permission", () => ({ checkPermission: jest.fn() }));
jest.mock("~/hooks", () => ({ useAuthContext: jest.fn() }));

const mockCheck = checkPermission as jest.Mock;

function Probe({ permissionIds }: { permissionIds?: readonly KnowledgeSpaceActionPermission[] }) {
    useKnowledgeSpaceActionPermissions(["s1"], { permissionIds });
    return null;
}

describe("useKnowledgeSpaceActionPermissions permissionIds", () => {
    beforeEach(() => {
        mockCheck.mockReset();
        // 普通成员：不是系统管理员、不在 fullAccess，才会真正发权限检查请求
        (useAuthContext as jest.Mock).mockReturnValue({ user: { role: "member" } });
        mockCheck.mockResolvedValue({ allowed: true });
    });

    it("默认查询全部 4 个操作权限", async () => {
        render(<Probe />);
        await waitFor(() => expect(mockCheck).toHaveBeenCalledTimes(4));
    });

    it("传入 permissionIds 时只查询这些权限（share_space 只发 1 个请求）", async () => {
        render(<Probe permissionIds={["share_space"]} />);
        await waitFor(() => expect(mockCheck).toHaveBeenCalledTimes(1));
        expect(mockCheck).toHaveBeenCalledWith(
            "knowledge_space",
            "s1",
            "can_manage",
            "share_space",
            expect.anything(),
        );
    });
});
