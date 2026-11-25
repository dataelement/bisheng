import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import OrgKbConfig from '@/pages/BuildPage/bench/OrgKbConfig';

vi.mock('@/components/bs-comp/selectComponent/useKnowledgeCandidates', () => ({
  useKnowledgeCandidates: () => ({
    items: [{ id: 9, name: 'Knowledge Nine' }],
    loaded: true,
    scopeKey: 'f005',
    error: null,
    loading: false,
    hasMore: false,
    search: () => {},
  }),
}));

afterEach(cleanup);

it('adds a knowledge base shown in the composer by default', () => {
  const onChange = vi.fn();
  render(<OrgKbConfig orgKbs={[]} onChange={onChange} />);

  fireEvent.click(screen.getByRole('checkbox'));

  expect(onChange).toHaveBeenCalledWith([
    { id: 9, name: 'Knowledge Nine', type: 3, show_in_composer: true, sort_order: 0 },
  ]);
});

it('writes show_in_composer when the admin hides a knowledge base', () => {
  const onChange = vi.fn();
  const orgKbs = [{ id: 9, name: 'Knowledge Nine', show_in_composer: true, sort_order: 0 }];
  render(<OrgKbConfig orgKbs={orgKbs} onChange={onChange} />);

  fireEvent.click(screen.getByRole('checkbox', { name: 'bench.showInComposer: Knowledge Nine' }));

  expect(onChange).toHaveBeenCalledWith([{ ...orgKbs[0], show_in_composer: false }]);
});
