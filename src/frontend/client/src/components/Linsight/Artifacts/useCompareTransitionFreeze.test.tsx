import { act, render } from '@testing-library/react';
import { useRef } from 'react';
import { CHAT_FREEZE_VAR, COMPARE_SETTLE_MS, useCompareTransitionFreeze } from './useCompareTransitionFreeze';

const ROW = 1480;
const CHAT = 760;
const PANEL = 712;

function widthOf(width: number) {
    return () => ({ width } as DOMRect);
}

function Harness({ comparing, open = true, enabled = true }: { comparing: boolean; open?: boolean; enabled?: boolean }) {
    const panelRef = useRef<HTMLDivElement>(null);
    const { rowRef, chatRef } = useCompareTransitionFreeze(comparing, open, enabled, panelRef);
    return (
        <div ref={rowRef} data-testid="row">
            <div ref={chatRef} data-testid="chat" />
            <div ref={panelRef} data-testid="panel" />
        </div>
    );
}

function mount(comparing: boolean, props: { open?: boolean; enabled?: boolean } = {}) {
    const utils = render(<Harness comparing={comparing} {...props} />);
    utils.getByTestId('row').getBoundingClientRect = widthOf(ROW);
    utils.getByTestId('chat').getBoundingClientRect = widthOf(CHAT);
    utils.getByTestId('panel').getBoundingClientRect = widthOf(PANEL);
    const chatPin = () => utils.getByTestId('chat').style.getPropertyValue(CHAT_FREEZE_VAR);
    const panelPin = () => {
        const { width, minWidth } = utils.getByTestId('panel').style;
        return width === minWidth ? width : `${width}|${minWidth}`;
    };
    return { ...utils, chatPin, panelPin };
}

function settle() {
    act(() => {
        jest.advanceTimersByTime(COMPARE_SETTLE_MS);
    });
}

describe('useCompareTransitionFreeze', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('does nothing until compare is toggled', () => {
        const { chatPin, panelPin } = mount(false);
        expect(chatPin()).toBe('');
        expect(panelPin()).toBe('');
    });

    it('pins the panel to the full row and the chat to its current width while entering', () => {
        const { rerender, chatPin, panelPin } = mount(false);
        rerender(<Harness comparing />);
        expect(panelPin()).toBe(`${ROW - 8}px`);
        expect(chatPin()).toBe(`${CHAT}px`);

        // Settled: the panel is free, the hidden chat keeps its width so it is
        // never laid out at ~0px while compare stays open.
        settle();
        expect(panelPin()).toBe('');
        expect(chatPin()).toBe(`${CHAT}px`);
    });

    it('pins both to the docked layout while leaving compare, then releases them', () => {
        const { rerender, chatPin, panelPin } = mount(true);
        rerender(<Harness comparing={false} />);
        // clamp(440px, 46%, 720px) of 1480 → 680.8
        const docked = ROW * 0.46;
        expect(panelPin()).toBe(`${docked - 8}px`);
        expect(chatPin()).toBe(`${ROW - docked}px`);

        settle();
        expect(panelPin()).toBe('');
        expect(chatPin()).toBe('');
    });

    it('keeps the card as it is when the whole workspace closes', () => {
        const { rerender, chatPin, panelPin } = mount(true);
        rerender(<Harness comparing={false} open={false} />);
        expect(panelPin()).toBe(`${PANEL}px`);
        expect(chatPin()).toBe(`${ROW}px`);
    });

    it('stays off in the touch layout', () => {
        const { rerender, chatPin, panelPin } = mount(false, { enabled: false });
        rerender(<Harness comparing enabled={false} />);
        expect(chatPin()).toBe('');
        expect(panelPin()).toBe('');
    });
});
