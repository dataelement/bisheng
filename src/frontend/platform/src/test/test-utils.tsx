import { render, RenderOptions } from '@testing-library/react';
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

// Re-export everything from @testing-library/react
export * from '@testing-library/react';
// Override render with the custom version
export { customRender as render };
