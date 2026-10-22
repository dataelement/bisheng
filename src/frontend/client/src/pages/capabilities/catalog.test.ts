import { capabilityCounts, filterCapabilities } from './catalog';
import type { Capability } from '~/api/capabilities';
const item = (id: string, kind: Capability['kind'], ready: boolean, name: string): Capability => ({
  id, resource_id: 1, kind, ready, name, description: 'Enterprise capability', provider: 'BISHENG', demo: false,
  trial: null, invocation_name: `runtime-${id}`,
});
const items = [item('1', 'skill', true, 'Order review'), item('2', 'api', true, 'Order query'), item('3', 'mcp', false, 'Inventory')];
test('each category shows its own available capabilities', () => {
  expect(filterCapabilities(items, 'api', '', true).map(row => row.id)).toEqual(['2']);
  expect(filterCapabilities(items, 'mcp', '', true)).toEqual([]);
  expect(filterCapabilities(items, 'mcp', '', false).map(row => row.id)).toEqual(['3']);
});
test('search and availability filters compose', () => {
  expect(filterCapabilities(items, 'all', 'ORDER', true)).toHaveLength(2);
  expect(filterCapabilities(items, 'skill', 'query', false)).toEqual([]);
});
test('counts describe the visible catalog', () => {
  expect(capabilityCounts(items)).toEqual({ all: 3, skill: 1, api: 1, mcp: 1, builtin: 0 });
});
