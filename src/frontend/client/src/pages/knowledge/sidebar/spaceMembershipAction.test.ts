import { getSpaceMembershipAction } from './spaceMembershipAction';

test('joined administrators leave rather than deleting the shared space', () => {
  expect(getSpaceMembershipAction('joined', true)).toBe('leave');
  expect(getSpaceMembershipAction('joined', false)).toBe('leave');
});

test('deletion remains available for non-joined spaces with delete permission', () => {
  expect(getSpaceMembershipAction('created', true)).toBe('delete');
  expect(getSpaceMembershipAction('department', true)).toBe('delete');
  expect(getSpaceMembershipAction('created', false)).toBe(null);
  expect(getSpaceMembershipAction('department', false)).toBe(null);
});
