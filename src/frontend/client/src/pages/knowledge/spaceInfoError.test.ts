import { resolveSpaceInfoFailure } from "./spaceInfoError";

jest.mock("~/api/request", () => ({
    translateApiErrorMessage: (source: { status_message?: string }) => source?.status_message ?? "",
}));

describe("what a failed space-detail load means", () => {
    it("sends the user away only when the space is really gone", () => {
        expect(resolveSpaceInfoFailure({ status_code: 18000 })).toMatchObject({
            leaveSpace: true,
            messageKey: "com_knowledge.space_invalid_or_deleted",
        });
    });

    it("sends the user away when the space is closed to them", () => {
        expect(resolveSpaceInfoFailure({ status_code: 18040 })).toMatchObject({ leaveSpace: true });
    });

    it("keeps the user in place when a disabled Catalog action breaks the call", () => {
        // 25001 is what the server answered for every space once upload_file was
        // switched off. Bouncing on it told users their spaces were deleted.
        const failure = resolveSpaceInfoFailure({
            status_code: 25001,
            status_message: "Action upload_file is unavailable for knowledge_space",
        });

        expect(failure.leaveSpace).toBe(false);
        expect(failure.messageKey).toBe("com_knowledge.space_load_failed");
        expect(failure.message).toBe("Action upload_file is unavailable for knowledge_space");
    });

    it("keeps the user in place when there is no business code at all", () => {
        expect(resolveSpaceInfoFailure(new Error("network down"))).toMatchObject({
            leaveSpace: false,
            messageKey: "com_knowledge.space_load_failed",
        });
    });

    it("reads the code out of an interceptor-wrapped response too", () => {
        expect(resolveSpaceInfoFailure({ response: { data: { status_code: 18000 } } })).toMatchObject({
            leaveSpace: true,
        });
    });
});
