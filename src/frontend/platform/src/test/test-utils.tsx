import { render, RenderOptions, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from 'react-query';
import { BrowserRouter } from 'react-router-dom';

/**
 * Wraps children with providers commonly needed across tests.
 * Add more providers (theme, auth context, etc.) as needed.
 */
function AllProviders({ children }: { children: React.ReactNode }) {
  // Fresh react-query client per render so cache never leaks across tests; the
  // app provides one at its root (src/index.tsx), so components using
  // useQuery/useQueryClient (e.g. the F038 lazy department tree) need it here too.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
}

/**
 * Custom render that wraps the component with AllProviders.
 *
 * Usage:
 *   import { render, screen } from '@/test/test-utils';
 *   render(<MyComponent />);
 *   expect(screen.getByText('hello')).toBeInTheDocument();
 */
const customRender = (
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
) => render(ui, { wrapper: AllProviders, ...options });

/**
 * Pick an option from a bs-ui (Radix) Select — the trigger is a button, not a
 * native <select>, so fireEvent.change does not work on it.
 *
 * The option is addressed by its accessible name, or by its position when the
 * i18n mock renders several options under the same key.
 *
 * Usage:
 *   await selectOption('model.preset.label', 'Preset A');
 *   await selectOption('actionLevel.change.edit', 3);
 */
export async function selectOption(
  triggerLabel: string,
  option: string | RegExp | number
) {
  const user = userEvent.setup();
  await user.click(screen.getByLabelText(triggerLabel));
  const target =
    typeof option === 'number'
      ? (await screen.findAllByRole('option'))[option]
      : await screen.findByRole('option', { name: option });
  await user.click(target);
}

/**
 * Pick an item from a bs-ui (Radix) DropdownMenu radio group — the items carry
 * role="menuitemradio", not role="option", so `selectOption` cannot see them.
 *
 * Usage:
 *   await selectMenuOption('actionLevel.change.edit', 3);
 */
export async function selectMenuOption(
  triggerLabel: string,
  option: string | RegExp | number
) {
  const user = userEvent.setup();
  await user.click(screen.getByLabelText(triggerLabel));
  const target =
    typeof option === 'number'
      ? (await screen.findAllByRole('menuitemradio'))[option]
      : await screen.findByRole('menuitemradio', { name: option });
  await user.click(target);
}

// Re-export everything from @testing-library/react
export * from '@testing-library/react';
// Override render with the custom version
export { customRender as render };
