// Approver-source and applicant-identity vocabularies for the approval scenario
// config page.
//
// Two lists, deliberately kept apart:
//
//   * the *label* maps answer "what does this stored value mean" and must cover
//     every value the backend can emit (see approver_resolver.py). Nothing is
//     ever removed from them — a chip rendering a bare enum code is a bug;
//   * the *selectable* lists answer "what may an administrator newly pick" and
//     are narrowed per deployment.
//
// Conflating the two is what made `tenant_admin` render as raw `tenant_admin`
// while also being impossible to re-add through the UI.

/** i18n key per approver source type — the single source of truth for display. */
export const APPROVER_SOURCE_LABEL_KEYS: Record<string, string> = {
  direct_user: 'approvalPage.approverSource.direct_user',
  department_admin: 'approvalPage.approverSource.department_admin',
  tenant_admin: 'approvalPage.approverSource.tenant_admin',
  channel_admin: 'approvalPage.approverSource.channel_admin',
  channel_owner: 'approvalPage.approverSource.channel_owner',
  channel_manager: 'approvalPage.approverSource.channel_manager',
  space_admin: 'approvalPage.approverSource.space_admin',
  knowledge_space_owner: 'approvalPage.approverSource.knowledge_space_owner',
  knowledge_space_manager: 'approvalPage.approverSource.knowledge_space_manager',
};

export type TFn = (key: string, opts?: Record<string, string>) => string;

/**
 * Labels that name a different real-world role on a single-tenant deployment.
 *
 * `tenant_admin` is the only entry today: the seeded "app publish" flow stores
 * it, but a single-tenant install is the Root tenant, where tenant admins
 * cannot be granted at all (error 19204) and the source resolves to the
 * platform super admins instead (approver_resolver.py). Showing "Tenant Admin"
 * there names a role the deployment does not have, and names the wrong people.
 *
 * This is a display substitution only — the stored value stays `tenant_admin`,
 * so one seed serves both deployment shapes and flipping the switch needs no
 * migration.
 */
const SINGLE_TENANT_LABEL_KEYS: Record<string, string> = {
  tenant_admin: 'approvalPage.approverSource.tenant_admin_single',
};

/**
 * Display label for an approver source type. Falls back to the caller-supplied
 * label (what was persisted alongside the value) and finally to the raw value,
 * so an unknown future source degrades to something readable instead of blank.
 */
export function approverSourceLabel(
  type: string,
  t: TFn,
  fallback?: string,
  multiTenantEnabled = true,
): string {
  const key =
    (!multiTenantEnabled && SINGLE_TENANT_LABEL_KEYS[type]) ||
    APPROVER_SOURCE_LABEL_KEYS[type] ||
    `approvalPage.approverSource.${type}`;
  // The persisted label came from a multi-tenant vocabulary, so it must not win
  // over a substitution we made on purpose.
  const defaultValue = !multiTenantEnabled && SINGLE_TENANT_LABEL_KEYS[type] ? type : fallback || type;
  return t(key, { defaultValue });
}

/**
 * Fixed applicant-identity values for the `applicant_role` condition, on top of
 * the system roles loaded from the API. Display-side list: a route saved while
 * multi-tenancy was on keeps rendering its label after the deployment switches
 * to single-tenant.
 */
export const FIXED_ROLE_VALUES = [
  { value: 'admin', label: 'approvalPage.roleValue.admin' },
  { value: 'tenant_admin', label: 'approvalPage.roleValue.tenant_admin' },
  { value: 'dept_admin', label: 'approvalPage.roleValue.dept_admin' },
];

/**
 * Applicant-identity values that can never match on a single-tenant deployment.
 *
 * `applicant_role: tenant_admin` is decided by an OpenFGA `admin` relation on
 * the tenant, which Root refuses to grant (error 19204) — so on a single-tenant
 * install *nobody* carries this identity and a route conditioned on it is dead.
 *
 * Note this is the opposite of the approver-*source* case: a source resolves
 * through `approver_resolver`, which deliberately falls back to the platform
 * super admins on Root, so there the value stays meaningful and only its label
 * changes (SINGLE_TENANT_LABEL_KEYS). Same enum value, two different questions —
 * "who is the applicant" vs "who should approve".
 */
export const SINGLE_TENANT_DEAD_ROLE_VALUES = new Set(['tenant_admin']);

/** Applicant-identity values a route may newly be pointed at. */
export function selectableRoleValues(multiTenantEnabled: boolean) {
  return multiTenantEnabled
    ? FIXED_ROLE_VALUES
    : FIXED_ROLE_VALUES.filter((v) => !SINGLE_TENANT_DEAD_ROLE_VALUES.has(v.value));
}

/**
 * Approver sources an administrator may newly add, ordered to match how the
 * backend seeds presets (approval_registry.py).
 */
export const APPROVER_SOURCE_OPTION_VALUES = [
  'direct_user',
  'department_admin',
  'tenant_admin',
  'knowledge_space_owner',
  'knowledge_space_manager',
  'channel_owner',
  'channel_manager',
];

/**
 * What the node editor's "add approver" dropdown offers.
 *
 * **Deployment shape does not narrow this list** (T046). `tenant_admin` in
 * particular stays offerable on a single-tenant install: it is the only source
 * that reaches the platform super admins — `approver_resolver` falls back to
 * them on Root — so hiding it would delete the capability rather than remove
 * noise, leaving an administrator to name each platform admin by hand through
 * `direct_user`. Single-tenant changes the *label*, not the availability
 * (SINGLE_TENANT_LABEL_KEYS).
 *
 * The only narrowing is the scenario preset's declared allow-list, which is
 * authoritative about what this scenario can resolve at all — a source outside
 * it would resolve to nobody, so it must not be offered even if some older
 * config saved it.
 *
 * `allowedTypes` undefined means "no preset selected — do not narrow".
 */
export function offerableApproverSources(allowedTypes?: string[]): string[] {
  if (!allowedTypes) return APPROVER_SOURCE_OPTION_VALUES;
  return APPROVER_SOURCE_OPTION_VALUES.filter((v) => allowedTypes.includes(v));
}
