export function getSpaceMembershipAction(
  type: 'created' | 'joined' | 'department',
  canDeleteSpace: boolean,
): 'delete' | 'leave' | null {
  // Membership intent takes precedence over elevated administration permissions.
  return type === 'joined' ? 'leave' : canDeleteSpace ? 'delete' : null;
}
