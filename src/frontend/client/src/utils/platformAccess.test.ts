import {
  canOpenPlatformAdminPanel,
  canOpenWorkbench,
  canShowPlatformAdminEntry,
} from './platformAccess';

describe('canOpenPlatformAdminPanel', () => {
  it('returns false for a plain client user', () => {
    expect(
      canOpenPlatformAdminPanel({
        role: 'user',
        plugins: ['home', 'apps', 'subscription'],
      }),
    ).toBe(false);
  });

  it('returns false when the user only has platform child menu permissions', () => {
    expect(
      canOpenPlatformAdminPanel({
        role: 'user',
        plugins: ['home', 'knowledge'],
      }),
    ).toBe(false);
  });

  it('returns true when the user has the platform parent entry permission', () => {
    expect(
      canOpenPlatformAdminPanel({
        role: 'user',
        plugins: ['admin'],
      }),
    ).toBe(true);
  });

  it('returns true for department admins', () => {
    expect(
      canOpenPlatformAdminPanel({
        role: 'user',
        plugins: ['home'],
        is_department_admin: true,
      }),
    ).toBe(true);
  });
});

describe('canOpenWorkbench', () => {
  it('returns false when the user only has workbench child menu permissions', () => {
    expect(
      canOpenWorkbench({
        role: 'user',
        plugins: ['home', 'apps', 'subscription', 'knowledge_space'],
      }),
    ).toBe(false);
  });

  it('returns true when the user has the workbench parent entry permission', () => {
    expect(
      canOpenWorkbench({
        role: 'user',
        plugins: ['workstation'],
      }),
    ).toBe(true);
  });
});

describe('canShowPlatformAdminEntry', () => {
  it('returns true when the backend grants admin-console access to a tenant admin', () => {
    expect(
      canShowPlatformAdminEntry({
        role: '[110]',
        plugins: ['backend', 'workstation'],
        has_admin_console: true,
      }),
    ).toBe(true);
  });

  it('honors an explicit backend denial even when a legacy menu alias is present', () => {
    expect(
      canShowPlatformAdminEntry({
        role: 'user',
        plugins: ['backend'],
        has_admin_console: false,
      }),
    ).toBe(false);
  });

  it('does not treat the deprecated backend alias as an entry grant without an area flag', () => {
    expect(
      canShowPlatformAdminEntry({
        role: 'user',
        plugins: ['backend'],
      }),
    ).toBe(false);
  });

  it('falls back to the admin parent menu for legacy servers', () => {
    expect(
      canShowPlatformAdminEntry({
        role: 'user',
        plugins: ['admin'],
      }),
    ).toBe(true);
  });
});
