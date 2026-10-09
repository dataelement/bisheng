import { act, render } from '@testing-library/react';
import { useRef } from 'react';
import { COMPARE_SETTLE_MS, useCompareTransitionFreeze } from './useCompareTransitionFreeze';

const ROW = 1480;
const CHAT = 760;
const PANEL = 712;

function widthOf(width: number) {
    return () => ({ width } as DOMRect);
}

type Snapshot = ReturnType<typeof useCompareTransitionFreeze>;
let latest: Snapshot;

function Harness({ comparing, open = true, enabled = true }: { comparing: boolean; open?: boolean; enabled?: boolean }) {
    const panelRef = useRef<HTMLDivElement>(null);
    latest = useCompareTransitionFreeze(comparing, open, enabled, panelRef);
    return (
        <div ref={latest.rowRef}>
            <div ref={latest.chatRef} data-testid="chat" />
            <div ref={panelRef} data-testid="panel" />
        </div>
    );
}

function mount(comparing: boolean, props: { open?: boolean; enabled?: boolean } = {}) {
    const utils = render(<Harness comparing={comparing} {...props} />);
    const [row] = utils.container.children as unknown as HTMLElement[];
    row.getBoundingClientRect = widthOf(ROW);
    utils.getByTestId('chat').getBoundingClientRect = widthOf(CHAT);
    utils.getByTestId('panel').getBoundingClientRect = widthOf(PANEL);
    return utils;
}

describe('useCompareTransitionFreeze', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('does nothing until compare is toggled', () => {
        mount(false);
        expect(latest.panelStyle).toBeUndefined();
        expect(latest.chatStyle).toBeUndefined();
        expect(latest.entering).toBe(false);
    });

    it('pins the panel to the full row and the chat to its current width while entering', () => {
        const { rerender } = mount(false);
        rerender(<Harness comparing />);
        expect(latest.panelStyle).toEqual({ minWidth: ROW - 8, width: ROW - 8 });
        expect(latest.chatStyle).toEqual({ '--compare-freeze-w': `${CHAT}px` });
        expect(latest.entering).toBe(true);

        act(() => {
            jest.advanceTimersByTime(COMPARE_SETTLE_MS);
        });
        expect(latest.panelStyle).toBeUndefined();
        expect(latest.chatStyle).toBeUndefined();
        expect(latest.entering).toBe(false);
    });

    it('pins both to the docked layout while leaving compare', () => {
        const { rerender } = mount(true);
        rerender(<Harness comparing={false} />);
        // clamp(440px, 46%, 720px) of 1480 → 680.8
        const docked = ROW * 0.46;
        expect(latest.panelStyle).toEqual({ minWidth: docked - 8, width: docked - 8 });
        expect(latest.chatStyle).toEqual({ '--compare-freeze-w': `${ROW - docked}px` });
        expect(latest.entering).toBe(false);
    });

    it('keeps the card as it is when the whole workspace closes', () => {
        const { rerender } = mount(true);
        rerender(<Harness comparing={false} open={false} />);
        expect(latest.panelStyle).toEqual({ minWidth: PANEL, width: PANEL });
        expect(latest.chatStyle).toEqual({ '--compare-freeze-w': `${ROW}px` });
    });

    it('stays off in the touch layout', () => {
        const { rerender } = mount(false, { enabled: false });
        rerender(<Harness comparing enabled={false} />);
        expect(latest.panelStyle).toBeUndefined();
        expect(latest.entering).toBe(false);
    });
});
