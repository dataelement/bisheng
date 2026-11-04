import { normalizeApiError } from '@bisheng/api-client';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import * as api from '@/controllers/API/approval';
import { getRolesApi } from '@/controllers/API/user';
import { showApiError } from '@/controllers/request';
import { notification } from '@bisheng/ui';
import { useApprovalController } from './useApprovalController';

vi.mock('@/controllers/API/user', () => ({ getRolesApi: vi.fn().mockResolvedValue({ data: [] }) }));
vi.mock('@/controllers/API/approval', () => ({
    listApprovalScenarioPresetsApi: vi.fn(), listApprovalScenariosApi: vi.fn(),
    listApprovalExceptionsApi: vi.fn(), createApprovalScenarioApi: vi.fn(),
    listApprovalRoutesApi: vi.fn(), listApprovalFlowsApi: vi.fn(), listApprovalNodesApi: vi.fn(),
}));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@bisheng/ui', () => ({ notification: { open: vi.fn() } }));
beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getRolesApi).mockResolvedValue({ data: [] });
    vi.mocked(api.listApprovalScenarioPresetsApi).mockResolvedValue([]);
    vi.mocked(api.listApprovalScenariosApi).mockResolvedValue([]);
    vi.mocked(api.listApprovalExceptionsApi).mockResolvedValue([]);
});

it.each(['routes', 'flows', 'nodes'] as const)('keeps scenario A intact when scenario B %s fail after another read succeeds', async (failedRead) => {
    const scenarios = [
        { id: 1, scenario_code: 'a', scenario_name: 'A' },
        { id: 2, scenario_code: 'b', scenario_name: 'B' },
    ];
    const routesA = [{ id: 11, route_name: 'Route A', route_type: 'pass' }];
    const flowsA = [{ id: 12, flow_code: 'a', flow_name: 'Flow A', is_active: true }];
    const nodesA = [{ id: 13, node_code: 'a', node_name: 'Node A', node_order: 1, node_mode: 'or', approver_config: {} }];
    vi.mocked(api.listApprovalScenariosApi).mockResolvedValue(scenarios);
    vi.mocked(api.listApprovalRoutesApi).mockResolvedValueOnce(routesA);
    vi.mocked(api.listApprovalFlowsApi).mockResolvedValueOnce(flowsA);
    vi.mocked(api.listApprovalNodesApi).mockResolvedValueOnce(nodesA);
    const { result } = renderHook(useApprovalController);
    await waitFor(() => expect(result.current.nodes).toEqual(nodesA));
    act(() => result.current.enterNodeEditMode());
    act(() => result.current.setIsNodeDirty(true));

    const error = new Error(`B ${failedRead} unavailable`);
    vi.mocked(api.listApprovalRoutesApi).mockImplementationOnce(async () => {
        if (failedRead === 'routes') throw error;
        return [{ id: 21, route_name: 'Route B', route_type: 'pass' }];
    });
    vi.mocked(api.listApprovalFlowsApi).mockImplementationOnce(async () => {
        if (failedRead === 'flows') throw error;
        return [{ id: 22, flow_code: 'b', flow_name: 'Flow B', is_active: true }];
    });
    vi.mocked(api.listApprovalNodesApi).mockImplementationOnce(async () => {
        if (failedRead === 'nodes') throw error;
        return [{ ...nodesA[0], id: 23, node_name: 'Node B' }];
    });
    await act(async () => {
        await expect(result.current.selectScenario(2)).rejects.toBe(error);
    });
    expect(result.current.selectedScenarioId).toBe(1);
    expect(result.current.routes).toEqual(routesA);
    expect(result.current.flows).toEqual(flowsA);
    expect(result.current.selectedFlowId).toBe(12);
    expect(result.current.nodes).toEqual(nodesA);
    expect(result.current.draftNodes).toEqual(nodesA);
    expect(result.current.isNodeEditMode).toBe(true);
    expect(result.current.isNodeDirty).toBe(true);
    expect(result.current.loadError).toBe(error);

    const routesB = [{ id: 21, route_name: 'Route B', route_type: 'pass' }];
    const flowsB = [{ id: 22, flow_code: 'b', flow_name: 'Flow B', is_active: true }];
    const nodesB = [{ ...nodesA[0], id: 23, node_name: 'Node B' }];
    vi.mocked(api.listApprovalRoutesApi).mockResolvedValue(routesB);
    vi.mocked(api.listApprovalFlowsApi).mockResolvedValue(flowsB);
    vi.mocked(api.listApprovalNodesApi).mockResolvedValue(nodesB);
    await act(() => result.current.selectScenario(2));
    expect(result.current.selectedScenarioId).toBe(2);
    expect(result.current.routes).toEqual(routesB);
    expect(result.current.flows).toEqual(flowsB);
    expect(result.current.nodes).toEqual(nodesB);
    expect(result.current.draftNodes).toEqual([]);
    expect(result.current.isNodeEditMode).toBe(false);
    expect(result.current.isNodeDirty).toBe(false);
    expect(result.current.loadError).toBe(null);
});
afterEach(cleanup);

it('terminates an initial load rejection at the page effect with the original error', async () => {
    const error = normalizeApiError(new Error('Load failed'), { message: 'Load failed' });
    vi.mocked(api.listApprovalScenariosApi).mockRejectedValueOnce(error);
    const { result } = renderHook(useApprovalController);
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
    expect(result.current.loadError).toBe(error);
    await act(() => result.current.loadPage());
    expect(result.current.loadError).toBe(null);
    expect(notification.open).not.toHaveBeenCalled();
});

it('keeps a failed scenario creation open and delegates error presentation without a second generic notice', async () => {
    const error = normalizeApiError(new Error('Create failed'), { message: 'Create failed' });
    error.presentation = 'toast';
    vi.mocked(api.createApprovalScenarioApi).mockRejectedValueOnce(error);
    const { result } = renderHook(useApprovalController);
    await waitFor(() => expect(api.listApprovalScenariosApi).toHaveBeenCalledOnce());
    act(() => result.current.setShowAddScenario(true));
    await act(() => result.current.handleAddScenario({ scenario_code: 'menu', scenario_name: 'Menu' }));
    expect(result.current.showAddScenario).toBe(true);
    expect(notification.open).not.toHaveBeenCalled();
    expect(showApiError).toHaveBeenCalledWith(error);
    expect(api.listApprovalScenariosApi).toHaveBeenCalledTimes(1);
});
