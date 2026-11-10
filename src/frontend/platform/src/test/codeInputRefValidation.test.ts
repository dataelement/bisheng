import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18next from "i18next";
import { findInvalidRefItems } from "@/util/flowUtils";

const source = {
    id: "code_src",
    data: {
        name: "Source",
        group_params: [{ params: [{ key: "code_output", type: "code_output", value: [{ key: "result", type: "str" }] }] }],
    },
};
const start = {
    id: "start_1",
    data: {
        name: "Start",
        group_params: [{ params: [{ key: "custom_variables", type: "global_var", value: [{ key: "k1", label: "city", value: "" }] }] }],
    },
};
const consumer = { id: "code_dst", data: { name: "Consumer", group_params: [] } };
const nodes = [source, start, consumer];

describe("code input reference validation", () => {
    beforeEach(() => {
        vi.spyOn(i18next, "t").mockImplementation(() => "Invalid reference");
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("accepts references that still exist", () => {
        const items = [
            { key: "a", type: "ref", label: "Source/result", value: "code_src.result" },
            { key: "b", type: "ref", label: "Start/city", value: "start_1.custom_variables#k1" },
        ];
        expect(findInvalidRefItems(consumer.id, nodes, items)).toEqual({ error: "", indexes: [] });
    });

    it("flags a reference whose output was renamed and points at its row", () => {
        const items = [
            { key: "a", type: "ref", label: "Start/city", value: "start_1.custom_variables#k1" },
            { key: "b", type: "ref", label: "Source/old_name", value: "code_src.old_name" },
        ];
        expect(findInvalidRefItems(consumer.id, nodes, items)).toEqual({ error: "Invalid reference", indexes: [1] });
    });

    it("flags a reference to a deleted node", () => {
        const items = [{ key: "a", type: "ref", label: "Gone/x", value: "code_gone.x" }];
        expect(findInvalidRefItems(consumer.id, nodes, items).indexes).toEqual([0]);
    });

    it("ignores literal inputs and unset references", () => {
        const items = [
            { key: "a", type: "input", label: "", value: "code_gone.x" },
            { key: "b", type: "ref", label: "", value: "" },
        ];
        expect(findInvalidRefItems(consumer.id, nodes, items)).toEqual({ error: "", indexes: [] });
        expect(findInvalidRefItems(consumer.id, nodes, undefined)).toEqual({ error: "", indexes: [] });
    });
});
