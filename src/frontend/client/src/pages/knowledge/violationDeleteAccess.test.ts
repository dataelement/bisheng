import { SpaceLevel, SpaceRole } from "~/api/knowledge";
import { canOfferKnowledgeViolationDelete } from "./violationDeleteAccess";

describe("canOfferKnowledgeViolationDelete", () => {
    it("hides the action in a personal library and for ordinary members", () => {
        expect(canOfferKnowledgeViolationDelete(SpaceLevel.PERSONAL, SpaceRole.CREATOR)).toBe(false);
        expect(canOfferKnowledgeViolationDelete(SpaceLevel.PUBLIC, SpaceRole.MEMBER)).toBe(false);
        expect(canOfferKnowledgeViolationDelete(SpaceLevel.PUBLIC, SpaceRole.CREATOR)).toBe(true);
        expect(canOfferKnowledgeViolationDelete(SpaceLevel.TEAM_KS, SpaceRole.ADMIN)).toBe(true);
    });
});
