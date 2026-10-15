import { SpaceLevel, SpaceRole } from "~/api/knowledge";

/** 非个人库的创建者或管理者点单个文件删除时, 才出现扣分选择. 服务端仍会再鉴权. */
export function canOfferKnowledgeViolationDelete(
    spaceLevel?: SpaceLevel | string | null,
    role?: SpaceRole | string | null,
): boolean {
    if (!spaceLevel || spaceLevel === SpaceLevel.PERSONAL) return false;
    return role === SpaceRole.CREATOR || role === SpaceRole.ADMIN;
}
