import { SpaceLevel } from "~/api/knowledge";
import { resolveInitialCreateLevel } from "./CreateKnowledgeSpaceDrawer";

// 个人库不可创建，故可创建集合仅公共/部门/团队
const ENABLED = [SpaceLevel.PUBLIC, SpaceLevel.DEPARTMENT, SpaceLevel.TEAM];

describe("resolveInitialCreateLevel（新建弹窗默认层级）", () => {
    it("当前层级可创建时保持不变", () => {
        expect(resolveInitialCreateLevel(ENABLED, SpaceLevel.TEAM, SpaceLevel.PUBLIC)).toBe(SpaceLevel.TEAM);
        expect(resolveInitialCreateLevel(ENABLED, SpaceLevel.DEPARTMENT, SpaceLevel.PUBLIC)).toBe(SpaceLevel.DEPARTMENT);
    });

    it("当前层级不可创建（竞态下读到旧 PERSONAL）时，回退到点击进入的分类，而非固定公共", () => {
        expect(resolveInitialCreateLevel(ENABLED, SpaceLevel.PERSONAL, SpaceLevel.DEPARTMENT)).toBe(SpaceLevel.DEPARTMENT);
        expect(resolveInitialCreateLevel(ENABLED, SpaceLevel.PERSONAL, SpaceLevel.TEAM)).toBe(SpaceLevel.TEAM);
    });

    it("initial 也不可创建（或缺省）时，退到第一个可创建项（公共）", () => {
        expect(resolveInitialCreateLevel(ENABLED, SpaceLevel.PERSONAL, SpaceLevel.PERSONAL)).toBe(SpaceLevel.PUBLIC);
        expect(resolveInitialCreateLevel(ENABLED, SpaceLevel.PERSONAL, undefined)).toBe(SpaceLevel.PUBLIC);
    });
});
