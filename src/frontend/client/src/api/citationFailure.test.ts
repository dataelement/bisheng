import request from "~/api/request";
import { getCitationDetail, getCitationUnresolvedReason } from "~/api/chatApi";
import { readCitationFailure } from "~/api/citationFailure";

jest.mock("~/api/request", () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));

const get = jest.mocked(request.get);

describe("citation request failures", () => {
    it("preserves an expired reason returned by the business envelope", async () => {
        get.mockResolvedValueOnce({ status_code: 404, data: { reason: "expired" } });
        await expect(getCitationDetail("expired-envelope")).rejects.toMatchObject({ citationExpired: true, citationForbidden: false });
        expect(getCitationUnresolvedReason("expired-envelope")).toBe("expired");
    });
    it("preserves the forbidden reason from a rejected HTTP response", async () => {
        get.mockRejectedValueOnce({ response: { data: { status_code: 404, data: { reason: "forbidden" } } } });
        await expect(getCitationDetail("forbidden-response")).rejects.toMatchObject({ citationForbidden: true, citationExpired: false });
        expect(getCitationUnresolvedReason("forbidden-response")).toBe("forbidden");
    });
    it("preserves expired reasons on directly rejected business envelopes", async () => {
        get.mockRejectedValueOnce({ status_code: 404, data: { reason: "expired" } });
        await expect(getCitationDetail("expired-rejection")).rejects.toMatchObject({ citationExpired: true });
    });
    it("propagates transport errors unchanged", async () => {
        const error = new Error("connection lost");
        get.mockRejectedValueOnce(error);
        await expect(getCitationDetail("transport-error")).rejects.toBe(error);
    });
    it("returns successful citation details", async () => {
        const detail = { citationId: "success", type: "web", sourcePayload: { url: "https://example.com" } };
        get.mockResolvedValueOnce(detail);
        expect(await getCitationDetail("success")).toEqual(detail);
    });
    it.each([null, undefined, "failure", 404])("handles non-object errors: %s", value => {
        expect(readCitationFailure(value)).toEqual({});
    });
});
