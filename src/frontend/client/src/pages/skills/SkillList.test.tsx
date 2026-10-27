import { render, screen } from '@testing-library/react';
import type { SkillRecord } from '~/components/Skills/types';
import { SkillList } from './SkillList';

function skill(partial: Pick<SkillRecord, 'id' | 'displayName' | 'updatedAt'>): SkillRecord {
  return {
    name: partial.displayName,
    description: 'Description',
    source: 'personal',
    enabled: true,
    contentHash: 'hash',
    bundleMissing: false,
    preview: '',
    files: [],
    ...partial,
  };
}

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => {
  const icons = new Proxy({}, { get: () => () => null });
  return { Outlined: icons, Filled: icons, Colored: icons };
});
jest.mock('~/mock/demo/DemoTag', () => ({ DemoTag: () => null }));

const rows = [
  skill({ id: 1, displayName: 'Zebra', updatedAt: '2026-03-01T00:00:00' }),
  skill({ id: 2, displayName: 'Alpha', updatedAt: '2026-01-01T00:00:00' }),
  skill({ id: 3, displayName: 'Middle', updatedAt: '2026-02-01T00:00:00' }),
];

function names() {
  return screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent);
}

it('lists the newest update first', () => {
  render(<SkillList skills={rows} sort="recent" onSelect={() => undefined} onToggle={() => undefined} />);
  expect(names()).toEqual(['Zebra', 'Middle', 'Alpha']);
});

it('lists names in alphabetical order', () => {
  render(<SkillList skills={rows} sort="name" onSelect={() => undefined} onToggle={() => undefined} />);
  expect(names()).toEqual(['Alpha', 'Middle', 'Zebra']);
});

it('keeps the later row first when two updates share a time', () => {
  const tied = [
    skill({ id: 4, displayName: 'Older id', updatedAt: '2026-04-01T00:00:00' }),
    skill({ id: 8, displayName: 'Newer id', updatedAt: '2026-04-01T00:00:00' }),
  ];
  render(<SkillList skills={tied} sort="recent" onSelect={() => undefined} onToggle={() => undefined} />);
  expect(names()).toEqual(['Newer id', 'Older id']);
});
