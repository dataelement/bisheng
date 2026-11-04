export function getSpaceMembershipAction(
  type: 'created' | 'joined' | 'department',
  canDeleteSpace: boolean,
): 'delete' | 'leave' | null {
  // Membership intent takes precedence over elevated administration permissions.
  return type === 'joined' ? 'leave' : canDeleteSpace ? 'delete' : null;
}

export function getSpaceDetailMembershipAction(
  space: { role?: 'creator' | 'admin' | 'member'; spaceKind?: 'normal' | 'department' },
  canDeleteSpace: boolean,
): 'delete' | 'leave' | null {
  if (!space.role) return null;
  const type = space.spaceKind === 'department' ? 'department' : space.role === 'creator' ? 'created' : 'joined';
  return getSpaceMembershipAction(type, canDeleteSpace);
}
