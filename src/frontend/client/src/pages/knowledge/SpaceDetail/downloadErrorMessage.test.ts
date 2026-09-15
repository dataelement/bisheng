/**
 * A refused download must say so, not blame the network.
 *
 * The download button is now offered on every reviewed file and the server
 * decides, so "you may not download this" is a normal answer rather than a bug.
 * It arrives as business code 19000, which already has a translation. Showing
 * the generic "download failed" for it would send the user looking for a
 * connection problem they do not have.
 */

/** Stand-ins for the real copy: this is about which message is chosen, not what it says. */
const mockRefusalCopy = "translated-refusal";
const FALLBACK = "generic-download-failed";

jest.mock("~/api/request", () => ({
    translateApiErrorMessage: (data: { status_code?: number }) =>
        data?.status_code === 19000 ? mockRefusalCopy : "",
}));

import { resolveDownloadErrorMessage } from "./downloadErrorMessage";


test("a refusal shows the server's wording", () => {
    const error = Object.assign(new Error("request failed"), {
        status_code: 19000,
        status_message: "Permission denied",
    });

    expect(resolveDownloadErrorMessage(error, FALLBACK)).toBe(mockRefusalCopy);
});

test("a refusal carried on the response is read too", () => {
    const error = Object.assign(new Error("request failed"), {
        response: { data: { status_code: 19000, status_message: "Permission denied" } },
    });

    expect(resolveDownloadErrorMessage(error, FALLBACK)).toBe(mockRefusalCopy);
});

test("a network failure keeps the generic wording", () => {
    expect(resolveDownloadErrorMessage(new Error("Network Error"), FALLBACK)).toBe(FALLBACK);
});

test("an untranslated business code keeps the generic wording", () => {
    const error = Object.assign(new Error("request failed"), { status_code: 12345 });

    expect(resolveDownloadErrorMessage(error, FALLBACK)).toBe(FALLBACK);
});

test("a thrown non-error does not crash the toast", () => {
    expect(resolveDownloadErrorMessage(undefined, FALLBACK)).toBe(FALLBACK);
    expect(resolveDownloadErrorMessage("boom", FALLBACK)).toBe(FALLBACK);
});
