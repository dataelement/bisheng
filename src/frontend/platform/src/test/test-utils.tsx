import { render, RenderOptions } from '@testing-library/react';
import { ReactElement } from 'react';
import { BrowserRouter } from 'react-router-dom';

/**
 * Wraps children with providers commonly needed across tests.
 * Add more providers (theme, auth context, etc.) as needed.
 */
function AllProviders({ children }: { children: React.ReactNode }) {
  return <BrowserRouter>{children}</BrowserRouter>;
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
