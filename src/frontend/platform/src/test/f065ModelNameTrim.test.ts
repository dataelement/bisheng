import { describe, expect, it } from "vitest";

import {
    hasDuplicateModelName,
    hasInvalidModelName,
    trimModelNames,
} from "@/pages/ModelPage/manage/modelNameTrim";

describe("trimModelNames", () => {
    it("strips leading and trailing whitespace from every model_name", () => {
        const models = trimModelNames([
            { id: 1, model_name: "  gpt-4  " },
            { id: 2, model_name: "\tembed-v1\n" },
        ]);
        expect(models.map((model) => model.model_name)).toEqual(["gpt-4", "embed-v1"]);
    });

    it("keeps internal spaces", () => {
        expect(trimModelNames([{ model_name: " gpt 4 " }])[0].model_name).toBe("gpt 4");
    });

    it("turns whitespace-only names into an empty string", () => {
        expect(trimModelNames([{ model_name: "   \t  " }])[0].model_name).toBe("");
    });
});

describe("hasInvalidModelName", () => {
    it("rejects empty names after trim", () => {
        expect(hasInvalidModelName(trimModelNames([{ model_name: "   " }]))).toBe(true);
    });

    it("rejects names longer than 100 characters", () => {
        expect(hasInvalidModelName([{ model_name: "a".repeat(101) }])).toBe(true);
    });

    it("accepts a non-empty name within 100 characters", () => {
        expect(hasInvalidModelName([{ model_name: "gpt-4" }])).toBe(false);
    });
});

describe("hasDuplicateModelName", () => {
    it("detects duplicates only after trimming", () => {
        const models = trimModelNames([
            { model_name: "gpt-4" },
            { model_name: " gpt-4 " },
        ]);
        expect(hasDuplicateModelName(models)).toBe(true);
    });

    it("allows the same name across distinct values", () => {
        expect(
            hasDuplicateModelName([
                { model_name: "gpt-4" },
                { model_name: "gpt-4o" },
            ]),
        ).toBe(false);
    });
});
