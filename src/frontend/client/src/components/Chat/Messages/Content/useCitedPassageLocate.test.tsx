/**
 * The shared locate hook behind every citation preview (task-mode source pane,
 * daily-chat docked panel, knowledge-space drawer): a docx / md preview lands on
 * the cited passage only after its body is ready. Misses keep the file at the
 * beginning without a warning; PDFs retain their own bbox highlight.
 */
import { act, render, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { useCitedPassageLocate, type CitedPassageLocateState } from './useCitedPassageLocate';

const DOC = [
    'Chapter one sets out the purpose of the performance rules for every employee.',
    'The trial period lasts six months from the effective date of these rules.',
    'Chapter three describes how objectives are drafted and reviewed each quarter.',
];

interface HarnessProps {
    fileType: string;
    chunks: string[];
    onState: (state: CitedPassageLocateState) => void;
    paragraphs?: string[];
    documentKey?: string;
    documentReady?: boolean;
}

function Harness({ fileType, chunks, onState, paragraphs = DOC, documentKey = '', documentReady = true }: HarnessProps) {
    const ref = useRef<HTMLDivElement>(null);
    onState(useCitedPassageLocate(ref, fileType, chunks, documentKey));
    return (
        <div ref={ref}>
            <header><p>100%</p></header>
            <div data-citation-scroll-container>
                {documentReady && <div data-citation-document-body>
                    {paragraphs.map((text) => (
                        <p key={text}>{text}</p>
                    ))}
                </div>}
            </div>
        </div>
    );
}

beforeAll(() => {
    Element.prototype.scrollIntoView = jest.fn();
});

function run(fileType: string, chunks: string[]) {
    let state: CitedPassageLocateState = 'pending';
    const view = render(<Harness fileType={fileType} chunks={chunks} onState={(s) => (state = s)} />);
    return { view, get state() { return state; } };
}

test('a docx preview lands on and marks the cited paragraph', async () => {
    const r = run('docx', ['The trial period lasts six months from the effective date of these rules.']);
    await waitFor(() => expect(r.state).toBe('found'));
    const hits = r.view.container.querySelectorAll('[data-cite-hit]');
    expect(hits).toHaveLength(1);
    expect(hits[0].textContent).toContain('trial period');
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
});

test('a passage that is not in the file reports missed', async () => {
    const r = run('docx', ['Bonus pools are split by department headcount at year end every single year.']);
    await waitFor(() => expect(r.state).toBe('missed'));
    expect(r.view.container.querySelectorAll('[data-cite-hit]')).toHaveLength(0);
});

test('spreadsheets skip passage locating', async () => {
    const r = run('xlsx', ['The trial period lasts six months from the effective date of these rules.']);
    await waitFor(() => expect(r.state).toBe('missed'));
});

test('toolbar paragraphs do not trigger a failed locate before the body loads', async () => {
    jest.useFakeTimers();
    const states: CitedPassageLocateState[] = [];
    const chunks = [DOC[1]];
    const onState = (state: CitedPassageLocateState) => states.push(state);
    try {
        const view = render(<Harness fileType="md" chunks={chunks} documentReady={false} onState={onState} />);
        await act(async () => { jest.advanceTimersByTime(500); });
        expect(states).not.toContain('missed');
        expect(view.container.querySelector('[data-cite-hit]')).toBeNull();
        view.rerender(<Harness fileType="md" chunks={chunks} documentReady onState={onState} />);
        await act(async () => {
            await Promise.resolve();
            jest.advanceTimersByTime(300);
        });
        expect(states).not.toContain('missed');
        expect(view.container.querySelector('[data-cite-hit]')?.textContent).toBe(DOC[1]);
    } finally {
        jest.useRealTimers();
    }
});

test('a missed citation clears old marks and returns the file to its beginning', async () => {
    const onState = jest.fn();
    const view = render(<Harness fileType="md" chunks={[DOC[1]]} onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')).not.toBeNull());
    const viewport = view.container.querySelector<HTMLElement>('[data-citation-scroll-container]')!;
    viewport.scrollTop = 800;
    view.rerender(<Harness fileType="md" chunks={['This absent source sentence cannot be located in the document.']} onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')).toBeNull());
    expect(viewport.scrollTop).toBe(0);
});

test('pdf is left to its own bbox highlight', async () => {
    const r = run('pdf', ['The trial period lasts six months from the effective date of these rules.']);
    await waitFor(() => expect(r.state).toBe('native'));
    expect(r.view.container.querySelectorAll('[data-cite-hit]')).toHaveLength(0);
});

test('a citation without source text also returns the file to its beginning', async () => {
    const onState = jest.fn();
    const view = render(<Harness fileType="md" chunks={[DOC[1]]} onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')).not.toBeNull());
    const viewport = view.container.querySelector<HTMLElement>('[data-citation-scroll-container]')!;
    viewport.scrollTop = 800;
    view.rerender(<Harness fileType="md" chunks={[]} onState={onState} />);
    expect(view.container.querySelector('[data-cite-hit]')).toBeNull();
    expect(viewport.scrollTop).toBe(0);
});

test('nothing happens before the file type resolves', () => {
    const r = run('', ['The trial period lasts six months from the effective date of these rules.']);
    expect(r.state).toBe('pending');
});

test('locates short historical snippets without a minimum document length', async () => {
    const states: CitedPassageLocateState[] = [];
    const view = render(<Harness fileType="txt" chunks={['Trial period']} paragraphs={['Trial period']} onState={(s) => states.push(s)} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')).not.toBeNull());
    expect(states).toContain('found');
});

test('waits for asynchronously rendered document content', async () => {
    const chunks = [DOC[1]];
    const onState = jest.fn();
    const view = render(<Harness fileType="md" chunks={chunks} paragraphs={[]} onState={onState} />);
    view.rerender(<Harness fileType="md" chunks={chunks} paragraphs={DOC} onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')?.textContent).toBe(DOC[1]));
});

test('switching passages removes the old highlight and unmount cleans up', async () => {
    const onState = jest.fn();
    const view = render(<Harness fileType="docx" chunks={[DOC[1]]} onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')?.textContent).toBe(DOC[1]));
    view.rerender(<Harness fileType="docx" chunks={[DOC[2]]} onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')?.textContent).toBe(DOC[2]));
    expect(view.container.querySelectorAll('[data-cite-band]')).toHaveLength(1);
    const root = view.container.firstElementChild!;
    view.unmount();
    expect(root.querySelectorAll('[data-cite-band]')).toHaveLength(0);
});

test('changing files reattaches locating even for the same type and snippet', async () => {
    const chunks = [DOC[1]];
    const onState = jest.fn();
    const view = render(<Harness fileType="md" chunks={chunks} documentKey="first.md" onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')).not.toBeNull());
    view.rerender(<Harness fileType="md" chunks={chunks} documentKey="second.md" paragraphs={[]} onState={onState} />);
    view.rerender(<Harness fileType="md" chunks={chunks} documentKey="second.md" paragraphs={DOC} onState={onState} />);
    await waitFor(() => expect(view.container.querySelector('[data-cite-hit]')?.textContent).toBe(DOC[1]));
});
