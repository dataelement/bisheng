/**
 * F069 T012: the result panel says plainly when the run retrieved sources but the
 * report cites none of them (AC-04). Anything else — cited, no sources, no audit
 * at all — renders no notice, and the notice is a line of text, never a badge.
 */
import { render, screen } from '@testing-library/react';
import { ResultSection } from './ResultSection';

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string, vars?: Record<string, string>) =>
        vars ? `${key}:${Object.values(vars).join(',')}` : key,
}));

jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy({}, { get: () => () => null }),
}));

jest.mock('@bisheng/ui', () => ({
    Badge: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
}));

jest.mock('~/components/Chat/Messages/Content/Markdown', () => ({
    __esModule: true,
    default: ({ content }: { content: string }) => <div data-testid="markdown">{content}</div>,
}));

jest.mock('./SaveAsButton', () => ({ SaveAsButton: () => null }));
jest.mock('./NewTabHint', () => ({ NewTabHint: () => null }));
jest.mock('~/markdown.css', () => ({}), { virtual: true });

const noop = () => undefined;

describe('ResultSection citation audit notice', () => {
    it('renders the notice with the retrieved count when the report cites nothing', () => {
        render(
            <ResultSection
                answer="report body"
                files={[]}
                versionId="sv-1"
                onPreview={noop}
                citationAudit={{ status: 'uncited', sources_seen: 12 }}
            />,
        );

        const note = screen.getByTestId('citation-uncited-note');
        expect(note).toHaveTextContent('com_linsight_citation_uncited:12');
        expect(note.tagName).toBe('P');
    });

    it.each([
        ['cited', { status: 'cited', sources_seen: 3 }],
        ['no_sources', { status: 'no_sources', sources_seen: 0 }],
        ['absent', undefined],
        ['null', null],
    ])('renders no notice when the audit is %s', (_label, audit) => {
        render(
            <ResultSection answer="report body" files={[]} versionId="sv-1" onPreview={noop} citationAudit={audit} />,
        );

        expect(screen.queryByTestId('citation-uncited-note')).toBeNull();
    });

    it('falls back to zero when the count is missing', () => {
        render(
            <ResultSection answer="report body" files={[]} versionId="sv-1" onPreview={noop} citationAudit={{ status: 'uncited' }} />,
        );

        expect(screen.getByTestId('citation-uncited-note')).toHaveTextContent('com_linsight_citation_uncited:0');
    });
});
