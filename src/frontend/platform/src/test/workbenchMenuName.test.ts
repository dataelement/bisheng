import i18next from 'i18next';
import { beforeAll, describe, expect, it } from 'vitest';
import zhHans from '../../public/locales/zh-Hans/bs.json';
import enUS from '../../public/locales/en-US/bs.json';
import ja from '../../public/locales/ja/bs.json';
import { toStoredMenuName } from '@/pages/BuildPage/bench/menuDisplayName';

// Resources are bundled here instead of fetched, so loadLanguages() resolves immediately.
beforeAll(async () => {
    await i18next.init({
        lng: 'en-US',
        ns: ['bs'],
        defaultNS: 'bs',
        resources: { 'zh-Hans': { bs: zhHans }, 'en-US': { bs: enUS }, ja: { bs: ja } },
    });
});

describe('toStoredMenuName', () => {
    it('stores blank as blank', async () => {
        expect(await toStoredMenuName('   ', 'bench.home')).toBe('');
    });

    it('treats the default name of any language as blank', async () => {
        expect(await toStoredMenuName(zhHans.bench.home, 'bench.home')).toBe('');
        expect(await toStoredMenuName(enUS.bench.appCenter, 'bench.appCenter')).toBe('');
        expect(await toStoredMenuName(ja.bench.subscribe, 'bench.subscribe')).toBe('');
    });

    it('ignores case and spacing when comparing with the default', async () => {
        // en-US default is "KnowledgeSpace"; the client's own copy is "Knowledge Space"
        expect(await toStoredMenuName(' knowledge space ', 'bench.knowledgeSpace')).toBe('');
    });

    it('keeps a custom name, trimmed', async () => {
        expect(await toStoredMenuName('  Workspace ', 'bench.home')).toBe('Workspace');
    });

    it('only compares against the same module default', async () => {
        // "Apps" is the app-center default, so it is a real custom name for home
        expect(await toStoredMenuName(enUS.bench.appCenter, 'bench.home')).toBe(enUS.bench.appCenter);
    });
});
