import { test } from '@playwright/test';

test.describe('G-M5 release smoke', () => {
  test.skip(!process.env.E2E_POINTS_RUN_GATES, 'Set E2E_POINTS_RUN_GATES=1 before release');
  test('placeholder — full smoke + reconcile + enabled=false', async () => {});
});
