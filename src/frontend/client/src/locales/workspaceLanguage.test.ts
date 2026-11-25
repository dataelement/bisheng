import Cookies from 'js-cookie';
import { readWorkspaceLanguage, saveWorkspaceLanguage } from './workspaceLanguage';

const initialConfig = window.APP_CONFIG;

afterEach(() => {
  window.localStorage.removeItem('lang');
  window.localStorage.removeItem('i18nextLng');
  Cookies.remove('lang', { path: '/' });
  window.APP_CONFIG = initialConfig;
});

it('restores the workspace choice ahead of a stale shared cookie', () => {
  Cookies.set('lang', 'zh-Hans');
  window.localStorage.setItem('lang', JSON.stringify('en'));

  expect(readWorkspaceLanguage()).toBe('en');
});

it('keeps a newly selected language when the shared cookie is used on reload', () => {
  saveWorkspaceLanguage('en');
  window.localStorage.removeItem('lang');

  expect(readWorkspaceLanguage()).toBe('en');
});

it('honors the deployment policy when restoring a previously saved Japanese selection', () => {
  window.APP_CONFIG = { ...initialConfig, disableJa: true };
  window.localStorage.setItem('lang', JSON.stringify('ja'));
  Cookies.set('lang', 'en-US');

  expect(readWorkspaceLanguage()).toBe('en');
});
