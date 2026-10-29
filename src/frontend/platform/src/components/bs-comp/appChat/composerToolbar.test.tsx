import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { ConversationComposer } from '@bisheng/chat';
import { SpeechToTextComponent } from '@/components/voiceFunction/speechToText';
import ChatFiles, { type ChatFilesHandle } from '@/pages/BuildPage/flow/FlowChat/ChatFiles';

vi.mock('@/controllers/API/workbench', () => ({ speechToText: vi.fn() }));
vi.mock('@/controllers/API/flow', () => ({ uploadChatFile: vi.fn() }));
vi.mock('@/util/utils', () => ({ getFileExtension: (name: string) => name.split('.').pop() ?? '' }));
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: { uploadFileMaxSize: 50 } }) }));
vi.mock('@/components/voiceFunction/audioPlayerStore', () => ({
    useAudioPlayerStore: () => ({ stopAudio: vi.fn(), setCurrentPlayingId: vi.fn() }),
    useAudioStore: () => ({ setIsLoading: vi.fn() }),
}));
afterEach(cleanup);

it('puts the actual platform voice control in the shared toolbar and opens the existing file picker', () => {
    const inputRef = createRef<HTMLTextAreaElement>();
    const fileRef = createRef<ChatFilesHandle>();
    const { container } = render(<ConversationComposer inputRef={inputRef} canExecute onSend={vi.fn()}
        labels={{ send: 'Send', stop: 'Stop', restart: 'Restart', attach: 'Attach' }}
        onAttach={() => fileRef.current?.openPicker()}
        voice={<SpeechToTextComponent inline onChange={vi.fn()} />}
        attachments={<ChatFiles ref={fileRef} accepts="*" disabled={false} v="v1" onChange={vi.fn()} />} />);
    const voice = screen.getByRole('button', { name: 'voiceInput.start' });
    const send = screen.getByRole('button', { name: 'Send' });
    const attach = screen.getByRole('button', { name: 'Attach' });
    expect(voice.parentElement).toBe(send.parentElement);
    expect(attach.parentElement).toBe(send.parentElement);
    expect(voice).toHaveClass('rounded-full');
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const click = vi.spyOn(input!, 'click');
    fireEvent.click(attach);
    expect(click).toHaveBeenCalledTimes(1);
});

it('retains the existing voice placement outside shared conversation composers', () => {
    render(<SpeechToTextComponent onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'voiceInput.start' }).parentElement).toHaveClass('absolute', 'right-12', 'top-5');
});
