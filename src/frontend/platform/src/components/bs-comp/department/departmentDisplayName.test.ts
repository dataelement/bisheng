import zh from '../../../../public/locales/zh-Hans/bs.json';
import { expect, it } from 'vitest';
import { departmentDisplayName } from './departmentDisplayName';

it('localizes only the seeded root name and preserves renamed or user-created departments', () => {
  expect(departmentDisplayName({ dept_id: 'BS@root', name: 'Default Org' }, zh.department.defaultOrganization)).toBe(zh.department.defaultOrganization);
  expect(departmentDisplayName({ dept_id: 'BS@root', name: zh.department.defaultOrganization }, 'Default Org')).toBe('Default Org');
  expect(departmentDisplayName({ dept_id: 'BS@root', name: 'Acme' }, zh.department.defaultOrganization)).toBe('Acme');
  expect(departmentDisplayName({ dept_id: 'custom', name: 'Default Org' }, zh.department.defaultOrganization)).toBe('Default Org');
});

import { departmentDisplayPath } from './departmentDisplayName';
it('localizes the root in full member paths without changing child or custom-root names', () => {
  const root = { dept_id: 'BS@root', name: 'Default Org' };
  expect(departmentDisplayPath('Default Org/Guests', root, zh.department.defaultOrganization)).toBe(`${zh.department.defaultOrganization}/Guests`);
  expect(departmentDisplayPath('Default Org / Guests', root, zh.department.defaultOrganization)).toBe(`${zh.department.defaultOrganization} / Guests`);
  expect(departmentDisplayPath('Default Org/Default Org', root, zh.department.defaultOrganization)).toBe(`${zh.department.defaultOrganization}/Default Org`);
  expect(departmentDisplayPath('Acme/Guests', { ...root, name: 'Acme' }, zh.department.defaultOrganization)).toBe('Acme/Guests');
  expect(departmentDisplayPath('Default Org/Guests', { ...root, dept_id: 'custom' }, zh.department.defaultOrganization)).toBe('Default Org/Guests');
  expect(departmentDisplayPath('Default Org/Guests', undefined, zh.department.defaultOrganization)).toBe('Default Org/Guests');
});
