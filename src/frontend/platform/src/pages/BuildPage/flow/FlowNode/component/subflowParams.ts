import type { SubflowInterface } from "@/controllers/API/workflow";
import type { WorkflowNode, WorkflowNodeParam } from "@/types/flow";

/** One input parameter row of a subflow node; same shape as a Code node input. */
export interface SubflowInputRow {
    key: string
    type: string
    label: string
    value: string
}

export function findNodeParam(node: WorkflowNode, key: string): WorkflowNodeParam | undefined {
    return node.group_params.flatMap(group => group.params).find(param => param.key === key)
}

/**
 * Rebuild a subflow node's params from the subflow's current interface.
 * Rows for names that still exist keep what the editor configured; new names get
 * an empty "input" row, which the engine treats as "use the subflow's own value".
 */
export function applySubflowInterface(
    selectParam: WorkflowNodeParam,
    inputsParam: WorkflowNodeParam,
    outputsParam: WorkflowNodeParam,
    info: SubflowInterface,
): void {
    const previous: SubflowInputRow[] = inputsParam.value || []
    selectParam.value = { id: info.id, name: info.name }
    inputsParam.value = info.inputs.map(input =>
        previous.find(row => row.key === input.name) || { key: input.name, type: 'input', label: '', value: '' })
    outputsParam.value = info.outputs.map(name => ({ key: name }))
}
