import { render } from '@testing-library/react';
import { AnswerFallback } from './AnswerFallback';

const markdownProps: Array<{ content: string; citations?: unknown }> = [];
jest.mock('~/components/Chat/Messages/Content/Markdown', () => ({
    __esModule: true,
    default: (props: { content: string; citations?: unknown }) => {
        markdownProps.push(props);
        return <div data-testid="markdown">{props.content}</div>;
    },
}));

describe('AnswerFallback', () => {
    beforeEach(() => {
        markdownProps.length = 0;
    });

    it('hands the stored answer to Markdown with the citation markers stripped', () => {
        const answer = '- **Short-term pressure**: rates stay high \ue200websearch_150b0464:1\ue201websearch_53875b24:1\ue202.';
        render(<AnswerFallback answer={answer} />);
        expect(markdownProps).toHaveLength(1);
        expect(markdownProps[0].content).toBe('- **Short-term pressure**: rates stay high .');
        expect(markdownProps[0].content).not.toMatch(/[\ue200-\ue202]|websearch_/);
    });
});
