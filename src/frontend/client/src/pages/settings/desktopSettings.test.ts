import { readDesktopSettingsSection } from './desktopSettings';

afterEach(() => { delete window.dshChatPresentation; window.sessionStorage.clear(); window.history.replaceState({}, '', '/'); });
it('requires native embedding and the explicit content-mode marker', () => {
  window.history.replaceState({}, '', '/?embed=dsh');
  expect(readDesktopSettingsSection('account', '?dshSettings=1')).toBeUndefined();
  window.dshChatPresentation = { reportLanding: jest.fn() };
  expect(readDesktopSettingsSection('account', '')).toBeUndefined();
  expect(readDesktopSettingsSection('account', '?dshSettings=1')).toBe('account');
  expect(readDesktopSettingsSection('desktop-usage', '?dshSettings=1')).toBe('desktop-usage');
  for (const section of ['general', '../admin', 'https://other.example/', '', undefined]) {
    expect(readDesktopSettingsSection(section, '?dshSettings=1')).toBeUndefined();
  }
});
it('does not change standalone settings when only a content-mode marker is present', () => {
  window.dshChatPresentation = { reportLanding: jest.fn() };
  expect(readDesktopSettingsSection('account', '?dshSettings=1')).toBeUndefined();
});
it.each(['account', 'desktop-usage', 'ai-access', 'my-tasks', 'my-requests', 'notifications'])(
  'accepts %s with host language and theme parameters', (section) => {
    window.history.replaceState({}, '', '/workspace/settings/' + section + '?embed=dsh');
    window.dshChatPresentation = { reportLanding: jest.fn() };
    expect(readDesktopSettingsSection(section, '?dshLocale=en&dshSettings=1&embed=dsh&dshTheme=dark')).toBe(section);
    expect(readDesktopSettingsSection(section, '?dshSettings=0&embed=dsh')).toBeUndefined();
  },
);
