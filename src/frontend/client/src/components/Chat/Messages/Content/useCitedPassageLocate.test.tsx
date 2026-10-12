/**
 * The shared locate hook behind every citation preview (task-mode source pane,
 * daily-chat docked panel, knowledge-space drawer): a docx / md preview lands on
 * the cited passage; tables and failed matches report 'missed' so the host shows
 * the quoted text; PDFs are left to their own bbox highlight.
 */
import { act, render, waitFor } from '@testing-library/react';
import { useRef, useState } from 'react';
import { MISS_SETTLE_MS, useCitedPassageLocate, type CitedPassageLocateState } from './useCitedPassageLocate';

const DOC = [
    'Chapter one sets out the purpose of the performance rules for every employee.',
    'The trial period lasts six months from the effective date of these rules.',
    'Chapter three describes how objectives are drafted and reviewed each quarter.',
];

function Harness({ fileType, chunks, onState }: {
    fileType: string;
    chunks: string[];
    onState: (state: CitedPassageLocateState) => void;
}) {
    const ref = useRef<HTMLDivElement>(null);
    onState(useCitedPassageLocate(ref, fileType, chunks));
    return (
        <div ref={ref}>
            {DOC.map((text) => (
                <p key={text}>{text}</p>
            ))}
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
    await waitFor(() => expect(r.state).toBe('missed'), { timeout: MISS_SETTLE_MS + 1000 });
    expect(r.view.container.querySelectorAll('[data-cite-hit]')).toHaveLength(0);
});

/** Renders the document in two passes, the cited paragraph arriving second. */
function ProgressiveHarness({ onState }: { onState: (state: CitedPassageLocateState) => void }) {
    const ref = useRef<HTMLDivElement>(null);
    const [shown, setShown] = useState(1);
    (window as unknown as { revealRest: () => void }).revealRest = () => setShown(DOC.length);
    onState(useCitedPassageLocate(ref, 'docx', [DOC[1]]));
    return (
        <div ref={ref}>
            {DOC.slice(0, shown).map((text) => (
                <p key={text}>{text}</p>
            ))}
        </div>
    );
}

test('a passage still rendering never flashes missed before it is found', async () => {
    jest.useFakeTimers();
    try {
        const states: CitedPassageLocateState[] = [];
        render(<ProgressiveHarness onState={(s) => states.push(s)} />);
        // First pass has content but not the cited paragraph.
        act(() => {
            jest.advanceTimersByTime(MISS_SETTLE_MS / 2);
        });
        act(() => {
            (window as unknown as { revealRest: () => void }).revealRest();
        });
        await act(async () => {
            jest.advanceTimersByTime(MISS_SETTLE_MS * 2);
        });
        expect(states[states.length - 1]).toBe('found');
        expect(states).not.toContain('missed');
    } finally {
        jest.useRealTimers();
    }
});

test('spreadsheets show the quote instead of trying to locate', async () => {
    const r = run('xlsx', ['The trial period lasts six months from the effective date of these rules.']);
    await waitFor(() => expect(r.state).toBe('missed'));
});

test('pdf is left to its own bbox highlight', async () => {
    const r = run('pdf', ['The trial period lasts six months from the effective date of these rules.']);
    await waitFor(() => expect(r.state).toBe('native'));
    expect(r.view.container.querySelectorAll('[data-cite-hit]')).toHaveLength(0);
});

test('nothing happens before the file type resolves', () => {
    const r = run('', ['The trial period lasts six months from the effective date of these rules.']);
    expect(r.state).toBe('pending');
});
