import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PlatformKnowledgeQueryItem } from './PlatformKnowledgeQueryItem';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('@/components/bs-comp/formFields/useSelectLabels', () => ({ useSelectLabels: () => ({}) }));
vi.mock('./VarSelectItem', () => ({
    VarSelectSingleItem: ({ onChange }: { onChange: (value: string) => void }) =>
        <button onClick={() => onChange('input.user_input')}>Choose variable</button>,
}));
vi.mock('@bisheng/ui', () => ({
    Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
    Select: ({ options, value, onChange, 'aria-label': label }: {
        options: { value: string; label: string }[];
        value: string;
        onChange: (value: string) => void;
        'aria-label': string;
    }) => <select aria-label={label} value={value} onChange={event => onChange(event.target.value)}>
        {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>,
}));

describe('knowledge question editor', () => {
    it('switches input sources without changing output keys', () => {
        const onChange = vi.fn();
        const onOutputChange = vi.fn();
        render(<PlatformKnowledgeQueryItem nodeId="search"
            data={{ key: 'user_question', value: { source: 'variable', variable: '' } }}
            onChange={onChange} onValidate={vi.fn()} onVarEvent={vi.fn()} onOutputChange={onOutputChange} />);
        fireEvent.click(screen.getByText('Choose variable'));
        expect(onChange).toHaveBeenLastCalledWith({ source: 'variable', variable: 'input.user_input' });
        fireEvent.change(screen.getByLabelText('platformKnowledge.questionSource'), { target: { value: 'constant' } });
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'bearing' } });
        expect(onChange).toHaveBeenLastCalledWith({ source: 'constant', value: 'bearing' });
        expect(onOutputChange.mock.lastCall?.[1].map((output: { key: string }) => output.key))
            .toEqual(['retrieved_result', 'retrieved_text', 'citations', 'hit_count']);
    });
});
