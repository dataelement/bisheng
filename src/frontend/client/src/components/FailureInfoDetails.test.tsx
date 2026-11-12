import { fireEvent, render, screen } from '@testing-library/react';
import { FailureInfoDetails } from './FailureInfoDetails';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string, values?: Record<string, string>) =>
    key === 'com_linsight_error_view_detail' ? 'View details'
        : key === 'com_linsight_error_hide_detail' ? 'Hide details'
        : values?.['0'] ?? key,
}));
jest.mock('bisheng-icons', () => ({ Outlined: { Down: () => null } }));

const failure = {
    version: 1,
    failure_id: 'failure-1',
    category: 'model_service',
    service: 'llm',
    operation: 'invoke_model',
    occurred_at: '2026-11-11T12:20:39Z',
    trace_id: 'trace-1',
};

it('keeps diagnostics collapsed, then formats the timestamp in the device timezone', () => {
    render(<FailureInfoDetails failureInfo={failure} />);
    expect(screen.queryByText(/failure-1/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'View details' }));
    const details = screen.getByText(/failure-1/);
    const localTime = new Date(failure.occurred_at);
    const clock = [localTime.getHours(), localTime.getMinutes(), localTime.getSeconds()]
        .map((value) => String(value).padStart(2, '0')).join(':');
    expect(details.textContent).toContain(`${clock} UTC`);
    expect(details.textContent).toMatch(/UTC[+-]\d{2}:\d{2}/);
    expect(details.textContent).not.toContain(failure.occurred_at);
    expect(details.textContent).toContain('trace-1');
    fireEvent.click(screen.getByRole('button', { name: 'Hide details' }));
    expect(screen.queryByText(/failure-1/)).not.toBeInTheDocument();
});

it('preserves the release-line safe reference fallback without dependency metadata', () => {
    const { rerender } = render(<FailureInfoDetails referenceId="support-1" />);
    expect(screen.getByText('support-1')).toBeInTheDocument();
    rerender(<FailureInfoDetails referenceId="https://private.invalid/secret" />);
    expect(screen.queryByText(/private/)).not.toBeInTheDocument();
});

it('reveals redacted detail together with provenance using one disclosure', () => {
    render(<FailureInfoDetails failureInfo={failure} detail="Redacted provider error" />);
    expect(screen.getAllByRole('button', { name: 'View details' })).toHaveLength(1);
    expect(screen.queryByText('Redacted provider error')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'View details' }));
    expect(screen.getByText(/failure-1/)).toBeInTheDocument();
    expect(screen.getByText('Redacted provider error')).toBeInTheDocument();
});
