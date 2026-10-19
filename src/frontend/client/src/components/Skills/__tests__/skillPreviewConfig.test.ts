describe('Skill Center deployment config', () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const originalBuildFlag = process.env.VITE_SKILL_CENTER_PREVIEW;

  afterEach(() => {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else Reflect.deleteProperty(globalThis, 'window');
    if (originalBuildFlag === undefined) delete process.env.VITE_SKILL_CENTER_PREVIEW;
    else process.env.VITE_SKILL_CENTER_PREVIEW = originalBuildFlag;
    jest.resetModules();
  });

  it.each([
    ['enables a generic build for the preview deployment', true, undefined, true],
    ['honors an explicit runtime disable', false, 'true', false],
    ['retains build-time opt-in for other deployments', undefined, 'true', true],
    ['defaults to disabled without either opt-in', undefined, undefined, false],
  ])('%s', async (_name, runtimeFlag, buildFlag, expected) => {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { APP_CONFIG: { skillCenterPreviewEnabled: runtimeFlag } },
    });
    if (buildFlag === undefined) delete process.env.VITE_SKILL_CENTER_PREVIEW;
    else process.env.VITE_SKILL_CENTER_PREVIEW = buildFlag;

    const { skillCenterPreviewEnabled } = await import('../types');
    expect(skillCenterPreviewEnabled).toBe(expected);
  });

  it('supports file and persistence code in a Node environment', async () => {
    Reflect.deleteProperty(globalThis, 'window');
    delete process.env.VITE_SKILL_CENTER_PREVIEW;
    const { skillCenterPreviewEnabled } = await import('../types');
    expect(skillCenterPreviewEnabled).toBe(false);
  });
});
