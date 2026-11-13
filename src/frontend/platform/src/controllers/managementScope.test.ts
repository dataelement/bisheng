import { expect, it } from 'vitest';
import { requiresManagementScope } from './managementScope';

it.each([
  ['PATCH', '/api/v1/guest-link/workflow/flow-a'],
  ['PATCH', '/api/v1/guest-link/assistant/assistant-a'],
  ['POST', '/api/v1/knowledge/space/3/uploads'],
  ['POST', '/api/v1/knowledge/space/3/uploads/upload-a/previews'],
  ['PUT', '/api/v1/knowledge/space/3/uploads/upload-a/previews/preview-a/chunks/0'],
  ['DELETE', '/api/v1/knowledge/space/3/uploads/upload-a/previews/preview-a/chunks/0'],
])('pins phase-one management write %s %s', (method, path) => {
  expect(requiresManagementScope(method, path)).toBe(true);
});

it('preserves shared temporary uploads and independent public execution', () => {
  expect(requiresManagementScope('POST', '/api/v1/knowledge/upload')).toBe(false);
  expect(requiresManagementScope('POST', '/api/v1/public/workflow/flow-a/run')).toBe(false);
  expect(requiresManagementScope('GET', '/api/v1/guest-link/workflow/flow-a')).toBe(true);
});
