import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { Button } from '../../../packages/ui/src/components/Button/Button';
import { Dropdown, DropdownItem } from '../../../packages/ui/src/components/Dropdown/Dropdown';
import { Select } from '../../../packages/ui/src/components/Select/Select';
import { Tooltip, TooltipProvider } from '../../../packages/ui/src/components/Tooltip/Tooltip';

afterEach(cleanup);

function renderMenu() {
  return render(
    <TooltipProvider>
      <button type="button">Before</button>
      <Tooltip content="More actions">
        <span>
          <Dropdown menu={<DropdownItem>Rename</DropdownItem>}>
            <Button aria-label="More" iconOnly>…</Button>
          </Dropdown>
        </span>
      </Tooltip>
      <button type="button">After</button>
    </TooltipProvider>,
  );
}

describe('shared Tooltip with a popup trigger', () => {
  it('does not treat focus inside a portalled menu as trigger focus', async () => {
    const user = userEvent.setup();
    renderMenu();

    await user.click(screen.getByRole('button', { name: 'More' }));
    await screen.findByRole('menu');

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('keeps focus restoration after Escape without reopening the tooltip', async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'More' });

    await user.click(trigger);
    await screen.findByRole('menu');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('does not reopen after selecting a menu command with the pointer', async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'More' });

    await user.click(trigger);
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    await waitFor(() => expect(trigger).toHaveFocus());

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('does not reopen after clicking outside onto a non-focusable surface', async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'More' });

    await user.click(trigger);
    await screen.findByRole('menu');
    await user.click(document.documentElement);
    await waitFor(() => expect(trigger).toHaveFocus());

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('cancels a pending hover when a menu is opened and closed quickly', async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'More' });

    await user.hover(trigger);
    await user.click(trigger);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());
    // Let the original 100ms hover delay expire after focus restoration.
    await act(() => new Promise((resolve) => setTimeout(resolve, 150)));

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('closes an already visible tooltip when a generic popup opens without a click', async () => {
    const user = userEvent.setup();
    const view = (expanded: boolean) => (
      <Tooltip content="Popup help">
        <span><button type="button" aria-haspopup="dialog" aria-expanded={expanded}>Popup</button></span>
      </Tooltip>
    );
    const { rerender } = render(view(false));
    await user.hover(screen.getByRole('button', { name: 'Popup' }));
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Popup help');

    rerender(view(true));

    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
  });

  it('supports standalone keyboard help but ignores scripted focus and touch', async () => {
    const user = userEvent.setup();
    render(<Tooltip content="Standalone help"><button type="button">Standalone</button></Tooltip>);
    const trigger = screen.getByRole('button', { name: 'Standalone' });
    act(() => trigger.focus());
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    act(() => trigger.blur());

    await user.tab();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Standalone help');
    await user.keyboard('{Escape}');
    await user.pointer({ keys: '[TouchA]', target: trigger });

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('does not retain a stale open state when a tooltip is temporarily disabled', async () => {
    const user = userEvent.setup();
    const view = (disabled: boolean) => (
      <Tooltip content="Optional help" disabled={disabled}><button type="button">Action</button></Tooltip>
    );
    const { rerender } = render(view(false));
    await user.tab();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Optional help');

    rerender(view(true));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    rerender(view(false));

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('keeps the icon Select tooltip closed after picking another option', async () => {
    const user = userEvent.setup();
    render(<Select variant="icon" defaultValue="one" aria-label="View" options={[
      { value: 'one', label: 'First view', icon: <svg /> },
      { value: 'two', label: 'Second view', icon: <svg /> },
    ]} />);
    const trigger = screen.getByRole('combobox', { name: 'View' });
    await user.tab();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('First view');

    await user.click(trigger);
    await user.click(await screen.findByRole('option', { name: 'Second view' }));
    await waitFor(() => expect(trigger).toHaveFocus());

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('shows deliberate keyboard focus and hover again after a menu closes', async () => {
    const user = userEvent.setup();
    renderMenu();
    const trigger = screen.getByRole('button', { name: 'More' });

    await user.tab();
    await user.tab();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('More actions');
    await user.keyboard('{Enter}');
    await screen.findByRole('menu');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    await user.tab();
    await user.tab({ shift: true });
    expect(await screen.findByRole('tooltip')).toHaveTextContent('More actions');
    await user.click(screen.getByRole('button', { name: 'After' }));
    await user.hover(trigger);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('More actions');
  });
});
