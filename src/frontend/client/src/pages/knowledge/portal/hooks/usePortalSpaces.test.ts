import { SpaceLevel, SpaceRole, type KnowledgeSpace } from "~/api/knowledge";
import { resolveSpacePermissions } from "./usePortalSpaces";

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
