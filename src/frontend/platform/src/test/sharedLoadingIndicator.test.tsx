import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import {
  Button, Cascader, LoadingIndicatorProvider, Switch, TreeNavigationStatus,
  type LoadingIndicatorProps,
} from '@bisheng/ui';

const renderIndicator = ({ className }: LoadingIndicatorProps) => (
  <span data-testid="configured-indicator" className={className} />
);

afterEach(cleanup);

it('preserves the default indicator outside the host provider', () => {
  const view = render(<Button loading>Save</Button>);
  expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-busy', 'true');
  expect(view.container.querySelector('svg.animate-spin')).not.toBeNull();
  expect(screen.queryByTestId('configured-indicator')).toBeNull();
});

it.each([
  ['small', 'size-3.5'], ['medium', 'size-4'], ['large', 'size-[18px]'],
] as const)('uses the configured %s button indicator and retains submission protection', (size, className) => {
  const onClick = vi.fn();
  render(<LoadingIndicatorProvider renderIndicator={renderIndicator}>
    <Button size={size} loading disabled onClick={onClick}>Save</Button>
  </LoadingIndicatorProvider>);
  const indicator = screen.getByTestId('configured-indicator');
  expect(indicator).toHaveClass(className);
  expect(indicator.parentElement).toHaveAttribute('aria-hidden', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(onClick).not.toHaveBeenCalled();
});

it('preserves asChild composition without injecting an extra child', () => {
  const indicator = vi.fn(renderIndicator);
  render(<LoadingIndicatorProvider renderIndicator={indicator}>
    <Button asChild loading><a href="/destination">Destination</a></Button>
  </LoadingIndicatorProvider>);
  expect(screen.getByRole('link', { name: 'Destination' })).toHaveAttribute('href', '/destination');
  expect(indicator).not.toHaveBeenCalled();
});

it('uses the configured switch indicator while keeping the toggle locked', () => {
  const onCheckedChange = vi.fn();
  render(<LoadingIndicatorProvider renderIndicator={renderIndicator}>
    <Switch loading checked aria-label="Publish" onCheckedChange={onCheckedChange} />
  </LoadingIndicatorProvider>);
  const control = screen.getByRole('switch', { name: 'Publish' });
  expect(control).toBeDisabled();
  expect(screen.getByTestId('configured-indicator')).toHaveClass('size-3.5');
  fireEvent.click(control);
  expect(onCheckedChange).not.toHaveBeenCalled();
});

it('uses configured indicators and screen-reader-only loading copy in cascaders and tree branches', () => {
  render(<LoadingIndicatorProvider renderIndicator={renderIndicator}>
    <Cascader options={[]} loading loadingText="Loading options" aria-label="Department" />
    <ul><TreeNavigationStatus loading>Loading branch</TreeNavigationStatus></ul>
  </LoadingIndicatorProvider>);
  fireEvent.click(screen.getByRole('combobox', { name: 'Department' }));
  expect(screen.getAllByTestId('configured-indicator')).toHaveLength(2);
  expect(screen.getByText('Loading options')).toHaveClass('sr-only');
  expect(screen.getByText('Loading branch')).toHaveClass('sr-only');
});
