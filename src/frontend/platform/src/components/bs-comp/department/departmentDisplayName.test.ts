import zh from '../../../../public/locales/zh-Hans/bs.json';
import { expect, it } from 'vitest';
import { departmentDisplayName } from './departmentDisplayName';

it('localizes only the seeded root name and preserves renamed or user-created departments', () => {
  expect(departmentDisplayName({ dept_id: 'BS@root', name: 'Default Org' }, zh.department.defaultOrganization)).toBe(zh.department.defaultOrganization);
  expect(departmentDisplayName({ dept_id: 'BS@root', name: zh.department.defaultOrganization }, 'Default Org')).toBe('Default Org');
  expect(departmentDisplayName({ dept_id: 'BS@root', name: 'Acme' }, zh.department.defaultOrganization)).toBe('Acme');
  expect(departmentDisplayName({ dept_id: 'custom', name: 'Default Org' }, zh.department.defaultOrganization)).toBe('Default Org');
});
