import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18next from "i18next";
import { cloneDeep } from "lodash-es";
import { getWorkflowNodeTemplate } from "@/controllers/API/workflow";
import { applySubflowInterface, findNodeParam } from "@/pages/BuildPage/flow/FlowNode/component/subflowParams";
import type { WorkflowNode } from "@/types/flow";
import { findInvalidRefItems, isVarInFlow } from "@/util/flowUtils";

const consumer = { id: "output_1", data: { name: "Output", group_params: [] } };

async function createSubflow(outputs = ["minutes"]) {
    const templates = await getWorkflowNodeTemplate();
    const template = templates.find(node => node.type === "subflow");
    if (!template) throw new Error("Missing subflow template");
    const data: WorkflowNode = cloneDeep(template);
    data.id = "subflow_1";
    const refresh = (names: string[]) => {
        const params = ["subflow_id", "subflow_inputs", "subflow_outputs"].map(key => {
            const param = findNodeParam(data, key);
            if (!param) throw new Error(`Missing parameter: ${key}`);
            return param;
        });
        applySubflowInterface(params[0], params[1], params[2], {
            id: "child_1",
            name: "Meeting minutes",
            inputs: [{ name: "meeting_text", value: "" }],
            outputs: names,
            eligible: true,
            ineligible_reasons: [],
        });
    };
    refresh(outputs);
    return { node: { id: data.id, data }, refresh };
}

describe("subflow return variable validation", () => {
    beforeEach(() => {
        vi.spyOn(i18next, "t").mockImplementation(() => "Invalid reference");
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("accepts the return value populated on the actual hidden template parameter", async () => {
        const { node } = await createSubflow();
        expect(findNodeParam(node.data, "subflow_outputs")).toMatchObject({
            type: "subflow_output", hidden: true, value: [{ key: "minutes" }],
        });
        expect(isVarInFlow(consumer.id, [node, consumer], "subflow_1.minutes", "Child/minutes")).toBe("");
    });

    it("rejects a renamed return value and accepts its replacement after refreshing the interface", async () => {
        const { node, refresh } = await createSubflow();
        refresh(["summary"]);
        expect(isVarInFlow(consumer.id, [node, consumer], "subflow_1.minutes", "Child/minutes")).toBe("Invalid reference");
        expect(isVarInFlow(consumer.id, [node, consumer], "subflow_1.summary", "Child/summary")).toBe("");
    });

    it("flags Code inputs and End return results that reference a renamed return value", async () => {
        const { node, refresh } = await createSubflow();
        const rows = [{ key: "text", type: "ref", label: "Child/minutes", value: "subflow_1.minutes" }];
        expect(findInvalidRefItems(consumer.id, [node, consumer], rows)).toEqual({ error: "", indexes: [] });
        refresh(["summary"]);
        expect(findInvalidRefItems(consumer.id, [node, consumer], rows)).toEqual({ error: "Invalid reference", indexes: [0] });
    });

    it("rejects a return value removed from the child interface", async () => {
        const { node, refresh } = await createSubflow();
        refresh([]);
        expect(isVarInFlow(consumer.id, [node, consumer], "subflow_1.minutes", "Child/minutes")).toBe("Invalid reference");
    });

    it.each(["subflow_1.missing", "deleted_child.minutes"])("rejects the missing reference %s", async reference => {
        const { node } = await createSubflow();
        expect(isVarInFlow(consumer.id, [node, consumer], reference, reference)).toBe("Invalid reference");
    });

    it.each(["meeting_text", "subflow_inputs", "subflow_outputs"])("keeps the hidden parameter %s unavailable", async key => {
        const { node } = await createSubflow();
        expect(isVarInFlow(consumer.id, [node, consumer], `subflow_1.${key}`, key)).toBe("Invalid reference");
    });

    it.each([
        { key: "code_output", type: "code_output", hidden: true, value: [{ key: "result" }], output: "result" },
        { key: "output", type: "var", value: [{ key: "result" }], output: "result" },
        { key: "output", type: "var", value: "", output: "output" },
    ])("preserves existing $type output validation", param => {
        const source = { id: "source_1", data: { group_params: [{ params: [param] }] } };
        expect(isVarInFlow(consumer.id, [source, consumer], `source_1.${param.output}`, param.output)).toBe("");
    });
});
