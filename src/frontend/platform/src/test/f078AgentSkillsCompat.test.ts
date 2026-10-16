import { describe, expect, it } from "vitest";
import { flowVersionCompatible } from "@/util/flowCompatible";

interface Param {
    key: string;
    type?: string;
    value: unknown;
}

interface Group {
    name?: string;
    params: Param[];
}

interface FlowNode {
    data: { type: string; v: string | number; tab: { value: string }; group_params: Group[] };
}

// A v2 agent node as saved before F078: no skills group, no deliverables output.
const v2AgentNode = (tab: "single" | "batch"): FlowNode => ({
    data: {
        type: "agent",
        v: "2",
        tab: { value: tab },
        group_params: [
            { params: [{ key: "batch_variable", value: [] }] },
            { name: "model", params: [{ key: "model_id", value: "" }] },
            { name: "prompt", params: [{ key: "system_prompt", value: "" }] },
            { name: "tools", params: [{ key: "tool_list", value: [] }] },
            {
                name: "output",
                params: [
                    { key: "output_user", value: true },
                    {
                        key: "output",
                        value: tab === "batch" ? [{ key: "output_start_1_a", label: "output_a" }] : [],
                    },
                ],
            },
        ],
    },
});

const paramKeys = (node: FlowNode) => node.data.group_params.map((g) => g.params.map((p) => p.key));

const deliverablesOf = (node: FlowNode) => {
    const outputs = node.data.group_params.find((g) => g.params.some((p) => p.key === "output"));
    return outputs?.params.find((p) => p.key === "output_deliverables");
};

describe("F078 agent node v2 -> v3", () => {
    it("adds the skills group before the tools group", () => {
        const flow = flowVersionCompatible({ nodes: [v2AgentNode("single")] });
        const groups = paramKeys(flow.nodes[0]);
        const skillsIndex = groups.findIndex((keys) => keys.includes("skill_list"));
        const toolsIndex = groups.findIndex((keys) => keys.includes("tool_list"));
        expect(skillsIndex).toBeGreaterThan(-1);
        expect(skillsIndex).toBe(toolsIndex - 1);
        expect(groups[skillsIndex]).toEqual(["skill_list", "input_files"]);
        expect(flow.nodes[0].data.v).toBe(3);
    });

    it("adds the deliverables output, empty in single mode", () => {
        const flow = flowVersionCompatible({ nodes: [v2AgentNode("single")] });
        const deliverables = deliverablesOf(flow.nodes[0]);
        expect(deliverables?.type).toBe("var");
        expect(deliverables?.value).toEqual([]);
    });

    it("derives one deliverables variable per batch output", () => {
        const flow = flowVersionCompatible({ nodes: [v2AgentNode("batch")] });
        const deliverables = deliverablesOf(flow.nodes[0]);
        expect(deliverables?.value).toEqual([{ key: "output_start_1_a_deliverables", label: "output_a_deliverables" }]);
    });

    it("is idempotent for a node that already has the params", () => {
        const flow = flowVersionCompatible({ nodes: [v2AgentNode("single")] });
        flow.nodes[0].data.v = 2;
        const again = flowVersionCompatible(flow);
        const all = paramKeys(again.nodes[0]).flat();
        expect(all.filter((k) => k === "skill_list")).toHaveLength(1);
        expect(all.filter((k) => k === "output_deliverables")).toHaveLength(1);
    });
});
