/**
 * A share link is a way in, not an application form.
 *
 * Opening /knowledge/share/130 as someone who already had the space — it was
 * listed in their own sidebar under 我加入的 — put up the intro-and-apply drawer
 * instead of taking them into it. Only the space's creator was let through, and
 * `role` cannot tell a member from a stranger: /info leaves it unset for a
 * non-member and the client maps unset to MEMBER, the very value a real member
 * carries.
 */

import { canOpenSharedSpace } from "./knowledgeUtils";

describe("canOpenSharedSpace", () => {
    it("lets in a viewer the space is visible to", () => {
        // The reported case: granted through a department, no membership row.
        expect(canOpenSharedSpace({ actions: ["visible", "use"], role: "member" })).toBe(true);
    });

    it("keeps out a viewer who may only preview and apply", () => {
        expect(canOpenSharedSpace({ actions: [], role: "member" })).toBe(false);
    });

    it("does not read an absent role as membership", () => {
        // /info returns no role for a non-member; the client fills in MEMBER.
        expect(canOpenSharedSpace({ actions: [], role: undefined })).toBe(false);
        expect(canOpenSharedSpace({ actions: [] })).toBe(false);
    });

    it("admits the creator whatever the actions say", () => {
        // Their own space: letting them in cannot be the wrong answer, and an
        // empty action list must not lock an owner out of their own link.
        expect(canOpenSharedSpace({ role: "creator" })).toBe(true);
        expect(canOpenSharedSpace({ actions: null, role: "creator" })).toBe(true);
        expect(canOpenSharedSpace({ actions: [], role: "creator" })).toBe(true);
    });

    it("refuses anyone else without a visible action", () => {
        expect(canOpenSharedSpace({ role: "member" })).toBe(false);
        expect(canOpenSharedSpace({})).toBe(false);
    });
});
