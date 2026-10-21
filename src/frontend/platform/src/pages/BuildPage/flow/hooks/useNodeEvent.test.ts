import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useNodeEvent } from './useNodeEvent'

function node(id: string, type: string) {
    return { id, type: 'flowNode', data: { id, name: type, type, description: '', group_params: [] } }
}
function graph() {
    return { nodes: [node('start_1', 'start'), node('end_1', 'end')], edges: [{ source: 'start_1', target: 'end_1' }] }
}
afterEach(cleanup)
it('accepts a connected start-to-end graph after field validation passes', async () => {
    const { result } = renderHook(() => useNodeEvent(graph()))
    await expect(result.current()).resolves.toEqual([])
})
it('waits for registered field validators and removes them when nodes unregister', async () => {
    const { result } = renderHook(() => useNodeEvent(graph()))
    act(() => window.dispatchEvent(new CustomEvent('node_event', { detail: { action: 'update', id: 'field', validate: async () => ['Required input'] } })))
    await expect(result.current()).resolves.toEqual(['Required input'])
    act(() => window.dispatchEvent(new CustomEvent('node_event', { detail: { action: 'delete', id: 'field' } })))
    await expect(result.current()).resolves.toEqual([])
})
it('marks disconnected nodes before allowing execution', async () => {
    const flow = graph(); flow.nodes.push(node('llm_1', 'llm'))
    const listener = vi.fn()
    window.addEventListener('nodeErrorBorderEvent', listener)
    try {
        const { result } = renderHook(() => useNodeEvent(flow))
        await expect(result.current()).resolves.toEqual(['unconnectedNodes'])
        expect((listener.mock.calls[0][0] as CustomEvent).detail.nodeIds).toEqual(['llm_1'])
    } finally { window.removeEventListener('nodeErrorBorderEvent', listener) }
})
it('rejects a graph without an outgoing start connection', async () => {
    const flow = graph(); flow.edges = []
    const { result } = renderHook(() => useNodeEvent(flow))
    await expect(result.current()).resolves.toEqual(['missingEndNode'])
})
