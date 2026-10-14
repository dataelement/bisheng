import { act, renderHook, waitFor } from "@testing-library/react";
import { checkPermission } from "~/api/permission";
import { useKnowledgeContainerWritePermissions } from "./useKnowledgeContainerWritePermissions";

let mockUser = { id: "7", role: "user", tenant_id: 1 };
jest.mock("recoil", () => ({ useRecoilValue: () => mockUser }));
jest.mock("~/store", () => ({ __esModule: true, default: { user: {} } }));
jest.mock("~/api/permission", () => ({ checkPermission: jest.fn() }));
const check = jest.mocked(checkPermission);
const root = { spaceId: "100", folderId: undefined as string | undefined, isSpaceAdmin: false };
const denied = { canCreateFolder: false, canUploadFile: false };

function deferred() {
    let resolve!: (value: { allowed: boolean }) => void;
    const promise = new Promise<{ allowed: boolean }>((done) => { resolve = done; });
    return { promise, resolve };
}

beforeEach(() => {
    mockUser = { id: "7", role: "user", tenant_id: 1 };
    check.mockReset();
    check.mockResolvedValue({ allowed: true });
});

it("根目录编辑者进入查看目录立即禁止写操作，允许其他可写目录", async () => {
    const pending = deferred();
    const { result, rerender } = renderHook(useKnowledgeContainerWritePermissions, { initialProps: root });
    await waitFor(() => expect(result.current.canUploadFile).toBe(true));
    check.mockImplementation((type, id) => id === "200" ? pending.promise : Promise.resolve({ allowed: true }));
    rerender({ ...root, folderId: "200" });
    expect(result.current).toEqual(denied);
    await act(async () => pending.resolve({ allowed: false }));
    expect(result.current).toEqual(denied);
    expect(check).toHaveBeenCalledWith("folder", "200", "can_edit", "upload_file_to_folder", expect.anything());
    rerender({ ...root, folderId: "300" });
    await waitFor(() => expect(result.current.canUploadFile).toBe(true));
});

it("迟到的允许结果和失败查询不能恢复其他目录权限", async () => {
    const pending = deferred();
    check.mockImplementation((_type, id) => id === "200" ? pending.promise : Promise.reject(new Error("offline")));
    const { result, rerender } = renderHook(useKnowledgeContainerWritePermissions, {
        initialProps: { ...root, folderId: "200" },
    });
    rerender({ ...root, folderId: "300" });
    await act(async () => pending.resolve({ allowed: true }));
    expect(result.current).toEqual(denied);
    expect(check.mock.calls[0][4]?.signal?.aborted).toBe(true);
});

it.each(["account", "tenant", "space"])("%s 改变立即失效，旧响应不可生效", async (change) => {
    const { result, rerender } = renderHook(useKnowledgeContainerWritePermissions, { initialProps: root });
    await waitFor(() => expect(result.current.canUploadFile).toBe(true));
    const old = deferred();
    check.mockReturnValue(old.promise);
    rerender({ ...root, folderId: "200" });
    const next = deferred();
    check.mockReturnValue(next.promise);
    if (change === "account") mockUser = { ...mockUser, id: "8" };
    if (change === "tenant") mockUser = { ...mockUser, tenant_id: 2 };
    rerender({ ...root, folderId: "200", spaceId: change === "space" ? "101" : "100" });
    expect(result.current).toEqual(denied);
    await act(async () => old.resolve({ allowed: true }));
    expect(result.current).toEqual(denied);
    await act(async () => next.resolve({ allowed: false }));
    expect(result.current).toEqual(denied);
});

it("知识库管理员快捷权限只适用于根目录，目录操作仍查询后端", async () => {
    check.mockResolvedValue({ allowed: false });
    const { result, rerender } = renderHook(useKnowledgeContainerWritePermissions, {
        initialProps: { ...root, isSpaceAdmin: true },
    });
    expect(result.current.canUploadFile).toBe(true);
    expect(check).not.toHaveBeenCalled();
    rerender({ ...root, isSpaceAdmin: true, folderId: "200" });
    expect(result.current).toEqual(denied);
    await waitFor(() => expect(check).toHaveBeenCalledTimes(2));
    expect(result.current).toEqual(denied);
});

it("无目标库不授权，创建与上传分别遵循接口结果", async () => {
    const { result, rerender } = renderHook(useKnowledgeContainerWritePermissions, {
        initialProps: { ...root, spaceId: undefined as string | undefined },
    });
    expect(result.current).toEqual(denied);
    expect(check).not.toHaveBeenCalled();
    check.mockImplementation((_type, _id, _relation, permission) => Promise.resolve({ allowed: permission === "create_folder" }));
    rerender(root);
    await waitFor(() => expect(result.current.canCreateFolder).toBe(true));
    expect(result.current.canUploadFile).toBe(false);
});
