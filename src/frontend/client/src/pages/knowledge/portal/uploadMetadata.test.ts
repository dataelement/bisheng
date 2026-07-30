import { resolveFileBusinessDomainCode } from "./uploadMetadata";

describe("resolveFileBusinessDomainCode", () => {
    it("prefers draft, then API field, then parsed file_encoding", () => {
        expect(resolveFileBusinessDomainCode(
            { businessDomainCode: "EM", fileEncoding: "SGGF-STD-PP-20260600000001" },
            { businessDomainCode: "FI" },
        )).toBe("FI");

        expect(resolveFileBusinessDomainCode(
            { businessDomainCode: "EM", fileEncoding: null },
        )).toBe("EM");

        expect(resolveFileBusinessDomainCode(
            { businessDomainCode: null, fileEncoding: "SGGF-STD-PP-20260600000001" },
        )).toBe("PP");
    });
});
