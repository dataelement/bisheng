import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { Tabs } from '../../../packages/ui/src/components/Tabs/Tabs';

afterEach(cleanup);

function renderTabs() {
  return render(
    <>
      <button type="button">Before</button>
      <Tabs items={[
        { key: 'one', label: 'One' },
        { key: 'disabled', label: 'Unavailable', disabled: true },
        { key: 'two', label: 'Two' },
        { key: 'three', label: 'Three' },
      ]} />
      <button type="button">After</button>
    </>,
  );
}

describe('shared Tabs focus visibility', () => {
  it('keeps pointer selection focused and active without requesting a focus ring', async () => {
    const user = userEvent.setup();
    renderTabs();
    const tab = screen.getByRole('tab', { name: 'Two' });

    await user.click(tab);

    expect(tab).toHaveFocus();
    expect(tab).toHaveAttribute('aria-selected', 'true');
    expect(tab).toHaveAttribute('data-pointer-focus', 'true');
  });

  it('keeps pointer suppression when focus moves between tabs', async () => {
    const user = userEvent.setup();
    renderTabs();

    await user.click(screen.getByRole('tab', { name: 'One' }));
    await user.click(screen.getByRole('tab', { name: 'Two' }));

    expect(screen.getByRole('tab', { name: 'Two' })).toHaveAttribute('data-pointer-focus', 'true');
    expect(screen.getByRole('tab', { name: 'One' })).toHaveAttribute('data-pointer-focus', 'false');
  });

  it('restores keyboard focus visibility and skips disabled tabs after a pointer selection', async () => {
    const user = userEvent.setup();
    renderTabs();
    await user.click(screen.getByRole('tab', { name: 'One' }));

    await user.keyboard('{ArrowRight}');

    const two = screen.getByRole('tab', { name: 'Two' });
    await waitFor(() => expect(two).toHaveFocus());
    expect(two).toHaveAttribute('aria-selected', 'true');
    expect(two).toHaveAttribute('data-pointer-focus', 'false');

    await user.keyboard('{End}');
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Three' })).toHaveFocus());
    await user.keyboard('{Home}');
    await waitFor(() => expect(screen.getByRole('tab', { name: 'One' })).toHaveFocus());
  });

  it('suppresses a keyboard focus ring when the already focused tab is clicked', async () => {
    const user = userEvent.setup();
    renderTabs();
    await user.click(screen.getByRole('button', { name: 'Before' }));
    await user.tab();
    const one = screen.getByRole('tab', { name: 'One' });
    expect(one).toHaveFocus();
    expect(one).toHaveAttribute('data-pointer-focus', 'false');

    await user.click(one);

    expect(one).toHaveFocus();
    expect(one).toHaveAttribute('data-pointer-focus', 'true');
  });

  it('allows keyboard re-entry after a pointer selection and a click outside', async () => {
    const user = userEvent.setup();
    renderTabs();
    const two = screen.getByRole('tab', { name: 'Two' });
    await user.click(two);
    await user.click(screen.getByRole('button', { name: 'After' }));

    await user.tab({ shift: true });

    expect(two).toHaveFocus();
    expect(two).toHaveAttribute('data-pointer-focus', 'false');
  });
});
