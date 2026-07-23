import { SpaceLevel, SpaceRole, type KnowledgeSpace } from "~/api/knowledge";
import { mergeDepartmentSpaces, resolveSpacePermissions } from "./usePortalSpaces";

const makeSpace = (overrides: Partial<KnowledgeSpace> = {}): KnowledgeSpace =>
    ({
        id: "1",
        name: "库",
        role: SpaceRole.CREATOR,
        spaceLevel: SpaceLevel.PERSONAL,
        isFavorite: false,
        ...overrides,
    }) as KnowledgeSpace;

describe("resolveSpacePermissions（个人知识库只有编辑功能）", () => {
    it("个人库：即便是 creator 也不能删除、不能授权", () => {
        const perms = resolveSpacePermissions(
            makeSpace({ spaceLevel: SpaceLevel.PERSONAL, role: SpaceRole.CREATOR }),
            {},
        );
        expect(perms.canEditSpace).toBe(true);
        expect(perms.canDeleteSpace).toBe(false);
        expect(perms.canManageMembers).toBe(false);
    });

    it("个人默认库：admin(全局超管，role=admin) 仍不能删除", () => {
        const perms = resolveSpacePermissions(
            makeSpace({ id: "149", spaceLevel: SpaceLevel.PERSONAL, role: SpaceRole.ADMIN }),
            {},
        );
        expect(perms.canDeleteSpace).toBe(false);
    });

    it("个人收藏库不能删除", () => {
        const perms = resolveSpacePermissions(
            makeSpace({ id: "117", spaceLevel: SpaceLevel.PERSONAL, isFavorite: true }),
            {},
        );
        expect(perms.canDeleteSpace).toBe(false);
    });

    it("非个人库（团队）creator 可删除、可授权", () => {
        const perms = resolveSpacePermissions(
            makeSpace({ spaceLevel: SpaceLevel.TEAM, role: SpaceRole.CREATOR }),
            {},
        );
        expect(perms.canDeleteSpace).toBe(true);
        expect(perms.canManageMembers).toBe(true);
    });
});

describe("mergeDepartmentSpaces", () => {
    it("普通用户可见发现空间，同时保留原可管理空间的角色和元数据", () => {
        const discoverableOnly = makeSpace({
            id: "10",
            name: "全员可见部门库",
            role: SpaceRole.MEMBER,
            spaceLevel: SpaceLevel.DEPARTMENT,
        });
        const discoverableManaged = makeSpace({
            id: "11",
            name: "发现接口名称",
            role: SpaceRole.MEMBER,
            spaceLevel: SpaceLevel.DEPARTMENT,
        });
        const managed = makeSpace({
            id: "11",
            name: "管理接口名称",
            role: SpaceRole.ADMIN,
            spaceLevel: SpaceLevel.DEPARTMENT,
            departmentName: "炼钢部",
        });

        expect(mergeDepartmentSpaces([discoverableOnly, discoverableManaged], [managed])).toEqual([
            discoverableOnly,
            managed,
        ]);
    });
});
