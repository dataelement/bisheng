import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Notifier, Toaster, notification, toast } from '@bisheng/ui';
import { Sheet, SheetContent, SheetTitle } from './index';

afterEach(cleanup);

it.each(['notification', 'toast'])('keeps the sheet open when a portaled %s is dismissed', async kind => {
    const onOpenChange = vi.fn();
    render(<><Notifier closeLabel="Dismiss notice" /><Toaster closeLabel="Dismiss toast" /><Sheet open onOpenChange={onOpenChange}><SheetContent><SheetTitle>Editor</SheetTitle></SheetContent></Sheet></>);
    act(() => {
        if (kind === 'notification') notification.open({ type: 'error', description: 'Connection failed', duration: 0 });
        else toast.show({ type: 'error', message: 'Connection failed', duration: 0 });
    });
    await act(() => new Promise(resolve => setTimeout(resolve, 0)));
    const close = screen.getByRole('button', { name: kind === 'notification' ? 'Dismiss notice' : 'Dismiss toast', hidden: true });
    fireEvent.pointerDown(close, { pointerType: 'mouse', button: 0 });
    fireEvent.click(close);
    expect(onOpenChange).not.toHaveBeenCalled();
    act(() => { notification.closeAll(); toast.clear(); });
});
