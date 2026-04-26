import { canOpenPlatformAdminPanel, canOpenWorkbench } from './platformAccess';

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
