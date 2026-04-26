import { canOpenPlatformAdminPanel } from './platformAccess';

describe('canOpenPlatformAdminPanel', () => {
  it('returns false for a plain client user', () => {
    expect(
      canOpenPlatformAdminPanel({
        role: 'user',
        plugins: ['home', 'apps', 'subscription'],
      }),
    ).toBe(false);
  });

  it('returns true when the user has a concrete platform menu permission', () => {
    expect(
      canOpenPlatformAdminPanel({
        role: 'user',
        plugins: ['home', 'knowledge'],
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
