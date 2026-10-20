import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import { endReturnGroup, getWorkflowNodeTemplate } from "@/controllers/API/workflow";
import { flowVersionCompatible } from "@/util/flowCompatible";
import { applySubflowInterface, findNodeParam } from "@/pages/BuildPage/flow/FlowNode/component/subflowParams";
import { formatDuration, subflowNodeFields } from "@/pages/BuildPage/flow/FlowNode/SubflowRunLog";
import { subflowWarningLines } from "@/pages/BuildPage/flow/SubflowWarningDialog";
import { nodeLogData } from "@/pages/BuildPage/flow/FlowChat/nodeLogData";
import { raiseNodeLayer } from "@/pages/BuildPage/flow/FlowNode/nodeLayer";
import type { WorkflowNode, WorkflowNodeParam } from "@/types/flow";

// Echo translator: the key plus its interpolation values, so assertions see what was asked for.
const t = ((key: string, options?: Record<string, unknown>) => {
    if (!options) return key
    const values = Object.entries(options).filter(([k]) => k !== 'defaultValue')
    if (!values.length) return key
    return `${key}|${values.map(([k, v]) => `${k}=${v}`).join('|')}`
}) as unknown as TFunction

describe("F086 End node v2", () => {
    it("adds a switched-off return group to v1 End nodes, once", () => {
        const flow = flowVersionCompatible({ nodes: [{ data: { type: "end", v: "1", group_params: [] } }] })
        const node = flow.nodes[0].data
        expect(node.v).toBe(2)
        expect(node.group_params).toEqual([endReturnGroup()])
        expect(node.group_params[0].params[0]).toMatchObject({ key: "return_enabled", value: false, hidden: true })

        flowVersionCompatible(flow)
        expect(node.group_params).toHaveLength(1)
    })

    it("treats a missing version as v1", () => {
        const flow = flowVersionCompatible({ nodes: [{ data: { type: "end", group_params: undefined } }] })
        expect(flow.nodes[0].data.group_params).toEqual([endReturnGroup()])
    })

    it("ships End v2 and the subflow node in the templates", async () => {
        const templates = await getWorkflowNodeTemplate()
        const end = templates.find(one => one.type === "end")
        const subflow = templates.find(one => one.type === "subflow")
        expect(end.v).toBe("2")
        expect(end.group_params).toEqual([endReturnGroup()])
        const params = subflow.group_params.flatMap(group => group.params)
        expect(params.map(one => one.key)).toEqual(["subflow_id", "subflow_inputs", "subflow_outputs"])
        expect(params[2].global).toMatch(/^code:/)
    })
})

const subflowNode = (inputs: unknown[] = [], outputs: unknown[] = []): WorkflowNode => ({
    id: "subflow_1",
    name: "Call",
    description: "",
    type: "subflow",
    group_params: [{
        params: [
            { key: "subflow_id", type: "subflow_select", value: {} },
            { key: "subflow_inputs", type: "subflow_input", value: inputs },
            { key: "subflow_outputs", type: "subflow_output", value: outputs },
        ] as WorkflowNodeParam[],
    }],
})

describe("F086 subflow node params", () => {
    it("keeps configured rows by name and adds empty rows for new names", () => {
        const node = subflowNode([
            { key: "city", type: "ref", label: "Start/x", value: "start_1.x" },
            { key: "gone", type: "input", label: "", value: "old" },
        ], [{ key: "old" }])
        const param = (key: string) => {
            const found = findNodeParam(node, key)
            if (!found) throw new Error(`missing param ${key}`)
            return found
        }
        const [select, inputs, outputs] = ["subflow_id", "subflow_inputs", "subflow_outputs"].map(param)

        applySubflowInterface(select, inputs, outputs, {
            id: "f1",
            name: "Child",
            inputs: [{ name: "city", value: "SH" }, { name: "days", value: "3" }],
            outputs: ["answer"],
            eligible: true,
            ineligible_reasons: [],
        })

        expect(select.value).toEqual({ id: "f1", name: "Child" })
        expect(inputs.value).toEqual([
            { key: "city", type: "ref", label: "Start/x", value: "start_1.x" },
            { key: "days", type: "input", label: "", value: "" },
        ])
        expect(outputs.value).toEqual([{ key: "answer" }])
    })
})

describe("F086 save warning", () => {
    it("lists referrers, forbidden nodes and only the interface changes that happened", () => {
        const lines = subflowWarningLines({
            referenced_by: [{ id: "p1", name: "P1" }, { id: "p2", name: "P2" }],
            forbidden_nodes: [{ id: "input_1", name: "Ask", type: "input" }],
            interface_changes: { inputs_added: ["z"], inputs_removed: [], outputs_added: [], outputs_removed: ["a", "b"] },
        }, t)
        expect(lines).toEqual([
            "subflowWarning.referencedBy|names=P1subflowWarning.separatorP2",
            "subflowWarning.forbiddenNodes|names=Ask",
            "subflowWarning.inputs_added|names=z",
            "subflowWarning.outputs_removed|names=asubflowWarning.separatorb",
        ])
    })
})

describe("F086 nested run log", () => {
    it("shows the failure reason, inputs and every logged value", () => {
        const fields = subflowNodeFields({
            node_id: "code_1",
            name: "Code",
            type: "code",
            duration_ms: 12,
            reason: "boom",
            input_data: { "start_1.x": 1 },
            log_data: [[
                { key: "code_output", value: { r: 1 }, type: "params" },
                { key: "start_1.file", value: "u", type: "file" },
            ]],
        }, t)
        expect(fields).toEqual([
            { label: "subflowLog.reason", type: "text", value: "boom" },
            { label: "subflowLog.input", type: "text", value: { "start_1.x": 1 } },
            { label: "node.code.code_output.label", type: "params", value: { r: 1 } },
            { label: "file", type: "file", value: "u" },
        ])
    })

    it("marks rounds when a node ran more than once and skips empty parts", () => {
        const fields = subflowNodeFields({
            node_id: "llm_1", name: "LLM", type: "llm", duration_ms: 0, reason: null, input_data: {},
            log_data: [[{ key: "output", value: "a", type: "variable" }], [{ key: "output", value: "b", type: "variable" }]],
        }, t)
        expect(fields.map(one => one.label)).toEqual([
            "output (roundRunResult|index=1)",
            "output (roundRunResult|index=2)",
        ])
    })

    it("formats durations", () => {
        expect(formatDuration(850)).toBe("850ms")
        expect(formatDuration(1250)).toBe("1.3s")
    })
})

describe("F086 failed node log", () => {
    const reason = 'Subflow S failed at node code_c: boom -- subflow error --'
        + JSON.stringify({ status_code: 10560, status_message: "Subflow S failed", data: { subflow_name: "S", node_name: "code_c", reason: "boom" } })

    it("shows the localized subflow error, then what the node logged", () => {
        const inner = [{ node_id: "code_c", reason: "boom" }]
        expect(nodeLogData({
            reason,
            log_data: [[
                { key: "subflow_inputs", value: {}, type: "params" },
                { key: "subflow_logs", value: inner, type: "subflow_logs" },
            ]],
        }, t)).toEqual([[
            { key: "error", type: "params", value: "api_errors:10560|subflow_name=S|node_name=code_c|reason=boom" },
            { key: "subflow_inputs", value: {}, type: "params" },
            { key: "subflow_logs", value: inner, type: "subflow_logs" },
        ]])
    })

    it("keeps other reasons as they are, and passes success logs through", () => {
        expect(nodeLogData({ reason: "kaput", log_data: null }, t)).toEqual([[{ key: "error", type: "params", value: "kaput" }]])
        expect(nodeLogData({ reason: "x -- subflow error --{broken", log_data: null }, t)?.[0][0].value).toBe("x")
        const rounds = [[{ key: "output", value: "a", type: "variable" }]]
        expect(nodeLogData({ reason: null, log_data: rounds }, t)).toBe(rounds)
    })
})

describe("F086 node log layer", () => {
    const canvasNode = () => {
        const node = document.createElement("div")
        node.className = "react-flow__node"
        node.style.zIndex = "0"
        const popup = document.createElement("div")
        node.appendChild(popup)
        return { node, popup }
    }

    it("lifts the node holding an open log and puts it back on close", () => {
        const { node, popup } = canvasNode()
        const undo = raiseNodeLayer(popup)
        expect(node.style.zIndex).toBe("2000")
        undo()
        expect(node.style.zIndex).toBe("0")
    })

    it("keeps a z-index the canvas set meanwhile, and ignores elements outside a node", () => {
        const { node, popup } = canvasNode()
        const undo = raiseNodeLayer(popup)
        node.style.zIndex = "1000"
        undo()
        expect(node.style.zIndex).toBe("1000")
        expect(() => raiseNodeLayer(document.createElement("div"))()).not.toThrow()
        expect(() => raiseNodeLayer(null)()).not.toThrow()
    })
})
