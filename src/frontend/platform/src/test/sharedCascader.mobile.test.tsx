import * as React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Cascader } from '../../../packages/ui/src/components/Cascader/Cascader';
import type { CascaderOption } from '../../../packages/ui/src/components/Cascader/types';

const options: CascaderOption[] = [{
  value: 'hq', label: 'Headquarters', children: [
    ...Array.from({ length: 8 }, (_, index) => ({ value: `other-${index}`, label: `Department ${index}` })),
    { value: 'engineering', label: 'Engineering', children: [
      { value: 'design', label: 'Design' },
      { value: 'frontend', label: 'Frontend' },
    ] },
  ],
}];
const selectedPath = ['hq', 'engineering', 'design'];
let phone = true;

function openPicker() {
  const trigger = screen.getByRole('combobox', { name: 'Team' });
  fireEvent.click(trigger);
  return trigger;
}

beforeEach(() => {
  phone = true;
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: phone, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('shared Cascader mobile navigation', () => {
  it('uses one anchored panel and drills down before committing the full leaf path', () => {
    const onChange = vi.fn();
    render(<Cascader options={options} onChange={onChange} aria-label="Team" showSearch={false} />);
    const trigger = openPicker();
    const popup = screen.getByRole('dialog', { name: 'Team' });
    expect(popup.closest('[data-radix-popper-content-wrapper]')).not.toBeNull();
    expect(screen.getAllByRole('tree')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('treeitem', { name: 'Headquarters' }));
    expect(screen.queryByRole('treeitem', { name: 'Headquarters' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('treeitem', { name: 'Engineering' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getAllByRole('treeitem')).toHaveLength(2);
    fireEvent.click(screen.getByRole('treeitem', { name: 'Design' }));
    expect(onChange).toHaveBeenCalledWith(selectedPath, expect.any(Array));
    expect(screen.queryByRole('tree')).not.toBeInTheDocument();
    expect(trigger).toHaveTextContent('Design');
    expect(trigger).not.toHaveTextContent('Headquarters');
    openPicker();
    expect(screen.getByRole('treeitem', { name: 'Design' })).toHaveAttribute('aria-selected', 'true');
  });

  it('restores the parent highlight and scroll position on back without scrolling the page', () => {
    render(<Cascader options={options} aria-label="Team" showSearch={false} />);
    const trigger = openPicker();
    fireEvent.click(screen.getByRole('treeitem', { name: 'Headquarters' }));
    const parent = screen.getByRole('treeitem', { name: 'Engineering' });
    const column = parent.closest<HTMLElement>('[data-cascader-column]');
    if (!column) throw new Error('Expected a scrollable menu column');
    column.scrollTop = 240;
    fireEvent.click(parent);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    const restoredParent = screen.getByRole('treeitem', { name: 'Engineering' });
    expect(restoredParent.closest('[data-cascader-column]')?.scrollTop).toBe(240);
    expect(trigger).toHaveAttribute('aria-activedescendant', restoredParent.id);
    expect(trigger).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByRole('treeitem', { name: 'Headquarters' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
  });

  it('keeps searching inside the popup and restores keyboard navigation after clearing', async () => {
    const onChange = vi.fn();
    render(<Cascader options={options} defaultValue={selectedPath} onChange={onChange}
      aria-label="Team" showSearch searchPlaceholder="Search teams" />);
    const trigger = openPicker();
    const input = screen.getByRole('combobox', { name: 'Search teams' });
    fireEvent.change(input, { target: { value: 'Headquarters' } });
    expect(screen.getByRole('treeitem', { name: 'Headquarters / Engineering / Design' })).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'missing' } });
    expect(screen.getByText('No matches')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: '' } });
    expect(screen.getByRole('treeitem', { name: 'Design' })).toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'ArrowLeft' });
    expect(screen.getByRole('treeitem', { name: 'Design' })).toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(input).toHaveAttribute('aria-activedescendant', screen.getByRole('treeitem', { name: 'Frontend' }).id);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith(['hq', 'engineering', 'frontend'], expect.any(Array));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('applies multiple selections immediately and closes on the trigger without a Done button', () => {
    const onChange = vi.fn();
    render(<Cascader options={options} multiple onChange={onChange} aria-label="Team" showSearch={false} />);
    const trigger = openPicker();
    fireEvent.click(screen.getByRole('treeitem', { name: 'Headquarters' }));
    const engineering = screen.getByRole('treeitem', { name: 'Engineering' });
    fireEvent.click(within(engineering).getByRole('checkbox', { hidden: true }));
    expect(onChange).toHaveBeenLastCalledWith([
      selectedPath, ['hq', 'engineering', 'frontend'],
    ], expect.any(Array));
    expect(screen.getByRole('tree')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Done' })).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(screen.queryByRole('tree')).not.toBeInTheDocument();
  });

  it('distinguishes navigating a strict parent from selecting it', () => {
    const onChange = vi.fn();
    render(<Cascader options={options} checkStrictly onChange={onChange} aria-label="Team" showSearch={false} />);
    openPicker();
    fireEvent.click(screen.getByRole('treeitem', { name: 'Headquarters' }));
    expect(onChange).not.toHaveBeenCalled();
    const engineering = screen.getByRole('treeitem', { name: 'Engineering' });
    fireEvent.click(within(engineering).getByRole('button', { hidden: true }));
    expect(onChange).toHaveBeenCalledWith(['hq', 'engineering'], expect.any(Array));
    expect(screen.queryByRole('tree')).not.toBeInTheDocument();
  });

  it('retries lazy load failures in the same popup', async () => {
    const loadData = vi.fn().mockRejectedValueOnce(new Error('Offline'))
      .mockResolvedValueOnce([{ value: 'design', label: 'Design' }]);
    const onLoadError = vi.fn();
    render(<Cascader options={[{ value: 'hq', label: 'Headquarters', isLeaf: false }]}
      loadData={loadData} onLoadError={onLoadError} aria-label="Team" showSearch={false} />);
    openPicker();
    fireEvent.click(screen.getByRole('treeitem', { name: 'Headquarters' }));
    expect(await screen.findByText('Load failed. Try again.')).toBeInTheDocument();
    expect(onLoadError).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('treeitem', { name: 'Headquarters' }));
    expect(await screen.findByRole('treeitem', { name: 'Design' })).toBeInTheDocument();
    expect(screen.getAllByRole('tree')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
    expect(loadData).toHaveBeenCalledTimes(2);
  });

  it('restores the selected level for default and externally controlled opening', async () => {
    const { rerender } = render(<Cascader options={options} value={selectedPath}
      open={false} aria-label="Team" showSearch={false} />);
    rerender(<Cascader options={options} value={selectedPath} open aria-label="Team" showSearch={false} />);
    expect(await screen.findByRole('treeitem', { name: 'Design' })).toHaveAttribute('aria-selected', 'true');
    cleanup();
    render(<Cascader options={options} defaultValue={selectedPath} defaultOpen aria-label="Team" showSearch={false} />);
    expect(screen.getByRole('treeitem', { name: 'Design' })).toHaveAttribute('aria-selected', 'true');
  });

  it('closes with Escape and restores the trigger focus', async () => {
    render(<Cascader options={options} aria-label="Team" showSearch searchPlaceholder="Search teams" />);
    const trigger = openPicker();
    const input = screen.getByRole('combobox', { name: 'Search teams' });
    input.focus();
    fireEvent.keyDown(input, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('tree')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it('closes on an outside click without taking focus from the clicked control', async () => {
    const user = userEvent.setup();
    render(<><Cascader options={options} aria-label="Team" showSearch={false} /><button>Next field</button></>);
    await user.click(screen.getByRole('combobox', { name: 'Team' }));
    const next = screen.getByRole('button', { name: 'Next field' });
    await user.click(next);
    await waitFor(() => expect(screen.queryByRole('tree')).not.toBeInTheDocument());
    expect(next).toHaveFocus();
  });

  it('keeps loading and empty states inside the same anchored popup', () => {
    const { rerender } = render(<Cascader options={[]} aria-label="Team" loading showSearch={false} />);
    openPicker();
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    rerender(<Cascader options={[]} aria-label="Team" showSearch={false} />);
    expect(screen.getByRole('dialog', { name: 'Team' })).toHaveTextContent('No data');
  });

  it.each(['disabled', 'readOnly'] as const)('does not open when %s', (state) => {
    render(<Cascader options={options} aria-label="Team" {...{ [state]: true }} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Team' }));
    expect(screen.queryByRole('tree')).not.toBeInTheDocument();
  });

  it('preserves the desktop multicolumn panel', () => {
    phone = false;
    render(<Cascader options={options} defaultValue={selectedPath} aria-label="Team" showSearch={false} />);
    openPicker();
    expect(screen.getByRole('treeitem', { name: 'Headquarters' })).toBeInTheDocument();
    expect(screen.getByRole('treeitem', { name: 'Engineering' })).toBeInTheDocument();
    expect(screen.getByRole('treeitem', { name: 'Design' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
  });
});
