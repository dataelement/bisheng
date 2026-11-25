import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { toolUsageOf, withToolUsage } from '@/components/LinSight/ToolUsageSelect';
import ToolsConfig from './ToolsConfig';

vi.mock('@/controllers/API/tools', () => ({ getToolsApi: vi.fn().mockResolvedValue([]) }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
afterEach(() => cleanup());

const CODE = {
    id: 2,
    name: 'Code interpreter',
    is_preset: 0,
    default_checked: true,
    children: [{ id: 22, name: 'Code interpreter', tool_key: 'bisheng_code_interpreter' }],
};

it('maps the two stored flags onto one usage and back', () => {
    expect(toolUsageOf({})).toBe('optional');
    expect(toolUsageOf({ default_checked: true })).toBe('default');
    expect(toolUsageOf({ default_checked: true, auto_enabled: true })).toBe('auto');
    expect(withToolUsage(CODE, 'auto')).toMatchObject({ default_checked: false, auto_enabled: true });
    expect(withToolUsage(CODE, 'optional')).toMatchObject({ default_checked: false, auto_enabled: false });
});

it('saves "always on" as auto-enabled and not checked by default', async () => {
    const onChange = vi.fn();
    render(<ToolsConfig tools={[CODE]} onChange={onChange} />, { wrapper });

    expect(screen.getByText('bench.toolUsage.title')).toBeInTheDocument();
    const select = screen.getByRole('combobox', { name: 'bench.toolUsage.ariaLabel' });
    expect(select).toHaveTextContent('bench.toolUsage.default');

    fireEvent.click(select);
    fireEvent.click(await screen.findByRole('option', { name: /bench\.toolUsage\.auto/ }));

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ id: 2, default_checked: false, auto_enabled: true })]);
});
