/**
 * A business error the user is meant to read must come from `api_errors`.
 *
 * Unsubscribing from a granted channel answers 19015, whose copy exists in all
 * three languages — and the toast said "API request failed (19015)". Both the
 * channel and the knowledge-space pages built the message by hand from the
 * response fields and never consulted the catalogue, so any code without a
 * hard-coded client-side string showed as that placeholder.
 */

import { translateApiErrorMessage } from "~/api/request";
import { createApiStatusError, extractApiErrorMessage, extractApiStatusCode } from "./apiStatusError";

jest.mock("~/api/request", () => ({
    translateApiErrorMessage: jest.fn(),
}));

const translate = translateApiErrorMessage as unknown as jest.Mock;

/** What the interceptor hands a caller for a business error. */
const grantedChannelResponse = {
    status_code: 19015,
    status_message: "This channel is open to you through a permission grant and cannot be unsubscribed",
    data: { exception: "This channel is open to you through a permission grant and cannot be unsubscribed" },
};

beforeEach(() => {
    translate.mockReset();
});

describe("createApiStatusError", () => {
    it("uses the translated api_errors copy, not the placeholder", () => {
        translate.mockReturnValue("<granted channel copy>");

        const error = createApiStatusError(grantedChannelResponse);

        expect(error.message).toBe("<granted channel copy>");
        expect(error.statusCode).toBe(19015);
    });

    it("passes the code and message the catalogue needs to resolve the copy", () => {
        translate.mockReturnValue("x");

        createApiStatusError(grantedChannelResponse);

        expect(translateApiErrorMessage).toHaveBeenCalledWith(
            expect.objectContaining({
                status_code: 19015,
                status_message: grantedChannelResponse.status_message,
            }),
        );
    });

    it("falls back to the placeholder only when nothing can be resolved", () => {
        translate.mockReturnValue("");

        expect(createApiStatusError({ status_code: 18080 }).message).toBe("API request failed (18080)");
        expect(createApiStatusError({}).message).toBe("API request failed");
    });

    it("reads a code out of an axios-shaped error too", () => {
        translate.mockReturnValue("");

        const error = createApiStatusError({ response: { data: { status_code: 18080 } } });

        expect(error.statusCode).toBe(18080);
    });
});

describe("extractApiErrorMessage", () => {
    it("prefers the catalogue over a raw Error message", () => {
        translate.mockReturnValue("<granted space copy>");

        const thrown = Object.assign(new Error("Request failed with status code 500"), {
            status_code: 18080,
        });

        expect(extractApiErrorMessage(thrown)).toBe("<granted space copy>");
    });

    it("keeps the Error message when the catalogue has nothing", () => {
        translate.mockReturnValue("");

        expect(extractApiErrorMessage(new Error("boom"))).toBe("boom");
    });
});

describe("extractApiStatusCode", () => {
    it.each([
        [{ status_code: 19015 }, 19015],
        [{ data: { status_code: 18080 } }, 18080],
        [{ response: { data: { code: "19014" } } }, 19014],
        [null, null],
        [{}, null],
    ])("reads %p as %p", (input, expected) => {
        expect(extractApiStatusCode(input)).toBe(expected);
    });
});
