import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { getAttachmentUrl } from '~/api/chatApi';
import { MessageAttachments } from './MessageAttachments';

jest.mock('~/api/chatApi', () => ({ getAttachmentUrl: jest.fn() }));
jest.mock('~/api/runApi', () => ({ getRunFileUrl: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/useLocalize', () => () => (key: string, options?: { 0: number }) => (
    key === 'com_folder_upload_file_count' ? `${options?.[0]} files` : key
));
jest.mock('~/hooks/usePrefersMobileLayout', () => () => false);
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn() }));
jest.mock('~/pages/knowledge/knowledgeUtils', () => ({ isMediaFileName: (name: string) => name.endsWith('.mp3') }));
jest.mock('~/pages/knowledge/FilePreview', () => () => null);
jest.mock('~/pages/knowledge/FilePreview/viewers', () => ({ getViewerType: () => 'pdf' }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' '), downloadFile: jest.fn() }));
jest.mock('./MediaPlaybackDialog', () => ({ open }: { open: boolean }) => open ? <div>Media playback</div> : null);

test('keeps sent folder uploads grouped and preserves click-through to member files', () => {
    const onPreviewFile = jest.fn();
    render(<MessageAttachments conversationId="chat" onPreviewFile={onPreviewFile} files={[
        { file_id: 'first', name: 'Budget.pdf', filepath: '/bisheng/budget', relative_path: 'Reports/2025/Budget.pdf' },
        { file_id: 'second', name: 'Notes.pdf', filepath: '/bisheng/notes', relative_path: 'Reports/Notes.pdf' },
        { file_id: 'loose', name: 'Brief.pdf', filepath: '/bisheng/brief', size: 1024 },
    ]} />);

    const folder = screen.getByRole('button', { name: 'Reports (2 files)' });
    expect(folder).toHaveClass('dsh-composer-chip');
    expect(folder).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Budget.pdf')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Brief.pdf PDF · 1KB/ })).toHaveClass('dsh-composer-chip');
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();

    fireEvent.keyDown(folder, { key: 'Enter' });
    expect(folder).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(screen.getByRole('button', { name: /Budget.pdf/ }));
    expect(onPreviewFile).toHaveBeenCalledWith(expect.objectContaining({ file_id: 'first', file_name: 'Budget.pdf' }));
    fireEvent.click(folder);
    expect(screen.queryByText('Budget.pdf')).not.toBeInTheDocument();
});

test('refreshes a sent image inside the same thumbnail card as the composer', async () => {
    jest.mocked(getAttachmentUrl).mockResolvedValueOnce('https://storage.local/bisheng/fresh.png');
    const { container } = render(<MessageAttachments conversationId="chat" files={[
        { file_id: 'photo', name: 'photo.png', filepath: '/bisheng/old.png' },
    ]} />);

    const card = screen.getByRole('button', { name: /photo.png/ });
    expect(card).toHaveClass('dsh-composer-thumbnail');
    fireEvent.error(container.querySelector('img')!);
    await waitFor(() => expect(container.querySelector('img')).toHaveAttribute('src', '/bisheng/fresh.png'));
    expect(getAttachmentUrl).toHaveBeenCalledWith('chat', 'photo');
});

test('retains media playback on the sent resource card', () => {
    render(<MessageAttachments files={[
        { name: 'meeting.mp3', filepath: '/bisheng/meeting', mediaDurationSec: 65 },
    ]} />);

    const media = screen.getByRole('button', { name: /meeting.mp3 MP3 · 1:05/ });
    expect(media).toHaveClass('dsh-composer-chip');
    fireEvent.click(media);
    expect(screen.getByText('Media playback')).toBeInTheDocument();
});
