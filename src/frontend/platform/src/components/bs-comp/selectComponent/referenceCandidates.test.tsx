import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useKnowledgeCandidates } from './useKnowledgeCandidates';
import KnowledgeSelect from './knowledge';
import KnowledgeSelectItem from '@/pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem';
import { Cascader } from '@bisheng/ui';
import { toModelCascaderOptions, toModelCascaderValue } from '@/components/bs-comp/formFields/modelOptions';
import * as api from '@/controllers/API/knowledgeSpace';
import { readFileLibDatabase } from '@/controllers/API';

const state = vi.hoisted(() => ({ tenant: 101, user: 'user:7', pin: 101, nodes: [] as unknown[], props: null as null | { value: Array<{value: string|number;label: string}>, options: Array<{value: string|number;label: string}>, onChange: (items: Array<{value: string|number;label: string}>) => void } }));
vi.mock('@/hooks/useKnowledgePageScope', () => ({ useKnowledgePageScope: () => ({ scopes: { ordinary: { identityKey: state.user, tenantId: state.tenant, managementTenantId: state.tenant, view: 'ordinary' } } }) }));
vi.mock('@/controllers/managementScope', () => ({ managementRequestScope: () => state.pin }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@/controllers/API/knowledgeSpace', () => ({ listVisibleSpaces: vi.fn() }));
vi.mock('@/controllers/API', () => ({ readFileLibDatabase: vi.fn() }));
vi.mock('@/components/bs-ui/select/multi', () => ({ default: (props: typeof state.props) => { state.props = props; return <div>picker</div>; } }));
vi.mock('@/pages/BuildPage/flow/flowStore', () => ({ default: () => ({ flow: { nodes: state.nodes } }) }));
vi.mock('@/util/flowUtils', () => ({ isVarInFlow: vi.fn() }));
const clients: QueryClient[] = [];
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={clients[clients.length - 1]}>{children}</QueryClientProvider>;
}
function pending<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { resolve, promise }; }
const page = (id: number, next_cursor: string | null = null) => ({ data: [{ id, name: `Space ${id}` }], page_size: 60, has_more: !!next_cursor, next_cursor });
beforeEach(() => {
  state.tenant = 101; state.pin = 101; state.user = 'user:7'; state.props = null;
  vi.clearAllMocks();
  clients.push(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  vi.mocked(api.listVisibleSpaces).mockResolvedValue(page(11));
  vi.mocked(readFileLibDatabase).mockResolvedValue(page(21));
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });
it('uses the visible SPACE cursor/search endpoint and consumes later pages', async () => {
  vi.mocked(api.listVisibleSpaces).mockResolvedValueOnce(page(11, 'next')).mockResolvedValueOnce(page(12)).mockResolvedValueOnce(page(13));
  const { result } = renderHook(() => useKnowledgeCandidates('space'), { wrapper });
  await waitFor(() => expect(result.current.options).toHaveLength(1));
  expect(api.listVisibleSpaces).toHaveBeenCalledWith({ cursor: null, page_size: 60, keyword: '' });
  act(() => result.current.loadMore());
  await waitFor(() => expect(result.current.options).toHaveLength(2));
  expect(api.listVisibleSpaces).toHaveBeenCalledWith({ cursor: 'next', page_size: 60, keyword: '' });
  act(() => result.current.search('visible only'));
  await waitFor(() => expect(result.current.options[0]?.value).toBe(13));
  expect(api.listVisibleSpaces).toHaveBeenCalledWith({ cursor: null, page_size: 60, keyword: 'visible only' });
});
it('keeps QA on its own type1 visible path', async () => {
  const { result } = renderHook(() => useKnowledgeCandidates('qa'), { wrapper });
  await waitFor(() => expect(result.current.options).toHaveLength(1));
  expect(readFileLibDatabase).toHaveBeenCalledWith({ cursor: null, pageSize: 60, name: '', type: 1, action: 'visible' });
  expect(api.listVisibleSpaces).not.toHaveBeenCalled();
});
it('a late response from the old user/tenant/pin is never displayed under the new identity', async () => {
  const first = pending<ReturnType<typeof page>>();
  vi.mocked(api.listVisibleSpaces).mockReturnValueOnce(first.promise).mockResolvedValueOnce(page(22));
  const { result, rerender } = renderHook(() => useKnowledgeCandidates('space'), { wrapper });
  await waitFor(() => expect(api.listVisibleSpaces).toHaveBeenCalledOnce());
  state.tenant = 202; state.pin = 202; state.user = 'user:8'; rerender();
  await waitFor(() => expect(result.current.options[0]?.value).toBe(22));
  await act(async () => first.resolve(page(11)));
  expect(result.current.options.map(item => item.value)).toEqual([22]);
});
it('the actual assistant selector never removes saved unknown ids or changes their types when options load', async () => {
  const onChange = vi.fn();
  const old = [{ value: '00099', label: 'historical', type: 'file' }, { value: 20, label: 'other historical', type: 'space' }];
  render(<KnowledgeSelect type="file" enableSpace multiple value={old} onChange={onChange} />, { wrapper });
  await waitFor(() => expect(state.props!.options).toEqual([expect.objectContaining({ value: '11' })]));
  expect(onChange).not.toHaveBeenCalled();
  act(() => state.props!.onChange([state.props!.value[0], { value: '11', label: 'Space 11' }]));
  expect(onChange).toHaveBeenCalledWith([old[0], { value: 11, label: 'Space 11', type: 'space' }]);
});
it('workflow legacy mode is not rewritten on load; removing one slot keeps all other bytes', async () => {
  const onChange = vi.fn(); const onVarEvent = vi.fn();
  const old = { type: 'knowledge', extra: 'keep', value: [{ key: '00099', label: 'old' }, { key: 20, label: 'other' }] };
  render(<KnowledgeSelectItem data={{ value: old }} nodeId="node" onChange={onChange} onValidate={vi.fn()} onVarEvent={onVarEvent} i18nPrefix="test." />, { wrapper });
  await screen.findByText('picker');
  expect(onChange).not.toHaveBeenCalled();
  act(() => state.props!.onChange([state.props!.value[0]]));
  expect(onChange).toHaveBeenCalledWith({ ...old, value: [old.value[0]] });
  expect(onVarEvent.mock.calls.at(-1)?.[0]()).toBe('');
});

it('the actual Cascader displays a saved unknown model without offering it as a new choice', () => {
  const changed = vi.fn();
  render(<Cascader options={toModelCascaderOptions([], '000999', 'Unavailable')} value={toModelCascaderValue('000999', [], true)} onChange={changed} />);
  expect(screen.getByText('Unavailable: 000999')).toBeVisible();
  expect(changed).not.toHaveBeenCalled();
});
