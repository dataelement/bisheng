import {
  APPROVER_SOURCE_LABEL_KEYS,
  APPROVER_SOURCE_OPTION_VALUES,
  FIXED_ROLE_VALUES,
  approverSourceLabel,
  offerableApproverSources,
  selectableRoleValues,
} from '@/pages/ApprovalPage/approverSources';
import { describe, expect, it } from 'vitest';

// Stand-in for i18next: resolves a key when the map knows it, otherwise honours
// the caller's defaultValue exactly like `t()` does for a missing key.
const KNOWN_LABELS: Record<string, string> = {
  'approvalPage.approverSource.direct_user': 'Specified User',
  'approvalPage.approverSource.department_admin': 'Applicant Dept Admin',
  'approvalPage.approverSource.tenant_admin': 'Tenant Admin',
  'approvalPage.approverSource.tenant_admin_single': 'Platform Admin',
  'approvalPage.approverSource.channel_owner': 'Channel Owner',
};
const t = (key: string, opts?: Record<string, string>) =>
  KNOWN_LABELS[key] ?? opts?.defaultValue ?? key;

describe('approver source labels', () => {
  it('covers every source type the backend resolver can emit', () => {
    // Mirrors approver_resolver.py — a value missing here renders as a bare enum
    // code in the approver chips, which is the bug this list exists to prevent.
    const backendSourceTypes = [
      'direct_user',
      'department_admin',
      'tenant_admin',
      'knowledge_space_owner',
      'knowledge_space_manager',
      'space_admin',
      'channel_admin',
      'channel_owner',
      'channel_manager',
    ];
    for (const type of backendSourceTypes) {
      expect(APPROVER_SOURCE_LABEL_KEYS[type]).toBe(`approvalPage.approverSource.${type}`);
    }
  });

  it('labels a seeded tenant_admin rather than leaking the enum code', () => {
    expect(approverSourceLabel('tenant_admin', t)).toBe('Tenant Admin');
  });

  it('labels every selectable option', () => {
    for (const value of APPROVER_SOURCE_OPTION_VALUES) {
      expect(APPROVER_SOURCE_LABEL_KEYS[value]).toBeDefined();
    }
  });

  it('falls back to the persisted label, then to the raw value', () => {
    expect(approverSourceLabel('future_source', t, 'Persisted Label')).toBe('Persisted Label');
    expect(approverSourceLabel('future_source', t)).toBe('future_source');
    expect(approverSourceLabel('future_source', t, '')).toBe('future_source');
  });
});

// What the backend seeds for the app-publish scenario (approval_registry.py).
const APP_PUBLISH_ALLOWED = ['department_admin', 'tenant_admin', 'direct_user'];

describe('offerableApproverSources', () => {
  it('lets a multi-tenant admin add tenant_admin back to the app-publish flow', () => {
    // The reason T046 exists: the preset declares tenant_admin, so intersecting
    // the preset list with the picker list must not drop it.
    expect(offerableApproverSources(APP_PUBLISH_ALLOWED)).toEqual([
      'direct_user',
      'department_admin',
      'tenant_admin',
    ]);
  });

  it('never offers a source the preset cannot resolve', () => {
    // A source outside the preset's allow-list would resolve to nobody, so it
    // must stay out of the picker even though the vocabulary knows it.
    expect(offerableApproverSources(APP_PUBLISH_ALLOWED)).not.toContain('channel_owner');
  });

  it('does not narrow anything when no scenario preset is selected', () => {
    expect(offerableApproverSources()).toEqual(APPROVER_SOURCE_OPTION_VALUES);
  });

  it('leaves scenarios that never mention tenant_admin untouched', () => {
    const channelAllowed = ['direct_user', 'department_admin', 'channel_owner', 'channel_manager'];
    expect(offerableApproverSources(channelAllowed)).toEqual([
      'direct_user',
      'department_admin',
      'channel_owner',
      'channel_manager',
    ]);
    expect(offerableApproverSources(channelAllowed)).toEqual([
      'direct_user',
      'department_admin',
      'channel_owner',
      'channel_manager',
    ]);
  });
});

describe('selectableRoleValues', () => {
  it('offers tenant_admin as an applicant identity when multi-tenancy is on', () => {
    expect(selectableRoleValues(true).map((v) => v.value)).toEqual([
      'admin',
      'tenant_admin',
      'dept_admin',
    ]);
  });

  it('hides tenant_admin as an applicant identity on a single-tenant deployment', () => {
    expect(selectableRoleValues(false).map((v) => v.value)).toEqual(['admin', 'dept_admin']);
  });

  it('leaves the display list intact so saved routes still render their label', () => {
    expect(FIXED_ROLE_VALUES.map((v) => v.value)).toContain('tenant_admin');
  });
});
