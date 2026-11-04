import { readDesktopLocale, rememberDesktopLocale, subscribeDesktopLocale } from './desktopLocale';

beforeEach(() => {
  window.history.replaceState({}, '', '/workspace/');
  window.sessionStorage.clear();
  window.localStorage.clear();
  delete window.dshChatPresentation;
  delete document.documentElement.dataset.dshHostLocale;
});

function nativeEntry() {
  window.dshChatPresentation = { reportLanding: jest.fn() };
  window.history.replaceState({}, '', '/workspace/?embed=dsh&dshLocale=zh');
}

it('reads the initial host language and retains it across router redirects and document reloads', () => {
  nativeEntry();
  expect(readDesktopLocale()).toBe('zh-Hans');
  rememberDesktopLocale('zh');
  window.history.replaceState({}, '', '/workspace/knowledge');
  delete document.documentElement.dataset.dshHostLocale;
  expect(readDesktopLocale()).toBe('zh-Hans');
  expect(window.localStorage.length).toBe(0);
});

it('lets live host state override a stale query parameter and releases the event listener', () => {
  nativeEntry();
  const listener = jest.fn();
  const unsubscribe = subscribeDesktopLocale(listener);
  window.dispatchEvent(new CustomEvent('dsh:locale', { detail: { locale: 'en' } }));
  expect(readDesktopLocale()).toBe('en');
  expect(document.documentElement.lang).toBe('en');
  expect(new URLSearchParams(window.location.search).get('dshLocale')).toBe('en');
  expect(listener).toHaveBeenCalledTimes(1);
  for (const detail of [null, 'zh', { locale: 'ja' }, { locale: {} }]) {
    window.dispatchEvent(new CustomEvent('dsh:locale', { detail }));
  }
  expect(listener).toHaveBeenCalledTimes(1);
  unsubscribe();
  window.dispatchEvent(new CustomEvent('dsh:locale', { detail: { locale: 'zh' } }));
  expect(listener).toHaveBeenCalledTimes(1);
  expect(readDesktopLocale()).toBe('en');
});

it('ignores query parameters, stale session state and host events in a standalone browser', () => {
  window.history.replaceState({}, '', '/workspace/?embed=dsh&dshLocale=zh');
  window.sessionStorage.setItem('dsh:host-locale', 'zh');
  const listener = jest.fn();
  const unsubscribe = subscribeDesktopLocale(listener);
  rememberDesktopLocale('en');
  window.dispatchEvent(new CustomEvent('dsh:locale', { detail: { locale: 'zh' } }));
  expect(readDesktopLocale()).toBeUndefined();
  expect(document.documentElement.dataset.dshHostLocale).toBeUndefined();
  expect(listener).not.toHaveBeenCalled();
  unsubscribe();
});
