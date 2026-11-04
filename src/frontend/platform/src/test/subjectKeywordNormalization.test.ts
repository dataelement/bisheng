import { describe, expect, it } from "vitest";
import { normalizeSubjectKeyword } from "@/components/bs-comp/selectComponent/useSubjectSearch";

describe("subject keyword normalization", () => {
    it.each([9, 10, 11, 12, 13, 32, 133, 160, 5760, 8192, 8202, 8232, 8233, 8239, 8287, 12288])("trims boundary whitespace U+%s", code => {
        const whitespace = String.fromCodePoint(code);
        expect(normalizeSubjectKeyword(`${whitespace}team${whitespace}`)).toBe("team");
    });
    it("keeps internal whitespace while normalizing line breaks", () => {
        expect(normalizeSubjectKeyword("a\tb\r\nc\rd\ne")).toBe("a\tb c d e");
    });
});
