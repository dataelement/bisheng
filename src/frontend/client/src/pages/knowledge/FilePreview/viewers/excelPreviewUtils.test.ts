import { formatExcelHeaderValue } from "./excelPreviewUtils";

describe("formatExcelHeaderValue", () => {
    it.each([undefined, null, ""])("keeps empty Excel headers blank", (value) => {
        expect(formatExcelHeaderValue(value)).toBe("");
    });

    it.each([
        [0, "0"],
        [false, "false"],
        ["Header", "Header"],
    ])("keeps non-empty Excel header values", (value, expected) => {
        expect(formatExcelHeaderValue(value)).toBe(expected);
    });
});
