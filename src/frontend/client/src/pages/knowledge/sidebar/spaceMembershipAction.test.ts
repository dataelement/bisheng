import { getSpaceDetailMembershipAction, getSpaceMembershipAction } from './spaceMembershipAction';

test('joined administrators leave rather than deleting the shared space', () => {
  expect(getSpaceMembershipAction('joined', true)).toBe('leave');
  expect(getSpaceMembershipAction('joined', false)).toBe('leave');
});
test('detail actions keep joined admins on leave even when deletion is permitted', () => {
  expect(getSpaceDetailMembershipAction({ role: 'admin', spaceKind: 'normal' }, true)).toBe('leave');
  expect(getSpaceDetailMembershipAction({ role: 'member', spaceKind: 'normal' }, false)).toBe('leave');
  expect(getSpaceDetailMembershipAction({ role: 'creator', spaceKind: 'normal' }, true)).toBe('delete');
  expect(getSpaceDetailMembershipAction({ role: 'admin', spaceKind: 'department' }, true)).toBe('delete');
  expect(getSpaceDetailMembershipAction({ role: 'member', spaceKind: 'department' }, false)).toBe(null);
});

test('deletion remains available for non-joined spaces with delete permission', () => {
  expect(getSpaceMembershipAction('created', true)).toBe('delete');
  expect(getSpaceMembershipAction('department', true)).toBe('delete');
  expect(getSpaceMembershipAction('created', false)).toBe(null);
  expect(getSpaceMembershipAction('department', false)).toBe(null);
});
