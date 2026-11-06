import type { i18n as I18n } from 'i18next';
import translationZh from './zh-Hans/translation.json';

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  localStorage.setItem('i18nextLng', 'en');
  localStorage.setItem('lang', JSON.stringify('en'));
  window.history.replaceState({}, '', '/workspace/');
  delete window.dshChatPresentation;
  delete document.documentElement.dataset.dshHostLocale;
});

afterEach(() => { delete window.dshChatPresentation; });

function initialize(): I18n {
  let instance: I18n | undefined;
  jest.isolateModules(() => { instance = jest.requireActual('./i18n').default; });
  if (!instance) throw new Error('i18n did not initialize');
  return instance;
}

it('initializes native pages from the host and never caches that override as a web preference', async () => {
  window.dshChatPresentation = { reportLanding: jest.fn() };
  window.history.replaceState({}, '', '/workspace/?embed=dsh&dshLocale=zh');
  const instance = initialize();
  jest.isolateModules(() => { jest.requireActual('../store/language'); });
  expect(instance.language).toBe('zh-Hans');
  expect(instance.t('com_knowledge.knowledge_space')).toBe(translationZh.com_knowledge.knowledge_space);
  await instance.changeLanguage('en');
  await instance.changeLanguage('zh-Hans');
  expect(localStorage.getItem('i18nextLng')).toBe('en');
  expect(localStorage.getItem('lang')).toBe('"en"');
  // A hard reload after a router redirect has no entry parameters left.
  window.history.replaceState({}, '', '/workspace/knowledge');
  delete document.documentElement.dataset.dshHostLocale;
  expect(initialize().language).toBe('zh-Hans');
});

it('restores the standalone web language even with desktop-looking query parameters', async () => {
  window.history.replaceState({}, '', '/workspace/?embed=dsh&dshLocale=zh');
  const instance = initialize();
  expect(instance.language).toBe('en');
  await instance.changeLanguage('zh-Hans');
  expect(localStorage.getItem('i18nextLng')).toBe('zh-Hans');
  expect(initialize().language).toBe('zh-Hans');
});
