/**
 * Clicking a square card for a channel the viewer cannot read used to open the
 * preview drawer, fire the article list, take a 403, and let the global 403
 * handler replace the page with the home view plus a "暂无查看权限" toast. The
 * drawer already had an intro-and-apply state for exactly this case — it just
 * asked for the articles anyway.
 */

import { canReadChannelContent } from "./channelContentAccess";

describe("canReadChannelContent", () => {
    it("refuses a viewer with no visible action, no subscription and no ownership", () => {
        expect(canReadChannelContent({ actions: ["edit"], isSubscribed: false })).toBe(false);
    });

    it("admits a grant holder who never subscribed", () => {
        // The reported department-grant case: no subscription row, but the
        // catalog makes the channel visible.
        expect(canReadChannelContent({ actions: ["visible"], isSubscribed: false })).toBe(true);
    });

    it("admits an active subscriber", () => {
        expect(canReadChannelContent({ actions: [], isSubscribed: true })).toBe(true);
    });

    it("admits the creator", () => {
        expect(canReadChannelContent({ actions: [], isCreatorView: true })).toBe(true);
    });

    it("refuses when actions are absent and the viewer is neither owner nor subscriber", () => {
        expect(canReadChannelContent({})).toBe(false);
        expect(canReadChannelContent({ actions: null })).toBe(false);
        expect(canReadChannelContent({ actions: undefined, isSubscribed: false })).toBe(false);
    });

    it("does not treat a pending application as access", () => {
        expect(canReadChannelContent({ actions: [], isSubscribed: false })).toBe(false);
    });

    it("ignores a permission_ids-era payload instead of trusting it", () => {
        // `permission_ids` / `view_channel` were retired with F048. A payload
        // carrying only those must not read as access.
        const legacy = { permission_ids: ["view_channel"] } as unknown as { actions?: string[] };
        expect(canReadChannelContent({ actions: legacy.actions, isSubscribed: false })).toBe(false);
    });
});
