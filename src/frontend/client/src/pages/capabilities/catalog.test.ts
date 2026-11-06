import { createInstance } from 'i18next';
import { resources } from '~/locales/i18n';
import { capabilityCounts, filterCapabilities, localizeCapability } from './catalog';
import type { Capability } from '~/api/capabilities';
const item = (id: string, kind: Capability['kind'], ready: boolean, name: string): Capability => ({
  id, resource_id: 1, kind, ready, name, description: 'Enterprise capability', provider: 'BISHENG', demo: false,
  trial: null, invocation_name: `runtime-${id}`,
});
const items = [item('1', 'skill', true, 'Order review'), item('2', 'api', true, 'Order query'), item('3', 'mcp', false, 'Inventory')];
test('each category shows its own available capabilities', () => {
  expect(filterCapabilities(items, 'tool', '', true).map(row => row.id)).toEqual(['2']);
  expect(filterCapabilities(items, 'tool', 'Inventory', true)).toEqual([]);
  expect(filterCapabilities(items, 'tool', 'Inventory', false).map(row => row.id)).toEqual(['3']);
});
test('search and availability filters compose', () => {
  expect(filterCapabilities(items, 'all', 'ORDER', true)).toHaveLength(2);
  expect(filterCapabilities(items, 'skill', 'query', false)).toEqual([]);
});
test('counts describe the visible catalog', () => {
  expect(capabilityCounts(items)).toEqual({ all: 3, skill: 1, tool: 2 });
});

const englishTools = resources.en.tool;
const chineseTools = resources['zh-Hans'].tool;
const companyKey = 'tianyancha_get_company_baseinfo';
const provider = Object.entries(englishTools.categories).find(([, value]) => value.name === 'Tianyancha')?.[0] ?? '';
const company: Capability = {
  ...item('company', 'builtin', true, chineseTools.tools[companyKey].name),
  tool_key: companyKey, provider, description: chineseTools.tools[companyKey].desc,
};

async function language(lng: string) {
  const instance = createInstance();
  await instance.init({ lng, resources, defaultNS: 'translation', fallbackLng: 'en' });
  return instance;
}

test.each(['en', 'zh-Hans', 'ja'] as const)('builtin display fields use the shared %s tool dictionary', async lng => {
  const i18n = await language(lng);
  const localized = localizeCapability(company, i18n.t.bind(i18n));
  expect(localized).toMatchObject({
    name: resources[lng].tool.tools[companyKey].name,
    description: resources[lng].tool.tools[companyKey].desc,
    provider: Object.entries(resources[lng].tool.categories).find(([key]) => key === provider)?.[1].name,
    resource_id: company.resource_id,
    invocation_name: company.invocation_name,
  });
  expect(company.name).toBe(chineseTools.tools[companyKey].name);
});

test('search matches displayed names, descriptions, providers, original copy and stable identifiers', async () => {
  const i18n = await language('en');
  const localized = localizeCapability(company, i18n.t.bind(i18n));
  for (const query of ['COMPANY BASIC', 'legal rep.', 'Tianyancha', company.name, companyKey, company.invocation_name]) {
    expect(filterCapabilities([localized], 'tool', query, false).map(row => row.id)).toEqual([company.id]);
  }
  expect(filterCapabilities([localized], 'tool', 'unrelated', false)).toEqual([]);
});

test('language switching immediately updates display and searchable copy', async () => {
  const i18n = await language('en');
  const translate = i18n.t.bind(i18n);
  expect(localizeCapability(company, translate).name).toBe(englishTools.tools[companyKey].name);
  await i18n.changeLanguage('zh-Hans');
  const localized = localizeCapability(company, translate);
  expect(localized.name).toBe(company.name);
  expect(filterCapabilities([localized], 'tool', company.name, false)).toHaveLength(1);
});

test.each(['api', 'mcp', 'skill'] as const)('%s preserves configured copy even when its key matches a builtin', async kind => {
  const i18n = await language('en');
  const custom = { ...company, kind, name: 'Custom company lookup', description: 'Custom instructions' };
  expect(localizeCapability(custom, i18n.t.bind(i18n))).toMatchObject(custom);
});

test('unknown tools and older catalog responses retain readable server copy', async () => {
  const i18n = await language('en');
  for (const tool_key of [undefined, null, 'future_tool']) {
    const unknown = { ...company, tool_key, provider: 'Future provider' };
    expect(localizeCapability(unknown, i18n.t.bind(i18n))).toMatchObject(unknown);
  }
});

test('time uses the existing tool translation for title and description', async () => {
  const i18n = await language('en');
  const time: Capability = { ...company, tool_key: 'get_current_time', trial: { scenario: 'time', arguments: {} } };
  expect(localizeCapability(time, i18n.t.bind(i18n))).toMatchObject({
    name: englishTools.tools.get_current_time.name,
    description: englishTools.tools.get_current_time.desc,
  });
});


test.each(['en', 'zh-Hans', 'ja'] as const)('knowledge search reuses the existing %s category translation', async lng => {
  const i18n = await language(lng);
  const knowledge: Capability = { ...company, tool_key: 'bisheng_knowledge_search' };
  const categoryKey = Object.entries(englishTools.categories).find(([, value]) => value.name === 'Knowledge base search')?.[0];
  const copy = Object.entries(resources[lng].tool.categories).find(([key]) => key === categoryKey)?.[1];
  expect(localizeCapability(knowledge, i18n.t.bind(i18n))).toMatchObject({ name: copy?.name, description: copy?.desc });
});
