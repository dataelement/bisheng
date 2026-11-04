import { workbenchBranding } from './workbenchBranding';
import type { BsConfig } from '~/types/chat';

it('resolves defaults and configured sources through the same presentation', () => {
  const originalBase = __APP_ENV__.BASE_URL;
  __APP_ENV__.BASE_URL = '/workspace';
  expect(workbenchBranding(undefined, 'Welcome')).toEqual({ welcomeMessage: 'Welcome', assistantIcon: { enabled: true, image: 'http://localhost:3080/workspace/assets/bisheng/logo-mark.svg' } });
  const config = { welcomeMessage: '  Team  ', assistantIcon: { enabled: false, image: 'https://files.example/logo.svg' } } as BsConfig;
  expect(workbenchBranding(config, 'Welcome')).toEqual({ welcomeMessage: 'Team', assistantIcon: { enabled: false, image: 'https://files.example/logo.svg' } });
  __APP_ENV__.BASE_URL = originalBase;
});
