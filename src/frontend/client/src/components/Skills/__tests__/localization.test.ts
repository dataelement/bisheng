import { createInstance } from 'i18next';
import { resources } from '~/locales/i18n';
import { localizeSkill, matchesSkillSearch } from '../localization';
import type { PlatformSkill } from '../types';

const keys = ['bisheng-docx', 'bisheng-pptx', 'bisheng-xlsx'] as const;
function builtin(key: typeof keys[number]): PlatformSkill {
  const copy = resources['zh-Hans'].translation.com_builtin_skills[key];
  return { id: `platform:${key}`, resourceId: 7, name: key, builtinKey: key,
    displayName: copy.name, description: copy.description, source: 'platform', enabled: false };
}
async function language(lng: string) {
  const instance = createInstance();
  await instance.init({ lng, resources, fallbackLng: 'en' });
  return instance;
}

describe.each(['en', 'zh-Hans', 'ja'] as const)('%s builtin skills', lng => {
  test.each(keys)('%s localizes display copy and preserves execution identity', async key => {
    const i18n = await language(lng);
    const source = builtin(key);
    const localized = localizeSkill(source, i18n.t.bind(i18n));
    const copy = resources[lng].translation.com_builtin_skills[key];
    expect(localized).toMatchObject({ ...source, displayName: copy.name, description: copy.description });
    expect(source.displayName).toBe(resources['zh-Hans'].translation.com_builtin_skills[key].name);
    for (const query of [copy.name.toUpperCase(), copy.description, source.displayName, source.description, key]) {
      expect(matchesSkillSearch(localized, query)).toBe(true);
    }
    expect(matchesSkillSearch(localized, 'unrelated query')).toBe(false);
  });
});

test('language changes use original catalog data', async () => {
  const i18n = await language('en');
  const source = builtin('bisheng-docx');
  expect(localizeSkill(source, i18n.t.bind(i18n)).displayName).toBe('Word document creation');
  await i18n.changeLanguage('zh-Hans');
  expect(localizeSkill(source, i18n.t.bind(i18n)).displayName).toBe(source.displayName);
});

test.each([undefined, null, 'future-skill'])('custom, older and unknown entries keep configured copy (%s)', async builtinKey => {
  const i18n = await language('en');
  const source = { ...builtin('bisheng-docx'), builtinKey, displayName: 'Tenant template', description: 'Tenant instructions' };
  expect(localizeSkill(source, i18n.t.bind(i18n))).toMatchObject(source);
});
