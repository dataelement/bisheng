import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@bisheng/api-client';
import { fireEvent, render, screen } from '@testing-library/react';
import { useContext } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { userContext } from '@/contexts/userContext';
import { getPlatformModelCapabilities, listPlatformModels } from '@/controllers/API/platformModel';
import { PlatformModelSelectItem } from './PlatformModelSelectItem';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/components/bs-comp/formFields/useSelectLabels', () => ({ useSelectLabels: () => ({}) }));
vi.mock('@/controllers/API/platformModel', () => ({
    getPlatformModelCapabilities: vi.fn(),
    listPlatformModels: vi.fn(),
}));
vi.mock('@bisheng/ui', () => ({
    Button: 'button',
    Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
    Select: ({
        options,
        value,
        onChange,
    }: {
        options: { value: string; label: string }[];
        value?: string | null;
        onChange?: (val: string) => void;
    }) => (
        <select
            aria-label="model-select"
            value={value ?? ''}
            onChange={e => onChange?.(e.target.value)}
        >
            <option value="" />
            {options.map(option => (
                <option key={option.value} value={option.value}>
                    {option.label}
                </option>
            ))}
        </select>
    ),
}));

describe('PlatformModelSelectItem', () => {
    it('loads authorized models and saves pinned version reference', async () => {
        vi.mocked(getPlatformModelCapabilities).mockResolvedValue({
            platform_llm_enabled: true,
            multi_tenant_enabled: true,
        });
        vi.mocked(listPlatformModels).mockResolvedValue({
            items: [
                {
                    resource_type: 'model',
                    resource_id: 'model-1',
                    version_id: 'ver-101',
                    call_id: 'ver-101',
                    name: 'DeepSeek-V3',
                    version: '1.0.0',
                    status: 'published',
                    allowed_actions: ['use'],
                },
            ],
            page_size: 20,
            has_more: false,
            next_cursor: null,
        });
        const onChange = vi.fn();
        const onValidate = vi.fn();
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

        function Harness() {
            const defaults = useContext(userContext);
            return (
                <userContext.Provider value={{ ...defaults, user: { user_id: 10, tenant_id: 2 } }}>
                    <PlatformModelSelectItem
                        workflowId="wf-1"
                        reference={null}
                        onChange={onChange}
                        onValidate={onValidate}
                    />
                </userContext.Provider>
            );
        }

        render(
            <QueryClientProvider client={queryClient}>
                <Harness />
            </QueryClientProvider>,
        );

        expect(await screen.findByRole('option', { name: 'DeepSeek-V3 (1.0.0)' })).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('model-select'), { target: { value: 'model-1::ver-101' } });
        expect(onChange).toHaveBeenCalledWith({
            resource_id: 'model-1',
            version_id: 'ver-101',
            call_id: 'ver-101',
            name: 'DeepSeek-V3',
            version: '1.0.0',
        });
        expect(screen.getByLabelText('model-select')).toHaveValue('model-1::ver-101');
        expect(screen.getByText(/platformLlm\.pinnedVersion/)).toHaveTextContent('platformLlm.pinnedVersion: 1.0.0');
    });

    it('shows token error alert instead of empty list on 10581', async () => {
        vi.mocked(getPlatformModelCapabilities).mockResolvedValue({
            platform_llm_enabled: true,
            multi_tenant_enabled: false,
        });
        vi.mocked(listPlatformModels).mockRejectedValue(
            new ApiError(null, { message: 'Token invalid', envelope: { status_code: 10581 } }),
        );
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

        function Harness() {
            const defaults = useContext(userContext);
            return (
                <userContext.Provider value={{ ...defaults, user: { user_id: 10 } }}>
                    <PlatformModelSelectItem
                        workflowId="wf-1"
                        reference={null}
                        onChange={vi.fn()}
                        onValidate={vi.fn()}
                    />
                </userContext.Provider>
            );
        }

        render(
            <QueryClientProvider client={queryClient}>
                <Harness />
            </QueryClientProvider>,
        );

        expect(await screen.findByRole('alert')).toHaveTextContent('platformLlm.tokenInvalid');
        expect(screen.queryByText('platformLlm.empty')).not.toBeInTheDocument();
    });
});
