import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ConversationAttachments, type AttachmentServices } from './ConversationAttachments';
import { normalizeHistory } from '../core/normalizeHistory';
afterEach(cleanup);
const labels = { download: 'Download', unavailable: 'Unavailable', close: 'Close', preview: 'Preview' };
const options = { mode: 'workflow' as const, sessionKey: 'a' };
it('keeps video poster and duration metadata across normalization and the media port', () => {
  const files = normalizeHistory([{ category: 'answer', files: [{ name: 'video.mp4', path: '/video', cover_filepath: '/poster.png', mediaDurationSec: 24 }] }], options)[0].files;
  const renderMedia = vi.fn(file => <span>{file.name}</span>);
  render(<ConversationAttachments files={files} services={{ labels, resolveUrl: value => value, onDownload: vi.fn(), renderMedia }} />);
  expect(renderMedia).toHaveBeenCalledWith(expect.objectContaining({ name: 'video.mp4', url: '/video', raw: expect.objectContaining({ cover_filepath: '/poster.png', mediaDurationSec: 24 }) }));
});
it('downloads the exact selected file through the host', () => {
  const files = normalizeHistory([{ category: 'answer', files: [{ name: 'report.pdf', path: '/report' }] }], options)[0].files;
  const onDownload = vi.fn();
  render(<ConversationAttachments files={files} services={{ labels, resolveUrl: value => value, onDownload }} />);
  fireEvent.click(screen.getByText('report.pdf'));
  expect(onDownload).toHaveBeenCalledWith(files[0]);
});
it('replaces a failed stored image URL with its freshly authorized URL', async () => {
  let resolve: (url: string) => void = () => undefined;
  const files = normalizeHistory([{ category: 'question', files: [{ id: 'file-1', name: 'picture.png', path: '/expired' }] }], options)[0].files;
  const services: AttachmentServices = { labels, resolveUrl: value => value, onDownload: vi.fn(), getImageUrl: () => new Promise(done => { resolve = done; }) };
  render(<ConversationAttachments files={files} services={services} />);
  fireEvent.error(screen.getByAltText('picture.png'));
  expect(screen.getByText('Unavailable')).toBeTruthy();
  await act(async () => { resolve('/fresh'); });
  expect(screen.getByAltText('picture.png').getAttribute('src')).toBe('/fresh');
});
